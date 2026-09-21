"""
Script Userbot (Telethon) : Permet à Miwa de répondre directement depuis votre compte Telegram personnel.
Une fois connecté la première fois, la session est sauvegardée définitivement dans miwa_personal_session.session
et le code ne vous sera plus JAMAIS redemandé !
"""
import os
import sys
import random
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events, errors


from dotenv import load_dotenv
import config
from gemini_client import MiwaGeminiClient

load_dotenv()

log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "userbot.log")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)
logging.getLogger("telethon").setLevel(logging.WARNING)
logger = logging.getLogger("MiwaUserbot")


API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
PHONE = os.getenv("TELEGRAM_PHONE")

if not API_ID or not API_HASH:
    print("\n" + "=" * 60)
    print("❌ ERREUR : TELEGRAM_API_ID ou TELEGRAM_API_HASH manquant dans le fichier .env")
    print("=" * 60 + "\n")
    exit(1)

import json
import time

MY_USER_ID = None
PROCESSED_MESSAGES = set()

# --- GESTION MULTI-COMPTES ---
CURRENT_ACCOUNT = "default"
for arg in sys.argv[1:]:
    if arg.startswith("--account="):
        CURRENT_ACCOUNT = arg.split("=", 1)[1].strip() or "default"
    elif not arg.startswith("-"):
        CURRENT_ACCOUNT = arg.strip() or "default"

print(f"🤖 Démarrage Userbot pour le compte : [{CURRENT_ACCOUNT}]")

def get_account_filename(base_name):
    if CURRENT_ACCOUNT == "default" or not CURRENT_ACCOUNT:
        return base_name
    name, ext = os.path.splitext(base_name)
    return f"{name}_{CURRENT_ACCOUNT}{ext}"

hist_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), get_account_filename("conversation_histories.json"))
gemini_client = MiwaGeminiClient(history_file=hist_file)

STATES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), get_account_filename("chat_states.json"))
USER_PRESENCE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), get_account_filename("user_presence.json"))
QUEUE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), get_account_filename("message_queue.json"))

CHAT_STATES = {}

def load_chat_states():
    global CHAT_STATES
    if os.path.exists(STATES_FILE):
        try:
            with open(STATES_FILE, "r", encoding="utf-8") as f:
                CHAT_STATES = json.load(f)
        except Exception:
            CHAT_STATES = {}

def save_chat_states():
    try:
        tmp_file = STATES_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(CHAT_STATES, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, STATES_FILE)
    except Exception as e:
        logger.error(f"Erreur sauvegarde chat_states: {e}")

# USER_PRESENCE_FILE dynamique
MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

def load_presence():
    if os.path.exists(USER_PRESENCE_FILE):
        try:
            with open(USER_PRESENCE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_presence(data):
    try:
        tmp_file = USER_PRESENCE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_file, USER_PRESENCE_FILE)
    except Exception:
        pass


def update_chat_state(user_id: int, updates: dict):
    load_chat_states()
    uid_str = str(user_id)
    if uid_str not in CHAT_STATES:
        CHAT_STATES[uid_str] = {}
    CHAT_STATES[uid_str].update(updates)
    save_chat_states()

def get_fan_profile(user_id: int) -> dict:
    load_chat_states()
    uid_str = str(user_id)
    return CHAT_STATES.get(uid_str, {}).get("fan_profile", {})

def update_fan_profile(user_id: int, new_info: dict):
    load_chat_states()
    uid_str = str(user_id)
    if uid_str not in CHAT_STATES:
        CHAT_STATES[uid_str] = {}
    if "fan_profile" not in CHAT_STATES[uid_str]:
        CHAT_STATES[uid_str]["fan_profile"] = {}
    CHAT_STATES[uid_str]["fan_profile"].update(new_info)
    save_chat_states()

def format_fan_profile_prompt(profile: dict) -> str:
    if not profile:
        return ""
    lines = ["📋 FICHE MÉMOIRE DE CE FAN (INFORMATIONS RETENUES À VIE) :"]
    for k, v in profile.items():
        if v:
            lines.append(f"- {k.capitalize()} : {v}")
    lines.append("RÈGLE STRICTE : Tu connais déjà ces informations par cœur ! Ne lui redemande JAMAIS ce que tu sais déjà (ex: ne redemande jamais son prénom, son âge ou sa ville).")
    return "\n".join(lines)

