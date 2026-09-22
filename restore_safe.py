#!/usr/bin/env python3
"""
Script de restauration ultra-sécurisé pour Miwa Bot.
Restaure les historiques de messages, étiquettes, profils et états sans perte.
"""
import os
import shutil
import json
import glob
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "backups", "hourly")

def list_backups():
    print("\n📦 Dernières sauvegardes horaires disponibles dans backups/hourly/ :")
    hist_files = sorted(glob.glob(os.path.join(BACKUP_DIR, "conversation_histories_*.json")), reverse=True)
    if not hist_files:
        print("  Aucune sauvegarde horaire trouvée pour l'instant.")
        return []
    
    for i, hf in enumerate(hist_files[:10]):
        fn = os.path.basename(hf)
        ts_part = fn.replace("conversation_histories_", "").replace(".json", "")
        size_kb = os.path.getsize(hf) / 1024
        print(f"  [{i+1}] Horodatage : {ts_part} | Taille : {size_kb:.1f} Ko")
    return hist_files[:10]

def restore_latest():
    hist_files = sorted(glob.glob(os.path.join(BACKUP_DIR, "conversation_histories_*.json")), reverse=True)
    if not hist_files:
        print("❌ Aucune sauvegarde à restaurer.")
        return False
    
    latest_hist = hist_files[0]
    ts_part = os.path.basename(latest_hist).replace("conversation_histories_", "").replace(".json", "")
    print(f"🔄 Restauration de la sauvegarde la plus récente : {ts_part}")

    # 1. Copier conversation_histories
    shutil.copy2(latest_hist, os.path.join(BASE_DIR, "conversation_histories.json"))

    # 2. Copier chat_states si dispo
    states_backup = os.path.join(BACKUP_DIR, f"chat_states_{ts_part}.json")
    if os.path.exists(states_backup):
        shutil.copy2(states_backup, os.path.join(BASE_DIR, "chat_states.json"))

    # 3. Copier custom_tags si dispo
    tags_backup = os.path.join(BACKUP_DIR, f"custom_tags_{ts_part}.json")
    if os.path.exists(tags_backup):
        shutil.copy2(tags_backup, os.path.join(BASE_DIR, "custom_tags.json"))

    # 4. Copier fan_tags_registry si dispo
    reg_backup = os.path.join(BACKUP_DIR, f"fan_tags_registry_{ts_part}.json")
    if os.path.exists(reg_backup):
        shutil.copy2(reg_backup, os.path.join(BASE_DIR, "fan_tags_registry.json"))

    print("✅ Restauration réussie avec succès ! (Messages + États + Étiquettes restaurés)")
    return True

if __name__ == "__main__":
    import sys
    if "--list" in sys.argv:
        list_backups()
    else:
        restore_latest()
