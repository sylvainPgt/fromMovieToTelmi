# 🎧 Story Maker from Movie

Une boîte à outils Python pour transformer un fichier vidéo (film, dessin animé) en une histoire audio en plusieurs chapitres, prête pour la conteuse **Telmi**.

Usage strictement personnel, à partir de vos propres films.

## 🎯 Principe

Le découpage manuel d'une bande son en chapitres est long et fastidieux. Ce projet l'automatise : il repère les **silences** du film et choisit les points de coupe qui donnent des chapitres de la durée voulue **sans jamais couper au milieu d'une réplique**.

La chaîne complète va du fichier vidéo au pack Telmi prêt à copier :

```
film.mkv ─┬─► audio ──► découpage en chapitres ──► MP3 par chapitre ─┐
          │              (silences + transcription)                   ├─► pack Telmi
          └─► une image par chapitre (PNG 640x480) ───────────────────┘
```

## 🛠️ Installation

1. Clonez le repo et installez les dépendances :

   ```bash
   pip install -r requirements.txt
   ```

2. Installez [FFmpeg](https://ffmpeg.org/) sur votre machine. À défaut, les scripts utilisent automatiquement le binaire fourni par `imageio-ffmpeg`.

Python 3.10 ou plus récent est requis.

## 🚀 La chaîne complète

### 1. Extraire la bande son

```bash
python scripts/extract_audio.py mon_film.mkv -o audio_du_film.wav
```

### 2. Transcrire les dialogues (recommandé)

Le fichier `.srt` sert à deux choses : éviter de couper une réplique en deux, et remplir le texte de chaque chapitre.

```bash
python scripts/transcribe.py audio_du_film.wav -m base --srt
```

### 3. Découper en chapitres

Commencez toujours par un **aperçu**, qui n'encode rien et permet de régler les paramètres en quelques secondes :

```bash
python scripts/split_chapters.py audio_du_film.wav -d 300 --srt audio_du_film.srt --preview
```

```
5 chapitres proposés :

    #     Début       Fin    Durée  Coupe
    1   0:00:00   0:05:02  0:05:02  franche
    2   0:05:02   0:09:58  0:04:56  franche
    3   0:09:58   0:15:01  0:05:03  correcte
    ...
```

La colonne **Coupe** indique où tombe le début du chapitre :

| Mention | Signification |
|---|---|
| `franche` | sur un silence net, coupure idéale |
| `correcte` | sur un silence court |
| `arbitraire` | aucun silence utilisable, coupure à l'aveugle |
| `sur une réplique !` | à éviter, ajustez les réglages |

Quand le découpage vous convient, relancez sans `--preview` pour produire les MP3 :

```bash
python scripts/split_chapters.py audio_du_film.wav -d 300 --srt audio_du_film.srt -o chapitres
```

Vous obtenez un dossier `chapitres/` avec les MP3 (44100 Hz, format Telmi) et un `chapters.json` décrivant le découpage.

**Si le résultat ne vous plaît pas :**

- trop de coupes `arbitraire` → le film est bruyant, abaissez le seuil avec `--noise -40` ou `--min-silence 0.4` ;
- chapitres trop inégaux → baissez `--tolerance` (0.3 par exemple) ;
- vous préférez de belles coupures à des durées régulières → montez `--boundary-weight` (0.4 par exemple) ;
- vous voulez un nombre de chapitres précis → `-n 12` au lieu de `-d`.

### 4. Choisir une image par chapitre

Le script teste plusieurs images au cœur de chaque chapitre et garde la plus lisible, en écartant les fondus au noir :

```bash
python scripts/extract_chapter_images.py mon_film.mkv chapitres/chapters.json
```

Une image ne vous plaît pas ? Remplacez simplement le PNG correspondant dans `chapitres/` par le vôtre, en 640x480.

### 5. Assembler le pack Telmi

```bash
python scripts/build_pack.py chapitres/chapters.json -t "Le titre de l'histoire" --age 5 -o pack
```

Le dossier `pack/` contient alors `metadata.json`, `nodes.json`, `notes.json`, `title.mp3`, `title.png`, `audios/` et `images/`. Les chapitres s'enchaînent automatiquement, et le dernier clôt l'histoire. Il ne reste qu'à copier ce dossier via **Telmi Sync**.

> `title.mp3` est un silence d'une seconde par défaut. Remplacez-le par un enregistrement du titre, ou passez `--title-audio mon_titre.mp3`.

## 🧰 Les autres outils

- `scripts/extract_images.py` : planche contact classique, une image toutes les X secondes, si vous préférez choisir vos illustrations à la main.
- `scripts/convert_to_telmi.py` : convertit un dossier d'images au format Telmi (PNG 640x480, rognage centré sans déformation).

Chaque script accepte `--help` pour voir toutes les options.

## 📓 Notebooks

Les notebooks `extract_images_audio_text_from_video.ipynb` et `convert_image_to_square.ipynb` reprennent les étapes d'extraction et de formatage de façon interactive, pour explorer un film avant de lancer la chaîne.

## 💡 Conseils

- Pour la transcription, le modèle Whisper `base` est un bon compromis vitesse/précision ; `medium` ou `large` sont plus lents mais bien meilleurs.
- L'aperçu (`--preview`) ne réencode rien : n'hésitez pas à l'enchaîner plusieurs fois pour trouver vos réglages avant de lancer la découpe réelle.
