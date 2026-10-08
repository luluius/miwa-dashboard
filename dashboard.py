"""
Miwa Control Center - Serveur Aiohttp avec support d'édition de statuts et profil.
"""

import os
import json
import time
import re
from aiohttp import web

# Import optionnel de Telethon pour le flow de connexion Telegram
try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

# Sessions Telegram en cours d'authentification { account_id: {client, phone, phone_code_hash} }
_pending_tg_auth = {}

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "miwa2026")
PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Charger le .env manuellement si les variables ne sont pas dans l'environnement
def _load_env_file():
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val

_load_env_file()

ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")
HTML_FILE = os.path.join(BASE_DIR, "dashboard.html")
PAYMENT_LINKS_FILE = os.path.join(BASE_DIR, "payment_links.json")
SCRIPTS_FILE = os.path.join(BASE_DIR, "scripts.json")
VAULT_FILE = os.path.join(BASE_DIR, "vault_media.json")
TAGS_FILE = os.path.join(BASE_DIR, "custom_tags.json")
TAGS_REGISTRY_FILE = os.path.join(BASE_DIR, "fan_tags_registry.json")
RATES_RULES_FILE = os.path.join(BASE_DIR, "rates_rules.json")
MEDIA_DIR = os.path.join(BASE_DIR, "media")
VAULT_DIR = os.path.join(BASE_DIR, "vault")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

def load_tags_registry():
    return load_json(TAGS_REGISTRY_FILE) or {}

def save_fan_tag_to_registry(account_id, user_id, tag_id, sender_name=""):
    reg = load_tags_registry()
    key = f"{account_id}:{user_id}"
    if tag_id:
        reg[key] = {
            "account_id": account_id,
            "user_id": str(user_id),
            "tag_id": tag_id,
            "sender_name": sender_name,
            "updated_at": time.time()
        }
    else:
        reg.pop(key, None)
    save_json(TAGS_REGISTRY_FILE, reg)


# Helper pour obtenir les chemins de données selon le compte
def get_account_id(request):
    try:
        aid = request.query.get("account", "").strip()
        if not aid and request.can_read_body:
            pass
        return aid if aid else "default"
    except Exception:
        return "default"

def get_account_paths(account_id="default"):
    aid = (account_id or "default").strip()
    if aid == "default" or not aid:
        return {
            "states": os.path.join(BASE_DIR, "chat_states.json"),
            "histories": os.path.join(BASE_DIR, "conversation_histories.json"),
            "queue": os.path.join(BASE_DIR, "message_queue.json"),
            "presence": os.path.join(BASE_DIR, "user_presence.json"),
            "stars": os.path.join(BASE_DIR, "stars_data.json"),
            "stars_flag": os.path.join(BASE_DIR, "stars_refresh.flag"),
        }
    return {
        "states": os.path.join(BASE_DIR, f"chat_states_{aid}.json"),
        "histories": os.path.join(BASE_DIR, f"conversation_histories_{aid}.json"),
        "queue": os.path.join(BASE_DIR, f"message_queue_{aid}.json"),
        "presence": os.path.join(BASE_DIR, f"user_presence_{aid}.json"),
        "stars": os.path.join(BASE_DIR, f"stars_data_{aid}.json"),
        "stars_flag": os.path.join(BASE_DIR, f"stars_refresh_{aid}.flag"),
    }

