# 🎧 Story Maker from Movie

Transformez un film en histoire audio en plusieurs chapitres, prête pour la conteuse **Telmi**.

Usage strictement personnel, à partir de vos propres films.

## 🎯 Principe

Le découpage manuel d'une bande son en chapitres est long et fastidieux. Ce projet l'automatise : il repère les **silences** du film et choisit les points de coupe qui donnent des chapitres de la durée voulue **sans jamais couper au milieu d'une réplique**.

```
film.mkv ─┬─► audio ──► découpage en chapitres ──► MP3 par chapitre ─┐
          │              (silences + transcription)                   ├─► pack Telmi
          └─► une image par chapitre (PNG 640x480) ───────────────────┘
```

## 🛠️ Installation

1. Installez les dépendances :

   ```bash
   pip install -r requirements.txt
   ```

2. Installez [FFmpeg](https://ffmpeg.org/). À défaut, le binaire fourni par `imageio-ffmpeg` est utilisé automatiquement.

Python 3.10 ou plus récent est requis.

## 🖱️ L'application (sans ligne de commande)

Double-cliquez sur le lanceur correspondant à votre système :

| Système | Fichier |
|---|---|
| macOS | `lancer-mac.command` |
| Windows | `lancer-windows.bat` |
| Linux | `lancer-linux.sh` |

Votre navigateur s'ouvre sur l'interface. Tout se passe **sur votre machine** : le serveur n'écoute que sur `127.0.0.1`, aucun fichier n'est envoyé nulle part.

L'interface vous guide en trois étapes :

1. **Le film** — choisissez-le dans l'explorateur intégré, cochez la transcription si vous la voulez, puis lancez l'analyse (avec barre de progression).
2. **Le découpage** — bougez le curseur de durée : le tableau des chapitres **se recalcule instantanément**, sans réanalyser le film. Chaque coupe est étiquetée `franche`, `correcte` ou `arbitraire` pour que vous voyiez d'un coup d'œil ce qui mérite un ajustement.
3. **Le pack** — donnez un titre, et l'application encode les MP3, choisit une image par chapitre et assemble le dossier prêt pour Telmi Sync.

Tout est écrit dans un dossier `<nom_du_film>_telmi/` à côté de votre film.

Si vous préférez, `python app.py` fait exactement la même chose que les lanceurs.

## ⌨️ En ligne de commande

Les mêmes traitements sont disponibles script par script.

### 1. Extraire la bande son

```bash
python scripts/extract_audio.py mon_film.mkv -o audio_du_film.wav
```

### 2. Transcrire les dialogues (recommandé)

Le `.srt` sert à deux choses : éviter de couper une réplique en deux, et remplir le texte de chaque chapitre.

```bash
python scripts/transcribe.py audio_du_film.wav -m base --srt
```

### 3. Découper en chapitres

Commencez par un **aperçu**, qui n'encode rien :

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

| Mention | Signification |
|---|---|
| `franche` | sur un silence net, coupure idéale |
| `correcte` | sur un silence court |
| `arbitraire` | aucun silence utilisable, coupure à l'aveugle |
| `sur une réplique !` | à éviter, ajustez les réglages |

Quand le découpage convient, relancez sans `--preview` :

```bash
python scripts/split_chapters.py audio_du_film.wav -d 300 --srt audio_du_film.srt -o chapitres
```

**Si le résultat ne vous plaît pas :**

- trop de coupes `arbitraire` → le film est bruyant, essayez `--noise -40` ou `--min-silence 0.4` ;
- chapitres trop inégaux → baissez `--tolerance` (0.3 par exemple) ;
- vous préférez de belles coupures à des durées régulières → montez `--boundary-weight` (0.4) ;
- vous voulez un nombre de chapitres précis → `-n 12` au lieu de `-d`.

### 4. Choisir une image par chapitre

```bash
python scripts/extract_chapter_images.py mon_film.mkv chapitres/chapters.json
```

Une image ne vous plaît pas ? Remplacez le PNG correspondant dans `chapitres/` par le vôtre, en 640x480.

### 5. Assembler le pack Telmi

```bash
python scripts/build_pack.py chapitres/chapters.json -t "Le titre de l'histoire" --age 5 -o pack
```

Le dossier `pack/` contient `metadata.json`, `nodes.json`, `notes.json`, `title.mp3`, `title.png`, `audios/` et `images/`. Les chapitres s'enchaînent automatiquement, et le dernier clôt l'histoire.

> `title.mp3` est un silence d'une seconde par défaut. Remplacez-le par un enregistrement du titre, ou passez `--title-audio mon_titre.mp3`.

## 🧰 Les autres outils

- `scripts/extract_images.py` : planche contact classique, une image toutes les X secondes.
- `scripts/convert_to_telmi.py` : convertit un dossier d'images au format Telmi (PNG 640x480, rognage centré).

Chaque script accepte `--help`.

## 📓 Notebooks

`extract_images_audio_text_from_video.ipynb` et `convert_image_to_square.ipynb` reprennent les étapes d'extraction de façon interactive, pour explorer un film avant de lancer la chaîne.

## 💡 Conseils

- Pour la transcription, le modèle Whisper `base` est un bon compromis ; `medium` ou `large` sont plus lents mais bien meilleurs.
- L'aperçu (interface ou `--preview`) ne réencode rien : ajustez autant que vous voulez avant de générer.
