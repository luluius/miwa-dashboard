@echo off
title Build MiwaDashboard.exe
echo ============================================
echo   Build MiwaDashboard.exe
echo ============================================
echo.

:: Verifie Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Telecharge Python sur https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Cree un environnement virtuel si besoin
if not exist "venv_build\" (
    echo [1/4] Creation de l'environnement virtuel...
    python -m venv venv_build
)

:: Active le venv
echo [2/4] Activation du venv...
call venv_build\Scripts\activate.bat

:: Installe les dependances
echo [3/4] Installation des dependances...
pip install --quiet --upgrade pip
pip install --quiet pywebview pyinstaller

:: Lance PyInstaller
echo [4/4] Compilation en cours (peut prendre 1-2 minutes)...
pyinstaller MiwaDashboard.spec --clean --noconfirm

echo.
if exist "dist\MiwaDashboard.exe" (
    echo ============================================
    echo   SUCCES ! Fichier genere :
    echo   dist\MiwaDashboard.exe
    echo ============================================
    explorer dist
) else (
    echo [ERREUR] La compilation a echoue. Verifie les messages ci-dessus.
)

pause
