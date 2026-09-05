# 🖥️ MiwaDashboard — Application Windows

Fenêtre desktop native pour accéder au dashboard Miwa sans ouvrir un navigateur.

---

## 📁 Contenu du dossier

```
windows_app/
├── launcher.py          ← Code source de l'app
├── MiwaDashboard.spec   ← Config PyInstaller
├── version_info.txt     ← Infos de version Windows
├── icon.ico             ← Icône de l'app
├── build.bat            ← Script de compilation (à lancer sur Windows)
└── README.md            ← Ce fichier
```

---

## 🔨 Comment compiler le .exe (sur un PC Windows)

### Prérequis
- Windows 10 ou 11
- [Python 3.10+](https://www.python.org/downloads/) installé (**cocher "Add Python to PATH"** lors de l'installation)
- Connexion internet (pour télécharger les dépendances)

### Étapes

1. Copie tout le dossier `windows_app/` sur ton PC Windows
2. Double-clique sur **`build.bat`**
3. Attends 1-2 minutes (installation + compilation automatique)
4. Le fichier **`dist/MiwaDashboard.exe`** s'ouvre automatiquement dans l'explorateur

> Le script installe automatiquement : `pywebview` + `PyInstaller` dans un environnement isolé.

---

## ✅ Ce que fait l'application

- Ouvre le dashboard Miwa (`https://miwa230.duckdns.org`) dans une **fenêtre native Windows**
- Pas de barre d'adresse, pas d'onglets — comme une vraie app desktop
- Utilise **Edge WebView2** (déjà installé sur Windows 10/11)
- Icône Miwa dans la barre des tâches

---

## ⚠️ Important

- Le PC doit être **connecté à internet** pour utiliser l'app (le dashboard tourne sur le VPS)
- **Windows Defender** peut afficher un avertissement "application inconnue" la première fois → cliquer sur "Informations complémentaires" puis "Exécuter quand même"
- L'exe fait ~30-50 Mo (normal pour une app Python packagée)