# Compatibilité descendante
STATES_FILE = os.path.join(BASE_DIR, "chat_states.json")
HISTORIES_FILE = os.path.join(BASE_DIR, "conversation_histories.json")
QUEUE_FILE = os.path.join(BASE_DIR, "message_queue.json")
USER_PRESENCE_FILE = os.path.join(BASE_DIR, "user_presence.json")
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(VAULT_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

DEFAULT_RATES_RULES = {
    "rates": [
        {"title": "Photo exclusive", "price": "10 €", "desc": "Selfie coquin ou lingerie"},
        {"title": "Pack 3 photos", "price": "25 €", "desc": "Série exclusive personnalisée"},
        {"title": "Vidéo courte (15-30s)", "price": "35 €", "desc": "Vidéo déshabillage ou bisous"},
        {"title": "Vidéo personnalisée (1-2min)", "price": "60 €", "desc": "Avec prénom prononcé"},
        {"title": "Sexting live 15 min", "price": "40 €", "desc": "Discussion coquine en temps réel + 2 photos"},
        {"title": "Abonnement VIP Uncove", "price": "15 € / mois", "desc": "Accès à tous les médias privés"}
    ],
    "rules": [
        "Ne JAMAIS promettre de rencontre réelle dans la vraie vie.",
        "Toujours utiliser le prénom du fan pour créer une proximité immédiate.",
        "Rester naturelle, chaleureuse, un peu taquine, ne jamais être agressive.",
        "Pour chaque demande intime, orienter vers un lien de paiement avec douceur.",
        "Ne jamais revendre un média déjà envoyé au même fan (vérifier le badge Vault)."
    ]
}

AI_DETECTION_PATTERNS = [
    r"\b(?:es[\s\-]tu|t[\'’]es|tu es|c[\'’]est)\s+(?:un\s+)?(?:robot|bot)\b",
    r"\b(?:es[\s\-]tu|t[\'’]es|tu es|c[\'’]est)\s+(?:une\s+)?ia\b",
    r"\b(?:intelligence artificielle|chatgpt|deepfake|deep fake|faux profil|fake profil|compte fake)\b",
    r"\b(?:es[\s\-]tu|t[\'’]es|tu es)\s+(?:une\s+)?(?:r[eé]elle|vraie personne|humain[e]?)\b",
    r"\b(?:tu existes vraiment|tu es fake|t\'es fake|es[\s\-]tu vraie|es[\s\-]tu vrai)\b",
    r"\b(?:on dirait un robot|on dirait une ia|parler [aà] un humain|vraie femme)\b",
    r"\b(?:hamadou)\b",
    r"\b(?:arnaque|arnaqueur|scam)\b",
]

COLOR_STYLES = {
    "sky": {"badge": "bg-[#2563eb] text-white border-[#1d4ed8] font-semibold", "dot": "bg-[#2563eb]", "hex": "#2563eb"},
    "rose": {"badge": "bg-[#dc2626] text-white border-[#b91c1c] font-semibold", "dot": "bg-[#dc2626]", "hex": "#dc2626"},
    "emerald": {"badge": "bg-[#16a34a] text-white border-[#15803d] font-semibold", "dot": "bg-[#16a34a]", "hex": "#16a34a"},
    "amber": {"badge": "bg-[#d97706] text-white border-[#b45309] font-semibold", "dot": "bg-[#d97706]", "hex": "#d97706"},
    "violet": {"badge": "bg-[#7c3aed] text-white border-[#6d28d9] font-semibold", "dot": "bg-[#7c3aed]", "hex": "#7c3aed"},
    "fuchsia": {"badge": "bg-[#c026d3] text-white border-[#a21caf] font-semibold", "dot": "bg-[#c026d3]", "hex": "#c026d3"},
    "cyan": {"badge": "bg-[#0891b2] text-white border-[#0e7490] font-semibold", "dot": "bg-[#0891b2]", "hex": "#0891b2"},
    "yellow": {"badge": "bg-[#ca8a04] text-white border-[#a16207] font-semibold", "dot": "bg-[#ca8a04]", "hex": "#ca8a04"},
    "orange": {"badge": "bg-[#ea580c] text-white border-[#c2410c] font-semibold", "dot": "bg-[#ea580c]", "hex": "#ea580c"},
    "slate": {"badge": "bg-[#475569] text-white border-[#334155] font-semibold", "dot": "bg-[#475569]", "hex": "#475569"},
    "gold": {"badge": "bg-gradient-to-r from-amber-400 via-yellow-300 to-amber-500 text-amber-950 border-amber-400 font-bold shadow-sm", "dot": "bg-amber-400", "hex": "#f59e0b"}
}

DEFAULT_TAGS = [
    {"id": "fan", "label": "Fan", "color": "sky", "is_default": True},
    {"id": "timewaster", "label": "Timewaster", "color": "rose", "is_default": True},
    {"id": "spender", "label": "Spender", "color": "emerald", "is_default": True},
    {"id": "masquer", "label": "Masquer", "color": "gold", "is_default": True}
]

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def create_backup(label="bulk"):
    """Sauvegarde chat_states + conversation_histories avant une action destructive."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_name = f"{ts}_{label}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    os.makedirs(backup_path, exist_ok=True)
    try:
        import shutil
        if os.path.exists(STATES_FILE):
            shutil.copy2(STATES_FILE, os.path.join(backup_path, "chat_states.json"))
        if os.path.exists(HISTORIES_FILE):
            shutil.copy2(HISTORIES_FILE, os.path.join(backup_path, "conversation_histories.json"))
        if os.path.exists(USER_PRESENCE_FILE):
            shutil.copy2(USER_PRESENCE_FILE, os.path.join(backup_path, "user_presence.json"))
        return backup_name
    except Exception as e:
        return None

def load_tags():
    tags = load_json(TAGS_FILE)
    if not isinstance(tags, list) or not tags:
        tags = DEFAULT_TAGS
    # S'assurer que le tag masquer existe toujours
    tag_ids = [t.get('id') for t in tags]
    if 'masquer' not in tag_ids and 'dore' not in tag_ids:
        tags.append({'id': 'masquer', 'label': 'Masquer', 'color': 'gold', 'is_default': True})
    else:
        # Renommer dore en masquer si present
        for t in tags:
            if t.get('id') in ('dore', 'masquer'):
                t['id'] = 'masquer'
                t['label'] = 'Masquer'
                t['color'] = 'gold'
    save_json(TAGS_FILE, tags)
    return tags

def save_tags(tags):
    return save_json(TAGS_FILE, tags)

def get_fan_status(state, user_id: str, tags_dict: dict, account_id: str = "default"):
    # PRIORITÉ ABSOLUE : Vérifier d'abord le registre permanent indépendant
    reg = load_tags_registry()
    reg_entry = reg.get(f"{account_id}:{user_id}")
    if reg_entry and reg_entry.get("tag_id"):
        tag_id = reg_entry["tag_id"]
        # Réinjecter directement dans le state pour synchroniser
        state["tag_id"] = tag_id
        state["manual_status"] = tag_id
    else:
        tag_id = state.get("tag_id") or state.get("manual_status")

    if not tag_id or tag_id not in tags_dict:
        return "", "", "", "", False
    tag = tags_dict[tag_id]
    color = tag.get("color", "sky")
    cfg = COLOR_STYLES.get(color, COLOR_STYLES["sky"])
    return tag["id"], tag["label"], cfg["badge"], cfg["dot"], True

async def index_handler(request):
    try:
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            html = f.read()
    except Exception as e:
        html = f"<h1>Erreur: {e}</h1>"
    return web.Response(text=html, content_type="text/html")

async def api_fans_handler(request):
    token = request.query.get("token", "")
    if token != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    acc_id = request.query.get("account", "default") or "default"
    paths = get_account_paths(acc_id)
    chat_states = load_json(paths["states"])
    histories = load_json(paths["histories"])
    presence = load_json(paths["presence"])
    tags_list = load_tags()
    tags_dict = {t["id"]: t for t in tags_list}
    now = time.time()
    all_uids = list(dict.fromkeys(list(chat_states.keys()) + list(histories.keys())))
    fans = []
    stars_info = load_json(paths["stars"])
    stats = {
        "total_fans": len(all_uids),
        "unread": 0,
        "followup": 0,
        "total_revenue": 0,
        "stars_balance": stars_info.get("balance", 0) if isinstance(stars_info, dict) else 0,
        "stars_earned": stars_info.get("total_earned", 0) if isinstance(stars_info, dict) else 0,
    }
    for t in tags_list:
        stats[t["id"]] = 0

    for uid in all_uids:
        state = chat_states.get(str(uid), {})
        user_history = histories.get(str(uid), [])
        if not state and not user_history:
            continue
        last_msg_snippet = ""
        last_msg_time = state.get("last_message_time", 0)
        last_role = ""
        if user_history:
            last_msg = user_history[-1]
            last_msg_time = last_msg.get("timestamp", last_msg_time)
            last_role = last_msg.get("role", "")
            last_text = (last_msg.get("content") or "").strip()
            last_photo = last_msg.get("photo_url")

            prefix = "Miwa: " if last_role == "assistant" else ""
            if last_photo and not last_text:
                last_msg_snippet = f"{prefix}📷 Photo"
            elif last_photo and last_text:
                last_msg_snippet = f"{prefix}📷 {last_text}"
            elif last_text:
                last_msg_snippet = f"{prefix}{last_text}"
            else:
                last_msg_snippet = f"{prefix}Message"

        # Si masqué temporairement ("supprimé 1 fois") et aucun nouveau message reçu depuis
        hidden_until = state.get("hidden_until_time", 0)
        if hidden_until and last_msg_time <= hidden_until:
            continue

        p = presence.get(str(uid), {})
        is_online = bool(p.get("online", False))
        is_typing = bool(p.get("typing_until", 0) > now)

        sc, sl, bs, dot, is_manual = get_fan_status(state, uid, tags_dict, account_id=acc_id)
        if sc in stats:
            stats[sc] += 1

        # Règle non lu : si le dernier message vient du fan et n'est pas marqué lu -> NON LU
        if state.get("is_read", False) or state.get("last_message_from") == "miwa":
            is_unread = False
        elif state.get("last_message_from") == "fan" or last_role == "user":
            is_unread = True
        else:
            is_unread = False

        if is_unread:
            stats["unread"] += 1

        prof = state.get("fan_profile", {})
        try:
            total_spent = float(state.get("total_spent", prof.get("total_spent", 0)) or 0)
        except (ValueError, TypeError):
            total_spent = 0
        stats["total_revenue"] += total_spent

        followup_date = state.get("followup_date", prof.get("followup_date", ""))
        followup_note = state.get("followup_note", prof.get("followup_note", ""))
        if followup_date:
            stats["followup"] += 1

        is_blocked = bool(state.get("is_blocked", False))
        fans.append({
            "user_id": uid,
            "name": state.get("sender_name") or f"Fan {uid}",
            "is_blocked": is_blocked,
            "message_count": state.get("message_count", 0),
            "last_message_time": last_msg_time,
            "last_message": last_msg_snippet,
            "status_code": sc,
            "status_label": sl,
            "badge_style": bs,
            "dot_style": dot,
            "is_manual": is_manual,
            "profile": prof,
            "sent_vault_ids": state.get("sent_vault_ids", []),
            "total_spent": total_spent,
            "followup_date": followup_date,
            "followup_note": followup_note,
            "is_online": is_online,
            "is_typing": is_typing,
            "is_unread": is_unread,
            "is_unanswered": bool(last_role == "user" or state.get("last_message_from") == "fan")
        })
    fans.sort(key=lambda x: x["last_message_time"], reverse=True)
    return web.json_response({"stats": stats, "fans": fans, "tags": tags_list})

async def api_chat_handler(request):
    token = request.query.get("token", "")
    if token != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    uid = request.match_info.get("user_id", "")
    acc_id = request.query.get("account", "default") or "default"
    paths = get_account_paths(acc_id)
    histories = load_json(paths["histories"])
    return web.json_response({"user_id": uid, "history": histories.get(str(uid), [])})

async def api_status_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    user_id = str(body.get("user_id", "")).strip()
    tag_id = body.get("tag_id") if "tag_id" in body else body.get("status_code", "")
    if tag_id == "dore":
        tag_id = "masquer"
    acc_id = body.get("account", "default") or "default"
    paths = get_account_paths(acc_id)
    chat_states = load_json(paths["states"])
    if user_id not in chat_states:
        chat_states[user_id] = {"sender_name": f"Fan {user_id}"}
    chat_states[user_id]["tag_id"] = tag_id or ""
    chat_states[user_id]["manual_status"] = tag_id or ""
    save_json(paths["states"], chat_states)
    # Enregistrer dans le registre permanent indépendant
    save_fan_tag_to_registry(acc_id, user_id, tag_id, chat_states[user_id].get("sender_name", ""))
    return web.json_response({"ok": True, "tag_id": tag_id})

async def api_tags_handler(request):
    token = request.query.get("token", "")
    if token != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response({"tags": load_tags()})

async def api_create_tag_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    label = body.get("label", "").strip()
    color = body.get("color", "violet").strip()
    if not label:
        return web.json_response({"error": "Nom d'étiquette requis"}, status=400)
    if color not in COLOR_STYLES:
        color = "violet"

    tags = load_tags()
    tag_id = re.sub(r'[^a-zA-Z0-9_]', '', label.lower().replace(' ', '_'))
    if not tag_id or any(t["id"] == tag_id for t in tags):
        tag_id = f"{tag_id or 'tag'}_{str(int(time.time()))[-4:]}"

    new_tag = {"id": tag_id, "label": label, "color": color, "is_default": False}
    tags.append(new_tag)
    save_tags(tags)
    return web.json_response({"ok": True, "tag": new_tag, "tags": tags})

async def api_delete_tag_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    tag_id = body.get("id", "").strip()
    if not tag_id:
        return web.json_response({"error": "ID d'étiquette requis"}, status=400)
    if tag_id in ("fan", "timewaster", "spender"):
        return web.json_response({"error": "Impossible de supprimer une étiquette par défaut"}, status=400)

    tags = load_tags()
    tags = [t for t in tags if t["id"] != tag_id]
    save_tags(tags)

    chat_states = load_json(STATES_FILE)
    modified = False
    for uid, state in chat_states.items():
        if state.get("tag_id") == tag_id or state.get("manual_status") == tag_id:
            state["tag_id"] = "fan"
            state["manual_status"] = "fan"
            modified = True
    if modified:
        save_json(STATES_FILE, chat_states)

    return web.json_response({"ok": True, "tags": tags})

async def api_profile_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    user_id = str(body.get("user_id", "")).strip()
    new_profile = body.get("profile", {})

    acc_id = body.get("account", "default") or "default"
    paths = get_account_paths(acc_id)
    chat_states = load_json(paths["states"])
    if user_id in chat_states:
        curr = chat_states[user_id].get("fan_profile", {})
        for k, v in new_profile.items():
            if v is not None and v != "":
                curr[k] = v
            elif k in curr:
                del curr[k]
        chat_states[user_id]["fan_profile"] = curr
        if "total_spent" in new_profile:
            chat_states[user_id]["total_spent"] = new_profile["total_spent"]
        if "followup_date" in new_profile:
            chat_states[user_id]["followup_date"] = new_profile["followup_date"]
        if "followup_note" in new_profile:
            chat_states[user_id]["followup_note"] = new_profile["followup_note"]
        save_json(paths["states"], chat_states)
        return web.json_response({"ok": True, "profile": curr})
    return web.json_response({"error": "Utilisateur non trouvé"}, status=404)

async def api_send_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    user_id = str(body.get("user_id", "")).strip()
    message = str(body.get("message", "")).strip()
    if not user_id or not message:
        return web.json_response({"error": "user_id et message requis"}, status=400)

    acc_id = body.get("account", "default") or "default"
    paths = get_account_paths(acc_id)
    chat_states = load_json(paths["states"])
    user_state = chat_states.get(user_id, {}) if isinstance(chat_states, dict) else {}
    target_lang = user_state.get("language", "fr")

    should_translate = bool(body.get("translate", False))
    actual_telegram_message = message
    sent_content = None

    import gemini_client

    try:
        if should_translate and target_lang and target_lang != "fr":
            try:
                translated = await gemini_client.gemini_client.translate_to_language(message, target_lang)
                if translated and translated.strip():
                    actual_telegram_message = translated.strip()
                    sent_content = actual_telegram_message
            except Exception as e:
                print(f"Erreur traduction sortante: {e}")

        now_ts = time.time()
        hist_client = gemini_client.MiwaGeminiClient(history_file=paths["histories"])
        hist_client.add_message(
            user_id,
            "assistant",
            message,
            sent_content=sent_content,
            lang=target_lang,
            timestamp=now_ts,
            read=False
        )

        if isinstance(chat_states, dict) and user_id in chat_states:
            chat_states[user_id]["last_message_from"] = "miwa"
            chat_states[user_id]["last_message_time"] = now_ts
            chat_states[user_id]["message_count"] = chat_states[user_id].get("message_count", 0) + 1
            save_json(paths["states"], chat_states)

        queue = load_json(paths["queue"])
        if not isinstance(queue, list):
            queue = []
        queue.append({"user_id": int(user_id), "message": actual_telegram_message, "queued_at": now_ts, "source": "dashboard"})
        if save_json(paths["queue"], queue):
            return web.json_response({"ok": True})
        return web.json_response({"error": "Erreur écriture queue"}, status=500)
    except Exception as e:
        print(f"Erreur api_send_handler: {e}")
        return web.json_response({"error": f"Erreur serveur envoi: {e}"}, status=500)

async def api_suggest_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    user_id = str(body.get("user_id", "")).strip()
    if not user_id:
        return web.json_response({"error": "user_id requis"}, status=400)

    acc_id = body.get("account", "default") or "default"
    paths = get_account_paths(acc_id)
    histories = load_json(paths["histories"])
    history = histories.get(user_id, [])
    chat_states = load_json(paths["states"])
    fan_profile = chat_states.get(user_id, {}).get("fan_profile", {})

    import gemini_client
    try:
        suggestion = await gemini_client.gemini_client.suggest_reply(
            user_id=int(user_id),
            last_messages=history[-3:],
            fan_profile=fan_profile
        )
        return web.json_response({"ok": True, "suggestion": suggestion})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_payment_links_handler(request):
    token = request.query.get("token", "")
    if token != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    links = load_json(PAYMENT_LINKS_FILE)
    if not isinstance(links, list):
        links = []
    return web.json_response({"links": links})

async def api_save_payment_links_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    links = body.get("links", [])
    if not isinstance(links, list):
        return web.json_response({"error": "links doit être une liste"}, status=400)
    if save_json(PAYMENT_LINKS_FILE, links):
        return web.json_response({"ok": True})
    return web.json_response({"error": "Erreur écriture"}, status=500)


async def api_bulk_action_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    
    action = str(body.get("action", "")).strip() # 'delete' or 'block' or 'unblock'
    user_ids = body.get("user_ids", [])
    if not isinstance(user_ids, list) or not user_ids:
        return web.json_response({"error": "user_ids liste requise"}, status=400)

    acc_id = body.get("account", "default") or "default"
    paths = get_account_paths(acc_id)
    chat_states = load_json(paths["states"])
    histories = load_json(paths["histories"])
    presence = load_json(paths["presence"])

    # ── Sauvegarde automatique avant toute action destructive ──
    backup_name = create_backup(label=f"{action}_{acc_id}")

    count = 0
    if action == "delete":
        for uid in user_ids:
            uid_str = str(uid).strip()
            if uid_str in chat_states:
                del chat_states[uid_str]
                count += 1
            if uid_str in histories:
                del histories[uid_str]
            if uid_str in presence:
                del presence[uid_str]
        save_json(paths["states"], chat_states)
        save_json(paths["histories"], histories)
        save_json(paths["presence"], presence)
        return web.json_response({"ok": True, "action": "delete", "count": count, "backup": backup_name})

    elif action in ("block", "unblock"):
        is_blk = (action == "block")
        for uid in user_ids:
            uid_str = str(uid).strip()
            if uid_str in chat_states:
                chat_states[uid_str]["is_blocked"] = is_blk
                count += 1
        save_json(paths["states"], chat_states)
        return web.json_response({"ok": True, "action": action, "count": count, "backup": backup_name})

    return web.json_response({"error": "Action inconnue (delete, block, unblock)"}, status=400)


async def api_delete_chat_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    
    user_id = str(body.get("user_id", "")).strip()
    permanent = bool(body.get("permanent", False))
    
    if not user_id:
        return web.json_response({"error": "user_id requis"}, status=400)
        
    acc_id = body.get("account", "default") or "default"
    paths = get_account_paths(acc_id)
    chat_states = load_json(paths["states"])
    histories = load_json(paths["histories"])
    
    if permanent:
        if user_id in chat_states:
            del chat_states[user_id]
            save_json(paths["states"], chat_states)
        if user_id in histories:
            del histories[user_id]
            save_json(paths["histories"], histories)
        presence = load_json(paths["presence"])
        if user_id in presence:
            del presence[user_id]
            save_json(paths["presence"], presence)
        return web.json_response({"ok": True, "action": "permanent_deleted"})
    else:
        if user_id in chat_states:
            chat_states[user_id]["hidden_until_time"] = int(time.time())
            save_json(paths["states"], chat_states)
        return web.json_response({"ok": True, "action": "hidden_once"})

async def api_mark_read_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    user_id = str(body.get("user_id", "")).strip()
    acc_id = body.get("account", "default") or "default"
    paths = get_account_paths(acc_id)
    chat_states = load_json(paths["states"])
    if user_id in chat_states:
        chat_states[user_id]["last_message_from"] = "miwa"
        chat_states[user_id]["is_read"] = True
        save_json(paths["states"], chat_states)
        return web.json_response({"ok": True})
    return web.json_response({"error": "Fan introuvable"}, status=404)

async def api_send_media_handler(request):
    try:
        body = await request.json()
    except Exception as e:
        return web.json_response({"error": f"Invalid payload: {e}"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)

    user_id = str(body.get("user_id", "")).strip()
    image_b64 = body.get("image_b64", "").strip()
    caption = body.get("message", "").strip()
    orig_filename = body.get("filename", "image.jpg")
    if not user_id or not image_b64:
        return web.json_response({"error": "user_id et fichier requis"}, status=400)

    ext = os.path.splitext(orig_filename)[1].lower()
    if not ext or len(ext) > 6:
        ext = ".jpg"

    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    import base64
    try:
        img_data = base64.b64decode(image_b64)
    except Exception:
        return web.json_response({"error": "Fichier base64 invalide"}, status=400)

    os.makedirs(MEDIA_DIR, exist_ok=True)
    filename = f"miwa_send_{user_id}_{int(time.time())}{ext}"
    filepath = os.path.join(MEDIA_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(img_data)

    photo_url = f"/media/{filename}"
    now_ts = time.time()

    acc_id = body.get("account", "default") or "default"
    paths = get_account_paths(acc_id)

    chat_states = load_json(paths["states"])
    user_state = chat_states.get(user_id, {}) if isinstance(chat_states, dict) else {}
    target_lang = user_state.get("language", "fr")
    should_translate = bool(body.get("translate", False))
    actual_caption = caption

    if should_translate and caption and target_lang and target_lang != "fr":
        try:
            import gemini_client
            translated = await gemini_client.gemini_client.translate_to_language(caption, target_lang)
            if translated and translated.strip():
                actual_caption = translated.strip()
        except Exception as e:
            print(f"Erreur traduction caption: {e}")

    import gemini_client
    hist_client = gemini_client.MiwaGeminiClient(history_file=paths["histories"])
    hist_client.add_message(
        user_id,
        "assistant",
        caption,
        sent_content=actual_caption if actual_caption != caption else None,
        photo_url=photo_url,
        timestamp=now_ts,
        read=False
    )

    if isinstance(chat_states, dict) and user_id in chat_states:
        chat_states[user_id]["last_message_from"] = "miwa"
        chat_states[user_id]["last_message_time"] = now_ts
        chat_states[user_id]["message_count"] = chat_states[user_id].get("message_count", 0) + 1
        save_json(paths["states"], chat_states)

    queue = load_json(paths["queue"])
    if not isinstance(queue, list):
        queue = []
    queue.append({
        "user_id": int(user_id),
        "message": actual_caption,
        "media_path": filepath,
        "queued_at": now_ts,
        "source": "dashboard"
    })
    save_json(paths["queue"], queue)

    return web.json_response({"ok": True, "photo_url": photo_url})

async def api_scripts_handler(request):
    token = request.query.get("token", "")
    if token != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    scripts = load_json(SCRIPTS_FILE)
    if not isinstance(scripts, list):
        scripts = []
    return web.json_response({"scripts": scripts})

async def api_save_scripts_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    scripts = body.get("scripts", [])
    if not isinstance(scripts, list):
        return web.json_response({"error": "scripts doit être une liste"}, status=400)
    if save_json(SCRIPTS_FILE, scripts):
        return web.json_response({"ok": True})
    return web.json_response({"error": "Erreur écriture scripts"}, status=500)

async def api_vault_handler(request):
    token = request.query.get("token", "")
    if token != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    items = load_json(VAULT_FILE)
    if not isinstance(items, list):
        items = []
    return web.json_response({"items": items})

async def api_vault_upload_handler(request):
    try:
        body = await request.json()
    except Exception as e:
        return web.json_response({"error": f"Invalid JSON: {e}"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)

    title = body.get("title", "").strip() or "Média Vault"
    category = body.get("category", "Général").strip() or "Général"
    file_b64 = body.get("file_b64", "").strip()
    filename_orig = body.get("filename", "media.jpg")

    if not file_b64:
        return web.json_response({"error": "Fichier requis"}, status=400)

    ext = os.path.splitext(filename_orig)[1].lower()
    if not ext or len(ext) > 6:
        ext = ".jpg"

    if "," in file_b64:
        file_b64 = file_b64.split(",", 1)[1]

    import base64
    try:
        data = base64.b64decode(file_b64)
    except Exception:
        return web.json_response({"error": "Base64 invalide"}, status=400)

    import uuid
    uid_media = f"vault_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    filename = f"{uid_media}{ext}"
    filepath = os.path.join(VAULT_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(data)

    media_type = "video" if ext in [".mp4", ".mov", ".webm", ".mkv"] else "image"
    url = f"/vault/{filename}"
    new_item = {
        "id": uid_media,
        "title": title,
        "category": category,
        "url": url,
        "media_type": media_type,
        "filename": filename,
        "size": len(data),
        "created_at": time.time()
    }

    items = load_json(VAULT_FILE)
    if not isinstance(items, list):
        items = []
    items.insert(0, new_item)
    save_json(VAULT_FILE, items)

    return web.json_response({"ok": True, "item": new_item})

async def api_vault_delete_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    media_id = body.get("id")
    items = load_json(VAULT_FILE)
    if not isinstance(items, list):
        items = []
    
    found = None
    remaining = []
    for item in items:
        if item.get("id") == media_id:
            found = item
        else:
            remaining.append(item)

    if found:
        fn = found.get("filename")
        if fn:
            fp = os.path.join(VAULT_DIR, fn)
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
        save_json(VAULT_FILE, remaining)
        return web.json_response({"ok": True})
    return web.json_response({"error": "Élément non trouvé"}, status=404)

async def api_vault_send_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)

    user_id = str(body.get("user_id", "")).strip()
    media_id = body.get("id")
    caption = body.get("message", "").strip()

    if not user_id or not media_id:
        return web.json_response({"error": "user_id et id média requis"}, status=400)

    items = load_json(VAULT_FILE)
    target_item = next((item for item in items if item.get("id") == media_id), None)
    if not target_item:
        return web.json_response({"error": "Média introuvable dans le Vault"}, status=404)

    filepath = os.path.join(VAULT_DIR, target_item["filename"])
    if not os.path.exists(filepath):
        return web.json_response({"error": "Fichier physique introuvable sur le serveur"}, status=404)

    now_ts = time.time()
    photo_url = target_item["url"]

    acc_id = body.get("account", "default") or "default"
    paths = get_account_paths(acc_id)

    import gemini_client
    hist_client = gemini_client.MiwaGeminiClient(history_file=paths["histories"])
    hist_client.add_message(
        user_id,
        "assistant",
        caption,
        photo_url=photo_url,
        timestamp=now_ts,
        read=False
    )

    chat_states = load_json(paths["states"])
    if isinstance(chat_states, dict) and user_id in chat_states:
        chat_states[user_id]["last_message_from"] = "miwa"
        chat_states[user_id]["last_message_time"] = now_ts
        chat_states[user_id]["message_count"] = chat_states[user_id].get("message_count", 0) + 1
        sent_vault = chat_states[user_id].setdefault("sent_vault_ids", [])
        if media_id not in sent_vault:
            sent_vault.append(media_id)
        save_json(paths["states"], chat_states)

    queue = load_json(paths["queue"])
    if not isinstance(queue, list):
        queue = []
    queue.append({
        "user_id": int(user_id),
        "message": caption,
        "media_path": filepath,
        "queued_at": now_ts,
        "source": "vault"
    })
    save_json(paths["queue"], queue)

    return web.json_response({"ok": True, "photo_url": photo_url})

def load_rates_rules():
    data = load_json(RATES_RULES_FILE)
    if not isinstance(data, dict) or not data.get("rates"):
        save_json(RATES_RULES_FILE, DEFAULT_RATES_RULES)
        return DEFAULT_RATES_RULES
    return data

async def api_rates_rules_get_handler(request):
    token = request.query.get("token", "")
    if token != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response(load_rates_rules())

async def api_rates_rules_save_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    rates = body.get("rates", [])
    rules = body.get("rules", [])
    data = {"rates": rates, "rules": rules}
    if save_json(RATES_RULES_FILE, data):
        return web.json_response({"ok": True})
    return web.json_response({"error": "Erreur écriture"}, status=500)

async def api_backups_list_handler(request):
    """Lister les sauvegardes disponibles."""
    if request.rel_url.query.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    backups = []
    if os.path.exists(BACKUP_DIR):
        for name in sorted(os.listdir(BACKUP_DIR), reverse=True)[:20]:
            bp = os.path.join(BACKUP_DIR, name)
            if os.path.isdir(bp):
                states_path = os.path.join(bp, "chat_states.json")
                count = 0
                if os.path.exists(states_path):
                    try:
                        with open(states_path, "r", encoding="utf-8") as f:
                            count = len(json.load(f))
                    except Exception:
                        pass
                backups.append({"name": name, "fan_count": count})
    return web.json_response({"ok": True, "backups": backups})


async def api_backups_restore_handler(request):
    """Restaurer une sauvegarde."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    backup_name = str(body.get("backup_name", "")).strip()
    if not backup_name:
        return web.json_response({"error": "backup_name requis"}, status=400)
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.isdir(backup_path):
        return web.json_response({"error": "Sauvegarde introuvable"}, status=404)
    try:
        import shutil
        restored = []
        for fname, dest in [
            ("chat_states.json", STATES_FILE),
            ("conversation_histories.json", HISTORIES_FILE),
            ("user_presence.json", USER_PRESENCE_FILE),
        ]:
            src = os.path.join(backup_path, fname)
            if os.path.exists(src):
                shutil.copy2(src, dest)
                restored.append(fname)
        return web.json_response({"ok": True, "restored": restored, "backup": backup_name})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)



