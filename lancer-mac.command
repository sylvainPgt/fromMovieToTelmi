#!/bin/bash
# Double-cliquez sur ce fichier pour ouvrir Story Maker.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo
    echo "  Python 3 n'est pas installé sur cet ordinateur."
    echo "  Téléchargez-le sur https://www.python.org/downloads/ puis relancez ce fichier."
    echo
    read -r -p "  Appuyez sur Entrée pour fermer."
    exit 1
fi

python3 lancer.py || read -r -p "  Appuyez sur Entrée pour fermer."