def extract_direct_facts(user_text: str) -> dict:
    facts = {}
    if not user_text:
        return facts
    import re

    # Mots interdits comme valeur de profil (faux positifs courants)
    FALSE_POSITIVE_WORDS = {
        'sortir', 'seul', 'seule', 'bien', 'mal', 'ici', 'la', 'là',
        'en', 'au', 'aux', 'du', 'de', 'par', 'sur', 'sous', 'avec',
        'chez', 'pour', 'dans', 'après', 'avant', 'aussi', 'très',
        'pas', 'plus', 'peu', 'trop', 'tout', 'rien', 'non', 'oui',
        'une', 'un', 'le', 'les', 'des', 'mon', 'ma', 'mes', 'son',
        'sa', 'ses', 'ce', 'cet', 'cette', 'ces', 'monde', 'france',
        'fatigué', 'fatiguée', 'heureux', 'heureuse', 'triste',
        'occupé', 'occupée', 'libre', 'disponible',
    }

    # Prénom
    m = re.search(r"(?:je m'appelle|moi c'est|mon prénom c'est)\s+([A-Za-zÀ-ÿ\-]+)", user_text, re.I)
    if m:
        facts['prenom'] = m.group(1).capitalize()

    # Âge
    m = re.search(r"\b(?:j'ai|jai)\s+(\d{1,2})\s*ans\b", user_text, re.I)
    if m:
        facts['age'] = f'{m.group(1)} ans'

    # Ville — avec validation stricte (longueur min 3, pas de faux positif)
    m = re.search(r"\b(?:j'habite|jhabite|je vis|je viens de|je suis de|j'?habite à|je suis à)\s+(?:à\s+|a\s+)?([A-Za-zÀ-ÿ\-]{3,})", user_text, re.I)
    if m:
        city = m.group(1).strip().capitalize()
        if (
            len(city) >= 3
            and city.lower() not in FALSE_POSITIVE_WORDS
            and not re.match(r'^(être|avoir|aller|faire|voir|savoir|vouloir|pouvoir)', city, re.I)
        ):
            facts['ville'] = city

    return facts


load_chat_states()

BUSY_KEYWORDS = [
    "vais manger", "va manger", "partir manger", "go manger",
    "dois y aller", "dois partir", "je pars", "je bouge", "je file",
    "vais bosser", "vais travailler", "au boulot", "au travail",
    "reviens tout à l'heure", "reviens dans", "a toute", "à toute",
    "a plus", "à plus", "bonne soirée", "bonne soiree", "bonne nuit",
    "a demain", "à demain", "suis occupé", "je suis occupé",
    "un truc à faire", "te laisse", "je te laisse", "occupe", "occupé"
]

INACTIVITY_DELAY = int(os.getenv("INACTIVITY_DELAY", 1800))  # 30 minutes (1800 secondes)

def is_night_time() -> bool:
    """Retourne True si Miwa dort (entre 00h30 et 05h30 du matin, heure de Paris)."""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/Paris"))
    if now.hour == 0 and now.minute >= 30:
        return True
    if 1 <= now.hour < 5:
        return True
    if now.hour == 5 and now.minute < 30:
        return True
    return False

async def react_to_message(client, event, emoji="❤️"):

    """Pose une réaction émoji (ex: ❤️) sur un message Telegram."""
    try:
        from telethon.tl.functions.messages import SendReactionRequest
        from telethon.tl.types import ReactionEmoji
        peer = await event.get_input_chat()
        await client(SendReactionRequest(peer=peer, msg_id=event.id, reaction=[ReactionEmoji(emoticon=emoji)]))
        return True
    except Exception as e:
        logger.warning(f"Impossible de poser la réaction {emoji}: {e}")
        return False