# ── GESTION DES COMPTES TELEGRAM (MULTI-COMPTE) ──
def load_accounts():
    accs = load_json(ACCOUNTS_FILE)
    if not isinstance(accs, list) or not accs:
        accs = [
            {"id": "default", "name": "Compte Principal", "phone": os.getenv("TELEGRAM_PHONE", ""), "is_default": True}
        ]
        save_json(ACCOUNTS_FILE, accs)
    return accs

async def api_accounts_list_handler(request):
    token = request.query.get("token", "")
    if token != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    accs = load_accounts()
    # Récupérer le statut et nombre de fans pour chaque compte
    results = []
    for a in accs:
        aid = a["id"]
        paths = get_account_paths(aid)
        states = load_json(paths["states"])
        total_fans = len(states)
        unread = sum(1 for s in states.values() if s.get("last_message_from") == "fan" and not s.get("is_read", False))
        sess_name = "miwa_personal_session" if aid == "default" else f"miwa_personal_session_{aid}"
        has_session = os.path.exists(os.path.join(BASE_DIR, f"{sess_name}.session"))
        results.append({
            "id": aid,
            "name": a.get("name", aid),
            "phone": a.get("phone", ""),
            "is_default": bool(a.get("is_default", False)),
            "total_fans": total_fans,
            "unread": unread,
            "has_session": has_session
        })
    return web.json_response({"ok": True, "accounts": results})

