import logging
import asyncio
import aiohttp
import re
import os
import json
from typing import Dict, List
import config
from persona import get_system_prompt

logger = logging.getLogger(__name__)

# URL de base OpenRouter (compatible API OpenAI)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Modèles prioritaires OpenRouter (ultra-rapides, haute fluidité en français, sans quotas)
MODELS_TO_TRY = [
    "google/gemini-2.5-flash",                   # Priorité 1 : Français natif, naturel, vif, comprend l'humour
    "qwen/qwen-2.5-72b-instruct",                # Priorité 2 : Modèle géant très intelligent
    "meta-llama/llama-3.1-8b-instruct",          # Fallback
    "minimax/minimax-m3:free",                   # Excellent fallback
    "openrouter/free",                           # Dernier recours
]



# Modèles supportant la vision (analyse d'images ultra-précise avec crédits OpenRouter)
VISION_MODELS = [
    "google/gemini-3.1-flash-lite-image",       # Priorité 1 : Google officiel, ultra-précis, rapide
    "google/gemini-3.1-flash-image",            # Priorité 2 : Haute résolution
    "mistralai/mistral-small-2603",             # Priorité 3 : Vision Mistral
    "openrouter/free",                          # Fallback
]

# Préfixes qui trahissent du raisonnement interne en anglais
REASONING_PREFIXES = (
    "okay,", "okay let", "ok,", "ok let",
    "first,", "first i", "let me", "i need to",
    "i should", "i must", "the user", "according to",
    "based on", "thinking:", "my response", "i'll respond",
    "i will respond", "since they", "so my",
)


def _strip_reasoning(text: str) -> str:
    """
    Supprime le raisonnement interne que certains modèles incluent dans leur réponse.
    - Supprime les balises <think>...</think>
    - Si la réponse commence par du raisonnement en anglais, extrait le dernier paragraphe (la vraie réponse)
    """
    if not text:
        return text

    # 1. Supprimer les balises <think>...</think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    # 2. Détecter si ça commence par du raisonnement anglais
    text_lower = text.lower().lstrip()
    is_reasoning = any(text_lower.startswith(prefix) for prefix in REASONING_PREFIXES)

    if is_reasoning:
        # Prendre le dernier paragraphe non-vide (la vraie réponse est à la fin)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        for paragraph in reversed(paragraphs):
            p_lower = paragraph.lower()
            if not any(p_lower.startswith(prefix) for prefix in REASONING_PREFIXES):
                return paragraph
        # Fallback : dernière ligne non vide
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            return lines[-1]

    # 3. Supprimer tout jeu de rôle entre astérisques (*sourit*, *elle appuie sur send*, etc.)
    text = re.sub(r"\*.*?\*", "", text, flags=re.DOTALL).strip()

    # 4. Supprimer les guillemets englobants si présents
    text = text.strip('"\'').strip()

    # 5. Nettoyer les balises résiduelles éventuelles
    text = re.sub(r"\[ACTION:\s*LIKE\]", "", text, flags=re.IGNORECASE).strip()

    # 6. Nettoyer les sauts de ligne multiples résiduels
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text



HISTORIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversation_histories.json")