async def inactivity_checker(client):
    """Vérifie toutes les 45s si un fan n'a pas répondu depuis 30 min sans avoir dit au revoir/occupé."""
    logger.info("⏱️ Surveillance d'inactivité active (relance douce après 30 min de silence)")
    while True:
        try:
            await asyncio.sleep(45)
            now = time.time()
            for uid_str, state in list(CHAT_STATES.items()):
                # On ne relance QUE SI :
                # 1. Le dernier message venait de Miwa
                # 2. Aucune relance n'a déjà été faite
                # 3. La conversation n'est pas en pause (pas de au revoir, pas de "je vais manger", pas de like)
                if (
                    state.get("last_message_from") == "miwa"
                    and not state.get("relance_sent", False)
                    and not state.get("conversation_paused", False)
                ):
                    last_time = state.get("last_message_time", now)
                    if (now - last_time) >= INACTIVITY_DELAY:
                        state["relance_sent"] = True
                        save_chat_states()

                        user_id = int(uid_str)
                        chat_id = state.get("chat_id", user_id)
                        sender_name = state.get("sender_name", "le fan")

                        logger.info(f"⏰ [Inactivité 30min] {sender_name} n'a pas répondu depuis 30 min. Génération relance...")

                        prompt = (
                            "[Action système : Le fan n'a pas répondu à ton dernier message depuis plus de 30 minutes "
                            "sans avoir dit qu'il était occupé ou au revoir. Envoie-lui un tout petit mot très doux et naturel "
                            "(1 seule phrase courte) pour demander gentiment s'il va bien ou s'il préfère papoter plus tard, sans forcer.]"
                        )
                        try:
                            followup = await gemini_client.generate_reply(user_id, prompt)
                            if not followup or "[ACTION:LIKE]" in followup:
                                followup = "Coucou ! Tout va bien ? Dis-moi si tu as été pris par quelque chose ou si tu préfères qu'on papote plus tard 🌸"
                        except Exception:
                            followup = "Coucou ! Tout va bien ? Dis-moi si tu as été pris par quelque chose ou si tu préfères qu'on papote plus tard 🌸"

                        async with client.action(chat_id, 'typing'):
                            await asyncio.sleep(random.uniform(2.5, 4.5))

                        await client.send_message(chat_id, followup)
                        logger.info(f"📤 [Relance 30min] Envoyée à {sender_name}: {followup}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Erreur dans inactivity_checker: {e}")
            await asyncio.sleep(10)


# QUEUE_FILE dynamique

async def queue_processor(client):
    """Envoie les messages mis en queue depuis le dashboard toutes les secondes."""
    logger.info("📬 Queue processor démarré (messages dashboard)")
    while True:
        try:
            await asyncio.sleep(1)
            if not os.path.exists(QUEUE_FILE):
                continue
            try:
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    queue = json.load(f)
            except Exception:
                continue
            if not isinstance(queue, list) or not queue:
                continue

            # IMPORTANT : Vider la queue IMMEDIATEMENT avant tout traitement
            # pour éviter les envois doubles/triples si la boucle se réexécute
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)

            remaining = []
            for item in queue:
                user_id = item.get("user_id")
                message = item.get("message", "").strip()
                media_path = item.get("media_path")
                attempts = item.get("attempts", 0)
                if not user_id or (not message and not media_path):
                    continue
                try:
                    uid_int = int(user_id)
                    try:
                        entity = await client.get_input_entity(uid_int)
                    except Exception:
                        entity = uid_int

                    # Simulation de frappe (courte pour réactivité)
                    async with client.action(entity, 'typing'):
                        await asyncio.sleep(random.uniform(0.5, 1.2))

                    if media_path and os.path.exists(media_path):
                        logger.info(f"📤 [Telethon] Envoi média {media_path} à {user_id}")
                        sent_msg = await client.send_file(entity, media_path, caption=message or None)
                    else:
                        sent_msg = await client.send_message(entity, message)
                    msg_id = getattr(sent_msg, "id", None)

                    # Mettre à jour l'état du chat
                    uid_str = str(user_id)
                    load_chat_states()
                    if uid_str in CHAT_STATES:
                        CHAT_STATES[uid_str]["last_message_from"] = "miwa"
                        CHAT_STATES[uid_str]["last_message_time"] = time.time()
                        CHAT_STATES[uid_str]["relance_sent"] = False
                        save_chat_states()

                    # Mettre à jour msg_id dans l'historique
                    import gemini_client as gc
                    gc.gemini_client.histories = gc.gemini_client._load_histories()
                    user_hist = gc.gemini_client.histories.get(uid_str, [])
                    if user_hist and user_hist[-1].get("role") == "assistant":
                        user_hist[-1]["msg_id"] = msg_id
                        gc.gemini_client._save_histories()

                    logger.info(f"📤 [Dashboard] Message envoyé à {uid_str} (ID msg: {msg_id}): {message[:60]}")
                except Exception as e:
                    logger.error(f"Erreur envoi queue message à {user_id}: {e}")

            # Remettre les messages en échec seulement
            if remaining:
                with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                    json.dump(remaining, f, ensure_ascii=False)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Erreur dans queue_processor: {e}")
            await asyncio.sleep(2)