async def api_accounts_create_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    name = body.get("name", "").strip()
    phone = body.get("phone", "").strip()
    if not name:
        return web.json_response({"error": "Nom du compte requis"}, status=400)
    
    clean_id = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))
    if not clean_id or clean_id in ("default", "main"):
        clean_id = f"acc_{int(time.time())}"
    
    accs = load_accounts()
    if any(a["id"] == clean_id for a in accs):
        clean_id = f"{clean_id}_{str(int(time.time()))[-4:]}"
        
    new_acc = {
        "id": clean_id,
        "name": name,
        "phone": phone,
        "created_at": time.time(),
        "is_default": False
    }
    accs.append(new_acc)
    save_json(ACCOUNTS_FILE, accs)
    
    # Créer les fichiers vides associés pour ce compte
    paths = get_account_paths(clean_id)
    if not os.path.exists(paths["states"]):
        save_json(paths["states"], {})
    if not os.path.exists(paths["histories"]):
        save_json(paths["histories"], {})
    if not os.path.exists(paths["queue"]):
        save_json(paths["queue"], [])
    if not os.path.exists(paths["presence"]):
        save_json(paths["presence"], {})
        
    return web.json_response({"ok": True, "account": new_acc, "accounts": accs})

async def api_accounts_delete_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)
    aid = body.get("id", "").strip()
    if not aid or aid == "default":
        return web.json_response({"error": "Impossible de supprimer le compte principal"}, status=400)
    accs = load_accounts()
    accs = [a for a in accs if a["id"] != aid]
    save_json(ACCOUNTS_FILE, accs)
    return web.json_response({"ok": True, "accounts": accs})

