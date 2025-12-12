# 🎧 Story Maker from Movie

Une boîte à outils Python pour transformer un fichier vidéo (film, dessin animé) en une histoire audio illustrée, prête pour la conteuse **Telmi**.

## 🎯 Objectif
Ce projet automatise l'extraction des médias d'un film pour faciliter la création d'histoires :
1. **Extraction Audio** : Récupère la bande son complète pour le montage.
2. **Planche Contact** : Capture une image toutes les X secondes pour servir d'illustrations aux chapitres.
3. **Transcription** : Convertit les dialogues en texte pour repérer facilement les moments clés (et pour nourrir une IA dans le but de créer une histoire texte)
4. **Formatage Telmi** : Redimensionne les images sélectionnées au format **640x480** (jpg).

## 🛠️ Installation

1. Clonez le repo et installez les dépendances :
   ```bash
   pip install -r requirements.txt
