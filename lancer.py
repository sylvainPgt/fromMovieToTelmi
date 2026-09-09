#!/usr/bin/env python3
"""Démarre Story Maker en préparant tout ce qu'il faut la première fois.

Ce fichier n'a besoin que de Python. Il crée un environnement isolé (.venv),
y installe les composants listés dans requirements.txt quand c'est
nécessaire, puis lance l'application. Les fichiers à double-clic
(lancer-windows.bat, lancer-mac.command, lancer-linux.sh) l'appellent ;
on peut aussi le lancer directement : python lancer.py
"""

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
# Empreinte de requirements.txt au moment de la dernière installation réussie :
# si le fichier change (mise à jour du projet), on réinstalle.
MARKER = VENV / "requirements.sha256"


def say(message: str = "") -> None:
    print(f"  {message}", flush=True)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def check_python_version() -> None:
    if sys.version_info >= (3, 10):
        return
    say(f"Python {sys.version_info.major}.{sys.version_info.minor} est trop ancien : "
        "il faut la version 3.10 ou plus récente.")
    say("Téléchargez-la sur https://www.python.org/downloads/ puis relancez.")
    sys.exit(1)


def ensure_venv() -> None:
    if venv_python().is_file():
        return
    say("Premier lancement : préparation d'un environnement Python isolé...")
    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(VENV)
    except Exception as error:  # noqa: BLE001 - tout échec doit être expliqué
        say(f"Impossible de créer l'environnement : {error}")
        if sys.platform.startswith("linux"):
            say("Sur Debian/Ubuntu, installez d'abord : sudo apt install python3-venv")
        sys.exit(1)


def requirements_digest() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ensure_requirements() -> None:
    digest = requirements_digest()
    if MARKER.is_file() and MARKER.read_text(encoding="utf-8").strip() == digest:
        return

    say("Installation des composants nécessaires.")
    say("Cela prend quelques minutes et ne se fait qu'une seule fois.")
    say()
    python = str(venv_python())
    # Un pip trop ancien peut refuser des paquets récents. Cette mise à jour
    # est un simple confort : si elle échoue (réseau lent, coupure), on
    # continue sans rien afficher, l'installation qui suit dira ce qu'il en est.
    subprocess.run(
        [python, "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Quelques centaines de Mo à télécharger : on laisse du temps aux
    # connexions lentes avant de déclarer forfait.
    result = subprocess.run([
        python, "-m", "pip", "install", "--timeout", "60", "-r", str(REQUIREMENTS),
    ])
    if result.returncode != 0:
        say()
        say("L'installation a échoué. Vérifiez la connexion internet, puis relancez.")
        sys.exit(1)

    MARKER.write_text(digest, encoding="utf-8")
    say()
    say("Composants installés.")
    say()


def main() -> None:
    check_python_version()
    os.chdir(ROOT)
    ensure_venv()
    ensure_requirements()
    # L'application tourne dans l'environnement isolé, pas dans le Python
    # qui a servi à l'amorcer.
    sys.exit(subprocess.call([str(venv_python()), str(ROOT / "app.py"), *sys.argv[1:]]))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