async def api_accounts_connect_handler(request):
    """Étape 1 : envoie le code SMS pour connecter un nouveau compte Telegram."""
    if not TELETHON_AVAILABLE:
        return web.json_response({"error": "Telethon non installé sur le serveur"}, status=500)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON invalide"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)

    account_id = body.get("account_id", "").strip()
    phone = body.get("phone", "").strip()
    if not account_id or not phone:
        return web.json_response({"error": "account_id et phone requis"}, status=400)
    if account_id == "default":
        return web.json_response({"error": "Impossible de modifier le compte principal"}, status=400)

    api_id = int(os.getenv("API_ID") or os.getenv("TELEGRAM_API_ID") or "0")
    api_hash = os.getenv("API_HASH") or os.getenv("TELEGRAM_API_HASH") or ""
    if not api_id or not api_hash:
        return web.json_response({"error": "API_ID / API_HASH non configurés sur le serveur"}, status=500)

    # Si une session est déjà en cours pour ce compte, la fermer proprement
    if account_id in _pending_tg_auth:
        try:
            await _pending_tg_auth[account_id]["client"].disconnect()
        except Exception:
            pass
        del _pending_tg_auth[account_id]

    session_file = os.path.join(BASE_DIR, f"miwa_personal_session_{account_id}")
    client = TelegramClient(session_file, api_id, api_hash)
    try:
        await client.connect()
        result = await client.send_code_request(phone)
    except Exception as e:
        await client.disconnect()
        return web.json_response({"error": f"Erreur Telegram : {str(e)}"}, status=500)

    _pending_tg_auth[account_id] = {
        "client": client,
        "phone": phone,
        "phone_code_hash": result.phone_code_hash,
    }

    # Sauvegarder le numéro de tel dans accounts.json
    accs = load_accounts()
    for a in accs:
        if a["id"] == account_id:
            a["phone"] = phone
            break
    save_json(ACCOUNTS_FILE, accs)

    return web.json_response({"ok": True, "message": f"Code envoyé au {phone}"})


