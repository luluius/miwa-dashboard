#!/usr/bin/env python3
"""
Script de sauvegarde horaire automatique pour Miwa Dashboard.
Sauvegarde tous les comptes (principal et secondaires) chaque heure dans backups/hourly/
"""
import os
import shutil
import time
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "backups", "hourly")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")
MAX_BACKUP_DAYS = 7

os.makedirs(BACKUP_DIR, exist_ok=True)

def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [{"id": "default", "name": "Compte Principal"}]

def perform_backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    accounts = load_accounts()
    saved_files = 0

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 💾 Début de la sauvegarde horaire...")

    for acc in accounts:
        aid = acc.get("id", "default")
        suffix = "" if aid == "default" else f"_{aid}"
        
        files_to_backup = [
            f"chat_states{suffix}.json",
            f"conversation_histories{suffix}.json",
            f"user_presence{suffix}.json",
            f"message_queue{suffix}.json"
        ]

        for fname in files_to_backup:
            src = os.path.join(BASE_DIR, fname)
            if os.path.exists(src) and os.path.getsize(src) > 2:
                dst = os.path.join(BACKUP_DIR, f"{fname.replace('.json', '')}_{ts}.json")
                try:
                    shutil.copy2(src, dst)
                    saved_files += 1
                except Exception as e:
                    print(f"❌ Erreur copie {fname}: {e}")

    # Sauvegarder aussi la liste des étiquettes et configurations
    global_files = [
        "custom_tags.json",
        "fan_tags_registry.json",
        "payment_links.json",
        "scripts.json",
        "rates_rules.json",
        "accounts.json"
    ]
    for gf in global_files:
        src = os.path.join(BASE_DIR, gf)
        if os.path.exists(src) and os.path.getsize(src) > 2:
            dst = os.path.join(BACKUP_DIR, f"{gf.replace('.json', '')}_{ts}.json")
            try:
                shutil.copy2(src, dst)
                saved_files += 1
            except Exception as e:
                print(f"❌ Erreur copie {gf}: {e}")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Sauvegarde terminée ({saved_files} fichiers archivés).")

    # Nettoyage des vieilles sauvegardes (> MAX_BACKUP_DAYS)
    cleanup_old_backups()

def cleanup_old_backups():
    now = time.time()
    cutoff = now - (MAX_BACKUP_DAYS * 86400)
    try:
        for f in os.listdir(BACKUP_DIR):
            fp = os.path.join(BACKUP_DIR, f)
            if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                os.remove(fp)
    except Exception as e:
        print(f"⚠️ Erreur nettoyage anciens backups: {e}")

if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        perform_backup()
    else:
        print("🕒 Service de backup horaire démarré (sauvegarde toutes les 3600 secondes).")
        while True:
            try:
                perform_backup()
            except Exception as e:
                print(f"❌ Erreur critique backup: {e}")
            time.sleep(3600)
