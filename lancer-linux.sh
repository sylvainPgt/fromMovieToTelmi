#!/bin/bash
# Double-cliquez sur ce fichier (ou lancez-le) pour ouvrir Story Maker.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo
    echo "  Python 3 n'est pas installé. Sur Debian/Ubuntu : sudo apt install python3 python3-venv"
    echo
    read -r -p "  Appuyez sur Entrée pour fermer."
    exit 1
fi

python3 lancer.py || read -r -p "  Appuyez sur Entrée pour fermer."