def mark_history_read_up_to(uid_str: str, max_id: int = 0):
    """Marque les messages envoyés par Miwa comme lus (read = True) jusqu'à max_id."""
    try:
        import gemini_client as gc
        hist = gc.gemini_client._get_history(uid_str)
        updated = False
        for m in hist:
            if m.get("role") == "assistant" and not m.get("read"):
                mid = m.get("msg_id")
                if max_id and mid and mid <= max_id:
                    m["read"] = True
                    updated = True
                elif not max_id or not mid:
                    m["read"] = True
                    updated = True
        if updated:
            gc.gemini_client._save_histories()
            logger.info(f"✓✓ Accusé de lecture synchronisé pour {uid_str} (max_id: {max_id})")
    except Exception as e:
        logger.error(f"Erreur mark_history_read_up_to: {e}")


async def read_sync_processor(client):
    """
    Synchronise activement les accusés de lecture (✓✓) toutes les 3 secondes
    en interrogeant l'état des dialogues Telegram (dialog.dialog.read_outbox_max_id).
    Garantit que même si le fan lit sans répondre, le ✓✓ s'affiche immédiatement.
    """
    logger.info("👀 Synchroniseur actif d'accusés de lecture (✓✓) démarré")
    while True:
        try:
            await asyncio.sleep(3)
            import gemini_client as gc
            histories = gc.gemini_client._load_histories()
            
            # Ne vérifier que les contacts ayant des messages assistant non lus récents
            pending_uids = set()
            for uid, msgs in histories.items():
                if any(m.get("role") == "assistant" and not m.get("read") for m in msgs[-5:]):
                    pending_uids.add(str(uid))

            if not pending_uids:
                continue

            async for dialog in client.iter_dialogs(limit=25):
                d_uid = str(dialog.id)
                if d_uid in pending_uids:
                    read_max_id = getattr(getattr(dialog, "dialog", None), "read_outbox_max_id", 0)
                    if read_max_id > 0:
                        mark_history_read_up_to(d_uid, read_max_id)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"read_sync_processor loop: {e}")
            await asyncio.sleep(4)


