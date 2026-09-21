"""
Miwa Control Center - Serveur Aiohttp avec support d'édition de statuts et profil.
"""

import os
import json
import time
import re
from aiohttp import web

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "miwa2026")
PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")
HTML_FILE = os.path.join(BASE_DIR, "dashboard.html")
PAYMENT_LINKS_FILE = os.path.join(BASE_DIR, "payment_links.json")
SCRIPTS_FILE = os.path.join(BASE_DIR, "scripts.json")
VAULT_FILE = os.path.join(BASE_DIR, "vault_media.json")
TAGS_FILE = os.path.join(BASE_DIR, "custom_tags.json")
RATES_RULES_FILE = os.path.join(BASE_DIR, "rates_rules.json")
MEDIA_DIR = os.path.join(BASE_DIR, "media")
VAULT_DIR = os.path.join(BASE_DIR, "vault")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

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
        }
    return {
        "states": os.path.join(BASE_DIR, f"chat_states_{aid}.json"),
        "histories": os.path.join(BASE_DIR, f"conversation_histories_{aid}.json"),
        "queue": os.path.join(BASE_DIR, f"message_queue_{aid}.json"),
        "presence": os.path.join(BASE_DIR, f"user_presence_{aid}.json"),
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

def get_fan_status(state, user_id: str, tags_dict: dict):
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
    fans = []
    stats = {"total_fans": len(chat_states), "unread": 0, "followup": 0, "total_revenue": 0}
    for t in tags_list:
        stats[t["id"]] = 0

    for uid, state in chat_states.items():
        # Extraire le dernier message pour la prévisualisation dans la barre latérale
        user_history = histories.get(str(uid), [])
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

        sc, sl, bs, dot, is_manual = get_fan_status(state, uid, tags_dict)
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
            "is_unread": is_unread
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

    import gemini_client
    actual_telegram_message = message
    sent_content = None

    if target_lang and target_lang != "fr":
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
        save_json(STATES_FILE, chat_states)
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
        save_json(paths["states"], chat_states)

    queue = load_json(paths["queue"])
    if not isinstance(queue, list):
        queue = []
    queue.append({
        "user_id": int(user_id),
        "message": caption,
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

def make_app():
    # 100 Mo max pour supporter l'envoi de photos et vidéos sans erreur 413
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app.router.add_static("/media", MEDIA_DIR)
    app.router.add_static("/vault", VAULT_DIR)
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/fans", api_fans_handler)
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
