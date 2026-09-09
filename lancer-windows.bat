@echo off
setlocal
cd /d "%~dp0"
title Story Maker

REM "py" est installe avec Python meme si la case "Add to PATH" a ete oubliee.
REM "python" seul peut etre un raccourci vers le Microsoft Store : on l'evite en premier.
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo  Python n'est pas installe sur cet ordinateur.
    echo.
    echo  1. Telechargez-le sur https://www.python.org/downloads/
    echo  2. Dans l'installateur, cochez la case "Add python.exe to PATH"
    echo  3. Une fois l'installation terminee, relancez ce fichier.
    echo.
    pause
    exit /b 1
)

%PY% lancer.py
if errorlevel 1 pause