async def on_private_message(event):
    """
    Mode Chatter Humain :
    Intercepte les messages privés reçus de Telegram,
    les enregistre dans l'historique et met à jour l'état des fans.
    L'IA automatique est DÉSACTIVÉE : ce sont les opérateurs humains
    qui répondent depuis le Dashboard Web (avec l'option de suggestion IA).
    """
    global MY_USER_ID, PROCESSED_MESSAGES

    # Ignorer les canaux, groupes et messages sortants
    if not event.is_private or event.out:
        return

    if MY_USER_ID and event.sender_id == MY_USER_ID:
        return
    if event.sender_id in (777000, 42777):
        return

    # Anti-doublon
    if event.id in PROCESSED_MESSAGES:
        return
    PROCESSED_MESSAGES.add(event.id)
    if len(PROCESSED_MESSAGES) > 2000:
        PROCESSED_MESSAGES.clear()

    sender = await event.get_sender()
    sender_name = getattr(sender, "first_name", "Fan")
    user_id = event.sender_id
    user_text = event.raw_text or ""

    logger.info(f"📩 [Message reçu] De {sender_name} (ID: {user_id}): {user_text}")

    try:
        # Traitement média (photo, document, vidéo, gif)
        photo_url = None
        is_voice = bool(getattr(event, "voice", False) or getattr(event, "audio", False))

        if event.media and not is_voice:
            try:
                ext = ".jpg"
                if event.video or getattr(event, "gif", False):
                    ext = ".mp4"
                elif getattr(event, "file", None) and getattr(event.file, "ext", None):
                    ext = event.file.ext or ".jpg"
                elif event.photo:
                    ext = ".jpg"

                fn = f"media_{user_id}_{int(time.time())}_{event.id}{ext}"
                fp = os.path.join(MEDIA_DIR, fn)
                await event.download_media(file=fp)
                photo_url = f"/media/{fn}"
                effective_message = user_text if user_text else ""
                logger.info(f"📸 Média reçu de {sender_name}: {photo_url}")
            except Exception as pe:
                logger.warning(f"Erreur téléchargement média: {pe}")
                effective_message = f"{user_text} [Média reçu]".strip()
        else:
            effective_message = user_text

        # Traitement vocal
        is_voice = bool(getattr(event, "voice", False) or getattr(event, "audio", False))
        if is_voice:
            try:
                voice_bytes = await event.download_media(bytes)
                if voice_bytes:
                    from audio_transcriber import transcribe_audio_bytes
                    loop = asyncio.get_running_loop()
                    voice_transcription = await loop.run_in_executor(None, transcribe_audio_bytes, voice_bytes)
                    effective_message = f"{effective_message} [Vocal]: {voice_transcription}".strip()
            except Exception as e:
                logger.warning(f"Erreur transcription vocal: {e}")
                effective_message = f"{effective_message} [Message vocal]".strip()

        # Détection langue et traduction désactivées — les messages restent dans leur langue d'origine
        lang = "fr"
        translated_fr = ""
        # if effective_message:
        #     try:
        #         trans_info = await gemini_client.detect_and_translate(effective_message)
        #         lang = trans_info.get("lang", "fr")
        #         translated_fr = trans_info.get("translated", "")
        #     except Exception as te:
        #         logger.warning(f"Erreur détection langue: {te}")

        uid_str = str(user_id)
        now_ts = time.time()
        final_content = effective_message  # pas de traduction
        original_content = None

        # Mettre à jour l'historique de conversation
        gemini_client.add_message(
            user_id,
            "user",
            final_content,
            original_content=original_content,
            lang=lang,
            photo_url=photo_url,
            timestamp=now_ts
        )

        # Mettre à jour la présence (en ligne)
        p = load_presence()
        if uid_str not in p:
            p[uid_str] = {}
        p[uid_str]["online"] = True
        p[uid_str]["last_seen"] = now_ts
        save_presence(p)

        # Si le fan répond, tous les messages précédents de Miwa ont été lus (read = True)
        hist = gemini_client._get_history(uid_str)
        read_updated = False
        for m in hist:
            if m.get("role") == "assistant" and not m.get("read"):
                m["read"] = True
                read_updated = True
        if read_updated:
            gemini_client._save_histories()

        # Compteur individuel & mémorisation de la langue
        user_state = CHAT_STATES.get(uid_str, {})
        message_count = user_state.get("message_count", 0) + 1

        update_state_dict = {
            "last_message_from": "fan",
            "last_message_time": now_ts,
            "chat_id": event.chat_id,
            "sender_name": sender_name,
            "message_count": message_count,
            "relance_sent": False,
            "is_read": False
        }
        if lang != "fr":
            update_state_dict["language"] = lang

        update_chat_state(user_id, update_state_dict)

        # Extraction faits de profil (ville, age, etc.)
        direct_facts = extract_direct_facts(effective_message)
        if direct_facts:
            update_fan_profile(user_id, direct_facts)
            logger.info(f"📝 [Fiche Fan {sender_name}] Infos détectées : {direct_facts}")

        logger.info(f"✅ Message de {sender_name} enregistré pour les chatters sur le Dashboard.")

    except Exception as e:
        logger.error(f"Erreur enregistrement message de {sender_name}: {e}")

