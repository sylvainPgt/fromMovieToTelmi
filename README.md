# 🎧 Story Maker from Movie

Une boîte à outils Python pour transformer un fichier vidéo (film, dessin animé) en une histoire audio illustrée, prête pour la conteuse **Telmi**.

## 🎯 Objectif

Ce projet automatise l'extraction des médias d'un film pour faciliter la création d'histoires :

1. **Planche contact** : capture une image toutes les X secondes pour servir d'illustrations aux chapitres.
2. **Extraction audio** : récupère la bande son complète pour le montage.
3. **Transcription** : convertit les dialogues en texte (avec horodatages en option) pour repérer facilement les moments clés — et pour nourrir une IA dans le but de créer une histoire texte.
4. **Formatage Telmi** : redimensionne les images sélectionnées au format **640x480** (JPG), sans déformation (rognage centré).

## 🛠️ Installation

1. Clonez le repo et installez les dépendances :

   ```bash
   pip install -r requirements.txt
   ```

2. Pré-requis : installez [FFmpeg](https://ffmpeg.org/) sur votre machine (nécessaire pour le traitement audio/vidéo).

## 🚀 Utilisation

Deux façons de travailler, au choix :

### En ligne de commande (dossier `scripts/`)

```bash
# 1. Une image toutes les 8 secondes dans le dossier "captures"
python scripts/extract_images.py mon_film.mkv -o captures -i 8

# 2. Extraction de la bande son en .wav
python scripts/extract_audio.py mon_film.mkv -o audio_du_film.wav

# 3. Transcription des dialogues (--srt ajoute un fichier avec horodatages)
python scripts/transcribe.py audio_du_film.wav -m base --srt

# 4. Conversion des images choisies au format Telmi (JPG 640x480)
python scripts/convert_to_telmi.py mes_images_choisies -o telmi_ready
```

Chaque script accepte `--help` pour voir toutes les options.

### Avec les notebooks Jupyter

- `extract_images_audio_text_from_video.ipynb` : les étapes 1 à 3 (images, audio, transcription), avec les paramètres à modifier en tête de cellule.
- `convert_image_to_square.ipynb` : l'étape 4 (formatage Telmi).

## 💡 Conseils

- Pour la transcription, le modèle Whisper `base` est un bon compromis vitesse/précision ; `medium` ou `large` sont plus lents mais bien meilleurs.
- Le workflow typique : extraire la planche contact, choisir à la main les meilleures images dans un dossier, puis les passer au script de conversion Telmi.