class MiwaGeminiClient:
    """Client IA Miwa — utilise OpenRouter (gratuit, sans quota, avec persistance disque)."""

    def __init__(self, history_file: str = None):
        self.api_key = config.OPENROUTER_API_KEY
        self.system_prompt = get_system_prompt()
        self.history_file = history_file or HISTORIES_FILE
        self.histories: Dict[str, List[dict]] = self._load_histories()

    def _load_histories(self) -> Dict[str, List[dict]]:
        h_file = getattr(self, "history_file", HISTORIES_FILE)
        if os.path.exists(h_file):
            try:
                with open(h_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_histories(self):
        h_file = getattr(self, "history_file", HISTORIES_FILE)
        try:
            tmp_file = h_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.histories, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, h_file)
        except Exception as e:
            logger.error(f"Erreur sauvegarde histories: {e}")


    def clear_history(self, user_id: int):
        uid = str(user_id)
        if uid in self.histories:
            self.histories[uid] = []
            self._save_histories()

    def _get_history(self, user_id: int) -> List[dict]:
        self.histories = self._load_histories()
        uid = str(user_id)
        if uid not in self.histories:
            self.histories[uid] = []
        return self.histories[uid]

    def add_message(self, user_id, role: str, content: str, **kwargs):
        import time
        self.histories = self._load_histories()
        uid = str(user_id)
        if uid not in self.histories:
            self.histories[uid] = []
        msg_dict = {
            "role": role,
            "content": content,
            "timestamp": kwargs.get("timestamp") or time.time(),
        }
        for k, v in kwargs.items():
            if v is not None and k not in msg_dict:
                msg_dict[k] = v
        self.histories[uid].append(msg_dict)
        self._save_histories()
        return msg_dict

    async def generate_reply(self, user_id: int, user_message: str, image_b64: str = None, extra_instruction: str = None) -> str:
        """Génère une réponse dans le personnage de Miwa via OpenRouter (avec support optionnel des images et instructions contextuelles)."""
        uid = str(user_id)
        history = self._get_history(user_id)

        # Préparation du contenu du message utilisateur
        if image_b64:
            text_prompt = user_message.strip() if user_message and user_message.strip() else "Je t'envoie cette photo ! Qu'en penses-tu ?"
            current_user_content = [
                {"type": "text", "text": text_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
            ]
            # Dans l'historique texte, on note qu'une photo a été partagée
            history_text = f"[Photo envoyée] {user_message}" if user_message else "[Photo envoyée]"
            history.append({"role": "user", "content": history_text})
        else:
            current_user_content = user_message
            history.append({"role": "user", "content": user_message})

        if len(history) > config.MAX_HISTORY_LENGTH * 2:
            history = history[-(config.MAX_HISTORY_LENGTH * 2):]
            self.histories[uid] = history

        self._save_histories()

        current_system_prompt = get_system_prompt()
        system_content = current_system_prompt
        if extra_instruction:
            system_content = f"{current_system_prompt}\n\n{extra_instruction}"

        # Si une image est fournie, on remplace le dernier message par le format multimodal
        messages = [{"role": "system", "content": system_content}] + history[:-1]
        messages.append({"role": "user", "content": current_user_content})



        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/miwa-bot",
            "X-Title": "Miwa Bot",
        }

        reply_text = None
        last_error = None

        candidate_models = VISION_MODELS if image_b64 else MODELS_TO_TRY
        seen = set()
        models_deduped = []
        for m in candidate_models:
            if m and m not in seen:
                seen.add(m)
                models_deduped.append(m)


        for model_name in models_deduped:
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.85,
                "max_tokens": 65,
                "reasoning": {"effort": "none"},  # Désactiver le thinking si supporté
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        OPENROUTER_URL,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            choices = data.get("choices", [])
                            if choices:
                                raw = choices[0].get("message", {}).get("content", "").strip()
                                reply_text = _strip_reasoning(raw)
                            if reply_text:
                                logger.info(f"Réponse obtenue via {model_name}")
                                break
                        elif resp.status in (429, 503, 502):
                            logger.info(f"Modèle {model_name} indisponible (HTTP {resp.status}), passage au suivant...")
                            continue
                        else:
                            err_body = await resp.text()
                            last_error = f"HTTP {resp.status}: {err_body}"
                            logger.warning(f"Erreur OpenRouter ({model_name}): {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Erreur réseau OpenRouter ({model_name}): {e}")

            if reply_text:
                break

        if reply_text:
            history.append({"role": "assistant", "content": reply_text})
            self._save_histories()
            return reply_text


        logger.error(f"Échec définitif de génération OpenRouter : {last_error}")
        return (
            "Désolée... 🥺 Le réseau a sauté une seconde dans la grange avec le mauvais temps. "
            "Tu peux me renvoyer ton petit message s'il te plaît ? 🌾🤍"
        )

    async def suggest_reply(self, user_id: int, last_messages: list, fan_profile: dict = None) -> str:
        """
        Génère une proposition de réponse SMS courte basée UNIQUEMENT
        sur le dernier message envoyé par le fan.
        """
        import persona
        time_ctx = persona.get_time_context()

        # Trouver le DERNIER message du fan (role=user) uniquement
        last_fan_msg = ""
        for m in reversed(last_messages or []):
            if m.get("role") == "user":
                last_fan_msg = m.get("content", "").strip()
                break

        if not last_fan_msg:
            return "Coucou ! Comment tu vas ?"

        prof_desc = ""
        if fan_profile:
            items = [f"{k}: {v}" for k, v in fan_profile.items() if v]
            if items:
                prof_desc = "Fan : " + ", ".join(items) + "."

        system_prompt = f"""Tu es une jeune femme chaleureuse, séduisante et complice de 23 ans qui répond par texto à un admirateur. {time_ctx}
{prof_desc}
L'opérateur humain a besoin d'UNE suggestion de réponse courte et pertinente.

RÈGLES CAPITALES :
- Ne parle JAMAIS de toi-même, de ta vie ou de ta journée, sauf si le fan t'a posé une question explicite sur toi.
- Réagis UNIQUEMENT et DIRECTEMENT à ce que le fan vient de dire (rebondis sur son propos).
- Style texto : court, naturel, joueur ou mignon (max 10 à 15 mots).
- Pas de grands monologues, pas d'explications.
- Réponds UNIQUEMENT le texte exact du texto à envoyer.

RÈGLE ABSOLUE — TU NE PARS JAMAIS, TU NE DORS JAMAIS :
- INTERDICTION TOTALE de dire que tu vas dormir, te coucher, partir ou t'arrêter de parler.
- INTERDICTION de dire : "je vais me coucher", "bonne nuit de mon côté", "je file dormir", "il est tard pour moi", "je vais y aller".
- Si le FAN dit qu'il va dormir → tu lui souhaites juste bonne nuit chaleureusement (ex: "Bonne nuit 🌙 dors bien !") et tu RESTES disponible.
- Si le fan continue à parler après avoir dit qu'il allait dormir → tu réponds normalement, PEU IMPORTE L'HEURE."""

        headers = {
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://telegram.org",
            "X-Title": "Miwa Suggest",
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Dernier message du fan : \"{last_fan_msg}\"\n\nSuggestion de réponse :"}
        ]

        payload = {
            "model": "google/gemini-2.5-flash",
            "messages": messages,
            "temperature": 0.75,
            "max_tokens": 35,
        }

        async with aiohttp.ClientSession() as session:
            for model_name in ["google/gemini-2.5-flash", "qwen/qwen-2.5-72b-instruct", "openrouter/free"]:
                payload["model"] = model_name
                try:
                    async with session.post(OPENROUTER_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            choices = data.get("choices", [])
                            if choices:
                                text = choices[0].get("message", {}).get("content", "").strip()
                                text = _strip_reasoning(text)
                                text = text.strip('"\'')
                                if text:
                                    return text
                except Exception as e:
                    logger.warning(f"Erreur suggestion IA ({model_name}): {e}")
                    continue

        return "Haha trop mignon 😄"

    async def detect_and_translate(self, text: str) -> dict:
        """
        Détecte la langue du message reçu.
        Si la langue n'est pas le français, le traduit en français.
        Retourne: {"lang": "en", "translated": "...", "is_foreign": True/False}
        """
        if not text or len(text.strip()) < 2:
            return {"lang": "fr", "translated": text, "is_foreign": False}

        headers = {
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://telegram.org",
            "X-Title": "Miwa Translator",
        }

        system_prompt = """Tu es un traducteur expert instantané pour une messagerie.
1. Détecte la langue du message reçu.
2. Si le message est déjà en FRANÇAIS (ou argot/texto/SMS français), réponds:
{"lang": "fr", "translated": ""}
3. Si le message est dans UNE AUTRE LANGUE (anglais, espagnol, arabe, russe, etc.), traduis-le fidèlement en français naturel:
{"lang": "<code_iso_2_lettres>", "translated": "<traduction_en_francais>"}

Réponds UNIQUEMENT le JSON strict valide, sans markdown, sans explications.
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]

        payload = {
            "model": "google/gemini-2.5-flash",
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 150,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(OPENROUTER_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            raw = choices[0].get("message", {}).get("content", "").strip()
                            raw = _strip_reasoning(raw)
                            raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
                            res = json.loads(raw)
                            lang = res.get("lang", "fr").lower().strip()
                            trans = res.get("translated", "").strip()
                            if lang != "fr" and trans:
                                return {"lang": lang, "translated": trans, "is_foreign": True}
        except Exception as e:
            logger.warning(f"Erreur detect_and_translate: {e}")

        return {"lang": "fr", "translated": text, "is_foreign": False}

    async def translate_to_language(self, text: str, target_lang: str) -> str:
        """Traduit un message français rédigé par l'opérateur vers la langue du fan (ex: en)."""
        if not text or not target_lang or target_lang.lower() == "fr":
            return text

        headers = {
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://telegram.org",
            "X-Title": "Miwa Translator Outgoing",
        }

        system_prompt = f"""Tu es un traducteur de SMS expert.
Traduis ce message français vers la langue cible : '{target_lang}'.
Règles :
- Style texto/SMS naturel et direct.
- Conserve les emojis et la ponctuation.
- Réponds UNIQUEMENT le texte traduit exact, sans guillemets, sans explications.
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]

        payload = {
            "model": "google/gemini-2.5-flash",
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 150,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(OPENROUTER_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            raw = choices[0].get("message", {}).get("content", "").strip()
                            raw = _strip_reasoning(raw)
                            raw = raw.strip('"\'')
                            if raw:
                                return raw
        except Exception as e:
            logger.warning(f"Erreur translate_to_language ({target_lang}): {e}")

        return text

# Instance partagée pour le bot et le dashboard
gemini_client = MiwaGeminiClient()