async def on_message_read(event):
    """Déclenché quand le fan lit nos messages sortants sur Telegram."""
    try:
        if getattr(event, "inbox", False):
            return
        uid = getattr(event, "chat_id", None) or getattr(event, "user_id", None)
        if uid:
            max_id = getattr(event, "max_id", 0)
            mark_history_read_up_to(str(uid), max_id)
    except Exception as e:
        logger.error(f"Erreur on_message_read: {e}")

async def on_raw_update(event):
    """Intercepte les accusés de lecture bas niveau Telegram (UpdateReadHistoryOutbox)."""
    try:
        from telethon.tl.types import UpdateReadHistoryOutbox
        if isinstance(event, UpdateReadHistoryOutbox):
            peer = getattr(event, "peer", None)
            uid = getattr(peer, "user_id", None)
            if uid:
                mark_history_read_up_to(str(uid), getattr(event, "max_id", 0))
    except Exception as e:
        logger.debug(f"Erreur on_raw_update: {e}")

async def on_user_update(event):
    """Détecte qui est en ligne et qui est en train d'écrire sur Telegram."""
    try:
        uid = str(getattr(event, "user_id", "") or getattr(event, "chat_id", ""))
        if not uid:
            return
        p = load_presence()
        if uid not in p:
            p[uid] = {}

        now = time.time()
        if event.online is not None:
            p[uid]["online"] = bool(event.online)
            if event.online:
                p[uid]["last_seen"] = now

        is_typing = bool(event.typing or getattr(event, "uploading", False) or getattr(event, "recording", False))
        if is_typing:
            p[uid]["typing_until"] = now + 6.0
            p[uid]["online"] = True

        save_presence(p)
    except Exception as e:
        logger.debug(f"Erreur on_user_update: {e}")

async def main():
    # Définition du chemin absolu pour enregistrer le fichier de session
    sess_name = "miwa_personal_session" if CURRENT_ACCOUNT == "default" else f"miwa_personal_session_{CURRENT_ACCOUNT}"
    session_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), sess_name)
    
    # Création du client dans la boucle asynchrone courante (évite les conflits SQLite)
    client = TelegramClient(session_file, int(API_ID), API_HASH)
    
    print("🌾 Connexion aux serveurs Telegram en cours...")
    await client.connect()

    # Vérifie si le compte est déjà connecté (sauvegardé sur le disque)
    if not await client.is_user_authorized():
        print(f"\n📲 Première connexion requise pour {PHONE}")
        sent_code = await client.send_code_request(PHONE)
        print("✉️ Code envoyé ! Regardez dans vos messages officiels Telegram.")
        code = input("\n👉 Entrez le code reçu sur Telegram : ").strip()
        try:
            await client.sign_in(PHONE, code, phone_code_hash=sent_code.phone_code_hash)
        except errors.SessionPasswordNeededError:
            while True:
                pwd = input("🔒 Mot de passe 2FA (double authentification de votre compte Telegram) : ").strip()
                try:
                    await client.sign_in(password=pwd)
                    break
                except errors.PasswordHashInvalidError:
                    print("❌ Mot de passe 2FA incorrect. Veuillez réessayer :")
        print("💾 Session enregistrée définitivement !")

    # Enregistrement des gestionnaires d'événements
    client.add_event_handler(on_private_message, events.NewMessage(incoming=True))
    client.add_event_handler(on_message_read, events.MessageRead(inbox=False))
    client.add_event_handler(on_raw_update, events.Raw)
    client.add_event_handler(on_user_update, events.UserUpdate)

    global MY_USER_ID
    me = await client.get_me()
    MY_USER_ID = me.id
    print("\n" + "=" * 60)
    print(f"✅ Connecté avec succès au compte de : {me.first_name} (@{me.username or 'sans_pseudo'})")
    print("🌾 Miwa est active sur votre compte et répondra en direct à vos fans !")
    print("=" * 60 + "\n")

    # Mode Chatter Humain : Inactivité automatique désactivée
    # asyncio.create_task(inactivity_checker(client))

    # Démarrage du processeur de messages manuels envoyés par les chatters depuis le dashboard
    asyncio.create_task(queue_processor(client))
    # Démarrage du synchroniseur actif d'accusés de lecture (✓✓)
    asyncio.create_task(read_sync_processor(client))

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())