async def api_accounts_verify_handler(request):
    """Étape 2 : vérifie le code OTP (et optionnellement le mot de passe 2FA)."""
    if not TELETHON_AVAILABLE:
        return web.json_response({"error": "Telethon non installé"}, status=500)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "JSON invalide"}, status=400)
    if body.get("token", "") != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)

    account_id = body.get("account_id", "").strip()
    code = body.get("code", "").strip()
    password = body.get("password", "").strip()  # 2FA optionnel

    if account_id not in _pending_tg_auth:
        return web.json_response({"error": "Session expirée, recommence depuis le début"}, status=400)

    pending = _pending_tg_auth[account_id]
    client = pending["client"]
    phone = pending["phone"]
    phone_code_hash = pending["phone_code_hash"]

    try:
        if password:
            # Étape 2FA
            await client.sign_in(password=password)
        else:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)

        me = await client.get_me()
        await client.disconnect()
        del _pending_tg_auth[account_id]

        # Marquer le compte comme connecté dans accounts.json
        accs = load_accounts()
        for a in accs:
            if a["id"] == account_id:
                a["connected"] = True
                a["telegram_name"] = ((me.first_name or "") + " " + (me.last_name or "")).strip()
                a["telegram_username"] = me.username or ""
                break
        save_json(ACCOUNTS_FILE, accs)

        return web.json_response({"ok": True, "name": me.first_name or me.username or account_id})

    except SessionPasswordNeededError:
        return web.json_response({"ok": False, "need_2fa": True, "message": "Ce compte a une 2FA active, entre ton mot de passe Telegram"})
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        return web.json_response({"ok": False, "error": "Code invalide ou expiré"}, status=400)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


def _extract_stars_val(val):
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    if hasattr(val, "amount"):
        amt = getattr(val, "amount", 0) or 0
        nanos = getattr(val, "nanos", 0) or 0
        return round(amt + nanos / 1e9, 2) if nanos else int(amt)
    try:
        return int(val)
    except Exception:
        return 0


async def _direct_fetch_stars_for_account(account_id="default"):
    """Fallback de récupération directe via Telethon (copie temporaire de session) si le userbot n'a pas encore synchronisé."""
    if not TELETHON_AVAILABLE:
        return None
    api_id = int(os.getenv("API_ID") or os.getenv("TELEGRAM_API_ID") or "0")
    api_hash = os.getenv("API_HASH") or os.getenv("TELEGRAM_API_HASH") or ""
    if not api_id or not api_hash:
        return None

    sess_name = "miwa_personal_session" if account_id == "default" else f"miwa_personal_session_{account_id}"
    orig_session = os.path.join(BASE_DIR, f"{sess_name}.session")
    if not os.path.exists(orig_session):
        return None

    import shutil
    import datetime
    tmp_base = f"/tmp/miwa_stars_{account_id}_{os.getpid()}_{int(time.time())}"
    tmp_session = f"{tmp_base}.session"
    try:
        shutil.copy2(orig_session, tmp_session)
    except Exception:
        return None

    client = TelegramClient(tmp_base, api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return None

        from telethon.tl.functions.payments import GetStarsStatusRequest
        from telethon.tl.types import InputPeerSelf

        status = await client(GetStarsStatusRequest(peer=InputPeerSelf()))
        balance = _extract_stars_val(getattr(status, "balance", 0))
        all_txs = list(getattr(status, "history", []) or [])
        users_map = {u.id: u for u in (getattr(status, "users", []) or [])}
        chats_map = {c.id: c for c in (getattr(status, "chats", []) or [])}
        next_offset = getattr(status, "next_offset", None)

        if next_offset:
            try:
                from telethon.tl.functions.payments import GetStarsTransactionsRequest
                for _ in range(3):
                    if not next_offset:
                        break
                    try:
                        page = await client(GetStarsTransactionsRequest(peer=InputPeerSelf(), offset=next_offset, limit=100))
                    except TypeError:
                        page = await client(GetStarsTransactionsRequest(peer=InputPeerSelf(), offset=next_offset))
                    page_txs = list(getattr(page, "history", []) or [])
                    if not page_txs:
                        break
                    all_txs.extend(page_txs)
                    for u in (getattr(page, "users", []) or []):
                        users_map[u.id] = u
                    for c in (getattr(page, "chats", []) or []):
                        chats_map[c.id] = c
                    new_offset = getattr(page, "next_offset", None)
                    if not new_offset or new_offset == next_offset:
                        break
                    next_offset = new_offset
            except Exception:
                pass

        gifts_count = 0
        gifts_stars = 0
        gifts_convert_stars = 0
        try:
            from telethon.tl.functions.payments import GetSavedStarGiftsRequest
            saved_gifts = await client(GetSavedStarGiftsRequest(peer=InputPeerSelf(), offset="", limit=100))
            gifts_list = getattr(saved_gifts, "gifts", []) or []
            gifts_count = getattr(saved_gifts, "count", len(gifts_list)) or len(gifts_list)
            for g in gifts_list:
                gift_obj = getattr(g, "gift", None)
                if gift_obj:
                    gifts_stars += _extract_stars_val(getattr(gift_obj, "stars", 0))
                    gifts_convert_stars += _extract_stars_val(getattr(gift_obj, "convert_stars", 0))
        except Exception:
            pass

        paths = get_account_paths(account_id)
        chat_states = load_json(paths["states"])
        now_ts = time.time()
        midnight_today_ts = now_ts - (now_ts % 86400)
        ts_7d = now_ts - 7 * 86400
        ts_30d = now_ts - 30 * 86400

        earned_from_fans = 0
        topped_up = 0
        total_in = 0
        total_out = 0
        earned_today = 0
        earned_7d = 0
        earned_30d = 0
        donors_map = {}
        transactions_formatted = []
        seen_tx_ids = set()

        for tx in all_txs:
            tx_id = str(getattr(tx, "id", ""))
            raw_amt = getattr(tx, "stars", None) if getattr(tx, "stars", None) is not None else getattr(tx, "amount", 0)
            stars = _extract_stars_val(raw_amt)
            dt = getattr(tx, "date", None)
            ts = int(dt.timestamp()) if dt else 0
            tx_key = f"{tx_id}_{stars}_{ts}"
            if tx_id and tx_key in seen_tx_ids:
                continue
            seen_tx_ids.add(tx_key)

            is_refund = bool(getattr(tx, "refund", False))
            is_pending = bool(getattr(tx, "pending", False))
            is_failed = bool(getattr(tx, "failed", False))
            is_gift = bool(getattr(tx, "gift", False) or getattr(tx, "stargift", False))
            is_reaction = bool(getattr(tx, "reaction", False))
            title = getattr(tx, "title", "") or ""
            description = getattr(tx, "description", "") or ""

            peer_wrapper = getattr(tx, "peer", None)
            peer_cls = type(peer_wrapper).__name__ if peer_wrapper else ""
            user_id_str = ""
            username = ""
            source_name = "Telegram"
            source_type = "other"

            if hasattr(peer_wrapper, "peer"):
                inner = peer_wrapper.peer
                uid = getattr(inner, "user_id", None) or getattr(inner, "channel_id", None) or getattr(inner, "chat_id", None)
                if uid:
                    user_id_str = str(uid)
                    source_type = "fan"
                    if uid in users_map:
                        u = users_map[uid]
                        fn = (getattr(u, "first_name", "") or "").strip()
                        ln = (getattr(u, "last_name", "") or "").strip()
                        username = getattr(u, "username", "") or ""
                        source_name = f"{fn} {ln}".strip() or (f"@{username}" if username else f"Fan {uid}")
                    elif uid in chats_map:
                        c = chats_map[uid]
                        source_name = getattr(c, "title", f"Chat {uid}")
                    elif user_id_str in chat_states:
                        source_name = chat_states[user_id_str].get("sender_name") or f"Fan {uid}"
                    else:
                        source_name = f"Fan {uid}"
            elif "AppStore" in peer_cls:
                source_name = "Apple App Store"
                source_type = "platform"
            elif "PlayMarket" in peer_cls:
                source_name = "Google Play"
                source_type = "platform"
            elif "Fragment" in peer_cls:
                source_name = "Fragment (Retrait / Achat)"
                source_type = "fragment"
            elif "PremiumBot" in peer_cls:
                source_name = "Telegram PremiumBot"
                source_type = "platform"
            elif "Ads" in peer_cls:
                source_name = "Telegram Ads"
                source_type = "platform"

            if is_refund:
                type_label = "Remboursement"
            elif is_reaction:
                type_label = "Réaction Étoile ⭐"
            elif is_gift:
                type_label = "Cadeau Étoile 🎁"
            elif getattr(tx, "extended_media", None):
                type_label = "Média débloqué 🔒"
            elif source_type == "platform" and stars > 0:
                type_label = "Rechargement Stars"
            elif source_type == "fragment" and stars < 0:
                type_label = "Retrait Fragment"
            elif title:
                type_label = title
            elif stars > 0:
                type_label = "Gain d'Étoiles ⭐"
            else:
                type_label = "Dépense d'Étoiles"

            if not is_failed and not is_refund:
                if stars > 0:
                    total_in += stars
                    if source_type in ("fan", "other"):
                        earned_from_fans += stars
                        if ts >= midnight_today_ts:
                            earned_today += stars
                        if ts >= ts_7d:
                            earned_7d += stars
                        if ts >= ts_30d:
                            earned_30d += stars
                        if user_id_str:
                            d_entry = donors_map.setdefault(user_id_str, {
                                "user_id": user_id_str,
                                "name": source_name,
                                "username": username,
                                "total_stars": 0,
                                "tx_count": 0
                            })
                            d_entry["total_stars"] += stars
                            d_entry["tx_count"] += 1
                    elif source_type == "platform":
                        topped_up += stars
                elif stars < 0:
                    total_out += abs(stars)

            if len(transactions_formatted) < 100:
                transactions_formatted.append({
                    "id": tx_id,
                    "stars": stars,
                    "timestamp": ts,
                    "type_label": type_label,
                    "source_name": source_name,
                    "source_type": source_type,
                    "user_id": user_id_str,
                    "username": username,
                    "title": title,
                    "description": description,
                    "is_gift": is_gift,
                    "is_reaction": is_reaction,
                    "is_refund": is_refund,
                    "is_pending": is_pending,
                    "is_failed": is_failed
                })

        total_earned = earned_from_fans if earned_from_fans > 0 else max(0, total_in - topped_up)
        if gifts_stars > 0 and total_earned == 0:
            total_earned = gifts_stars

        top_donors = sorted(donors_map.values(), key=lambda x: x["total_stars"], reverse=True)[:20]
        me_obj = await client.get_me()

        payload = {
            "ok": True,
            "account_id": account_id,
            "account_name": getattr(me_obj, "first_name", "") or "",
            "account_username": getattr(me_obj, "username", "") or "",
            "balance": balance,
            "total_earned": total_earned,
            "earned_from_fans": earned_from_fans,
            "total_in": total_in,
            "total_out": total_out,
            "topped_up": topped_up,
            "earned_today": earned_today,
            "earned_7d": earned_7d,
            "earned_30d": earned_30d,
            "gifts_count": gifts_count,
            "gifts_stars": gifts_stars,
            "gifts_convert_stars": gifts_convert_stars,
            "estimated_usd": round(total_earned * 0.013, 2),
            "estimated_eur": round(total_earned * 0.012, 2),
            "fan_value_eur": round(total_earned * 0.02, 2),
            "balance_usd": round(balance * 0.013, 2),
            "balance_eur": round(balance * 0.012, 2),
            "top_donors": top_donors,
            "transactions": transactions_formatted,
            "updated_at": now_ts
        }
        save_json(paths["stars"], payload)
        return payload
    except Exception as e:
        print(f"Erreur _direct_fetch_stars_for_account ({account_id}): {e}")
        return None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        for ext in ("", ".session", ".session-journal", ".session-wal", ".session-shm"):
            try:
                if os.path.exists(tmp_base + ext):
                    os.remove(tmp_base + ext)
            except Exception:
                pass


async def api_stars_handler(request):
    """Retourne les statistiques d'Étoiles Telegram (Stars) via l'API pour le compte actif et le cumul multi-comptes."""
    import asyncio
    token = request.query.get("token", "")
    if token != DASHBOARD_PASSWORD:
        return web.json_response({"error": "Unauthorized"}, status=401)

    acc_id = request.query.get("account", "default") or "default"
    refresh = request.query.get("refresh", "0") == "1"
    paths = get_account_paths(acc_id)

    if refresh:
        try:
            with open(paths["stars_flag"], "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except Exception:
            pass
        # Attendre jusqu'à 2.5s que le userbot consomme le flag
        for _ in range(10):
            await asyncio.sleep(0.25)
            if not os.path.exists(paths["stars_flag"]):
                break

        # Si le userbot n'a pas consommé le flag (ex: userbot non redémarré), fallback direct
        if os.path.exists(paths["stars_flag"]):
            try:
                os.remove(paths["stars_flag"])
            except Exception:
                pass
            await _direct_fetch_stars_for_account(acc_id)

    data = load_json(paths["stars"])
    if not isinstance(data, dict) or "balance" not in data:
        # Première lecture si le fichier n'existe pas encore
        direct_data = await _direct_fetch_stars_for_account(acc_id)
        if direct_data:
            data = direct_data
        else:
            data = {
                "ok": True,
                "account_id": acc_id,
                "balance": 0,
                "total_earned": 0,
                "earned_from_fans": 0,
                "total_in": 0,
                "total_out": 0,
                "topped_up": 0,
                "earned_today": 0,
                "earned_7d": 0,
                "earned_30d": 0,
                "gifts_count": 0,
                "gifts_stars": 0,
                "estimated_usd": 0,
                "estimated_eur": 0,
                "fan_value_eur": 0,
                "balance_usd": 0,
                "balance_eur": 0,
                "top_donors": [],
                "transactions": [],
                "updated_at": 0
            }

    # Calculer également le résumé cumulé de tous les comptes
    accs = load_accounts()
    all_balance = 0
    all_earned = 0
    all_today = 0
    accounts_breakdown = []
    for a in accs:
        aid = a["id"]
        apaths = get_account_paths(aid)
        sdata = data if aid == acc_id else load_json(apaths["stars"])
        if not isinstance(sdata, dict):
            sdata = {}
        b = sdata.get("balance", 0) or 0
        e = sdata.get("total_earned", 0) or 0
        td = sdata.get("earned_today", 0) or 0
        all_balance += b
        all_earned += e
        all_today += td
        accounts_breakdown.append({
            "id": aid,
            "name": a.get("name", aid),
            "balance": b,
            "total_earned": e,
            "earned_today": td
        })

    data["all_accounts"] = {
        "balance": all_balance,
        "total_earned": all_earned,
        "earned_today": all_today,
        "estimated_eur": round(all_earned * 0.012, 2),
        "fan_value_eur": round(all_earned * 0.02, 2),
        "breakdown": accounts_breakdown
    }
    return web.json_response(data)


def make_app():
    # 100 Mo max pour supporter l'envoi de photos et vidéos sans erreur 413
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app.router.add_static("/media", MEDIA_DIR)
    app.router.add_static("/vault", VAULT_DIR)
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/fans", api_fans_handler)
    app.router.add_get("/api/stars", api_stars_handler)
    app.router.add_get("/api/chat/{user_id}", api_chat_handler)
    app.router.add_post("/api/status", api_status_handler)
    app.router.add_get("/api/tags", api_tags_handler)
    app.router.add_post("/api/tags/create", api_create_tag_handler)
    app.router.add_post("/api/tags/delete", api_delete_tag_handler)
    app.router.add_post("/api/profile", api_profile_handler)
    app.router.add_post("/api/send", api_send_handler)
    app.router.add_post("/api/send-media", api_send_media_handler)
    app.router.add_post("/api/mark-read", api_mark_read_handler)
    app.router.add_post("/api/chat/delete", api_delete_chat_handler)
    app.router.add_post("/api/fans/bulk", api_bulk_action_handler)
    app.router.add_get("/api/backups", api_backups_list_handler)
    app.router.add_post("/api/backups/restore", api_backups_restore_handler)
    app.router.add_get("/api/accounts", api_accounts_list_handler)
    app.router.add_post("/api/accounts/create", api_accounts_create_handler)
    app.router.add_post("/api/accounts/delete", api_accounts_delete_handler)
    app.router.add_post("/api/accounts/connect", api_accounts_connect_handler)
    app.router.add_post("/api/accounts/verify", api_accounts_verify_handler)
    app.router.add_post("/api/suggest", api_suggest_handler)
    app.router.add_get("/api/payment-links", api_payment_links_handler)
    app.router.add_post("/api/payment-links", api_save_payment_links_handler)
    app.router.add_get("/api/scripts", api_scripts_handler)
    app.router.add_post("/api/scripts", api_save_scripts_handler)
    app.router.add_get("/api/vault", api_vault_handler)
    app.router.add_post("/api/vault/upload", api_vault_upload_handler)
    app.router.add_post("/api/vault/delete", api_vault_delete_handler)
    app.router.add_post("/api/vault/send", api_vault_send_handler)
    app.router.add_get("/api/rates-rules", api_rates_rules_get_handler)
    app.router.add_post("/api/rates-rules", api_rates_rules_save_handler)
    return app

if __name__ == "__main__":
    app = make_app()
    print(f"Miwa Dashboard sur http://0.0.0.0:{PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT)
