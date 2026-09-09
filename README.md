# 🎧 Story Maker from Movie

Transformez un film en histoire audio en plusieurs chapitres, prête pour la conteuse **Telmi**.

Usage strictement personnel, à partir de vos propres films.

## 🚀 Démarrage rapide

Deux étapes, et la seconde ne se fait qu'une fois.

### 1. Installez Python (une seule fois)

Téléchargez-le sur [python.org/downloads](https://www.python.org/downloads/) et lancez l'installateur.

> **Sous Windows, cochez la case « Add python.exe to PATH »** sur le premier écran de l'installateur. C'est la seule chose à ne pas rater.

### 2. Téléchargez le projet et double-cliquez

Sur cette page GitHub : bouton vert **Code → Download ZIP**. Décompressez le dossier où vous voulez, puis double-cliquez sur le lanceur de votre système :

| Système | Fichier |
|---|---|
| Windows | `lancer-windows.bat` |
| macOS | `lancer-mac.command` |
| Linux | `lancer-linux.sh` |

**Au premier lancement, tout s'installe tout seul** — comptez quelques minutes, une fenêtre noire fait défiler du texte, c'est normal. Ensuite votre navigateur s'ouvre sur l'application. Les lancements suivants sont immédiats.

C'est tout. Pas de ligne de commande, pas de FFmpeg à installer, rien d'autre.

Tout se passe **sur votre ordinateur** : aucun fichier n'est envoyé nulle part.

## 🎯 Comment ça marche

Le découpage manuel d'une bande son en chapitres est long et fastidieux. L'application l'automatise : elle repère les **silences** du film et choisit les points de coupe qui donnent des chapitres de la durée voulue, **sans jamais couper au milieu d'une réplique**.

L'interface vous guide en quatre étapes :

1. **Le film** — choisissez-le dans l'explorateur intégré (les lecteurs `C:`, `D:` sont listés, et vous pouvez coller un chemin), puis lancez l'analyse. Laissez la transcription décochée pour un premier essai.
2. **Le découpage** — indiquez où l'histoire commence et se termine pour écarter les génériques, puis bougez le curseur de durée : le tableau des chapitres **se recalcule instantanément**. Chaque coupe est étiquetée `franche`, `correcte` ou `arbitraire` pour voir d'un coup d'œil ce qui mérite un ajustement.
3. **Les images** — l'application propose une planche par chapitre et pré-sélectionne la plus lisible. Cliquez pour en choisir une autre. Étape facultative.
4. **Le pack** — donnez un titre, choisissez une image de couverture, enregistrez l'annonce du titre au micro, et générez.

Sur la Telmi, l'histoire se présente exactement comme celles de la collection « Telmi - Histoires » : la couverture s'affiche, puis un **menu des chapitres** que l'on parcourt à la molette, chacun montrant son image et s'annonçant par un petit carillon — ou par votre voix, si vous avez enregistré son annonce à l'étape 4. Une fois un chapitre choisi, les suivants s'enchaînent tout seuls ; on peut mettre en pause, et le bouton maison ramène au menu sur le chapitre en cours.

Par défaut, l'image du chapitre reste affichée pendant l'écoute. Décochez « Afficher l'image pendant l'écoute » pour que l'écran s'éteigne à la place, comme dans les histoires officielles : la batterie tient alors bien plus longtemps.

Si l'application trouve le dossier de Telmi Sync sur votre ordinateur, elle vous propose d'y **installer le pack directement**. Relancez ensuite Telmi Sync : l'histoire apparaît dans votre bibliothèque, prête à synchroniser sur la conteuse.

Tout est écrit dans un dossier `<nom_du_film>_telmi/` à côté de votre film.

## 🔧 En cas de problème

**« Python n'est pas installé » alors que je viens de l'installer** — la case « Add python.exe to PATH » n'a pas été cochée. Relancez l'installateur de Python, choisissez *Modify*, et cochez-la. Ou plus simple : désinstallez et réinstallez en la cochant.

**Windows affiche « Windows a protégé votre ordinateur »** — c'est l'avertissement habituel pour un fichier téléchargé. Cliquez sur *Informations complémentaires*, puis *Exécuter quand même*.

**La fenêtre noire se ferme aussitôt** — un message d'erreur s'y trouvait. Relancez le fichier depuis un terminal pour le lire, ou envoyez une capture.

**L'installation échoue au premier lancement** — vérifiez la connexion internet, puis relancez : elle reprend là où elle s'est arrêtée.

**Le pack n'apparaît pas dans Telmi Sync** — le glisser-déposer sur sa fenêtre ne fait rien. Telmi Sync lit ses histoires dans `C:\Users\<vous>\.telmi\stories` (Windows) ou `~/.telmi/stories` (macOS, Linux). Copiez-y le dossier produit tel quel, puis relancez Telmi Sync.

**Trop de coupes « arbitraire »** — trop peu de silences trouvés. Dans les réglages avancés de l'étape 1, **remontez** le seuil de silence vers −25 ou −20 dB (moins négatif = plus tolérant = plus de silences), et relancez l'analyse.

## 🎙️ La transcription des dialogues (facultatif)

Cocher « Transcrire les dialogues » empêche toute coupe au milieu d'une réplique et remplit le texte de chaque chapitre. C'est bien meilleur, mais **lourd** : cela installe PyTorch (2 à 3 Go) et la transcription d'un long métrage prend de 30 minutes à plus d'une heure.

Pour l'activer, ouvrez un terminal dans le dossier du projet et lancez :

```bash
.venv\Scripts\python -m pip install -r requirements-transcription.txt      # Windows
.venv/bin/python -m pip install -r requirements-transcription.txt          # macOS, Linux
```

Une transcription déjà calculée est réutilisée : changer le seuil de silence ne coûte ensuite que quelques minutes.

## ⌨️ Pour aller plus loin : la ligne de commande

Les mêmes traitements existent script par script, pour qui préfère automatiser. Chaque script accepte `--help`. Utilisez le Python de l'environnement isolé (`.venv\Scripts\python` sous Windows, `.venv/bin/python` ailleurs), ou installez `requirements.txt` dans le vôtre.

```bash
# 1. Extraire la bande son
python scripts/extract_audio.py mon_film.mkv -o audio_du_film.wav

# 2. Transcrire les dialogues (facultatif, demande requirements-transcription.txt)
python scripts/transcribe.py audio_du_film.wav -m base --srt

# 3. Découper en chapitres : d'abord un aperçu, qui n'encode rien
python scripts/split_chapters.py audio_du_film.wav -d 300 --srt audio_du_film.srt --preview
#    puis la découpe réelle
python scripts/split_chapters.py audio_du_film.wav -d 300 --srt audio_du_film.srt -o chapitres

# 4. Une image par chapitre
python scripts/extract_chapter_images.py mon_film.mkv chapitres/chapters.json

# 5. Assembler le pack Telmi
python scripts/build_pack.py chapitres/chapters.json -t "Le titre de l'histoire" --age 5 -o pack
```

Pour ajuster le découpage : `--noise -25` trouve plus de silences (un seuil moins négatif est plus tolérant), `--tolerance 0.3` resserre les durées, `--boundary-weight 0.4` privilégie les belles coupures, `-n 12` vise un nombre de chapitres.

Le pack produit contient `metadata.json`, `nodes.json`, `notes.json`, `title.mp3`, `title.png`, `audios/` et `images/`, et son dossier est nommé selon la convention de Telmi Sync : `Collection_âge_Titre_identifiant`.

Deux outils annexes : `scripts/extract_images.py` (planche contact, une image toutes les X secondes) et `scripts/convert_to_telmi.py` (convertit un dossier d'images en PNG 640x480).

## 📓 Notebooks

`extract_images_audio_text_from_video.ipynb` et `convert_image_to_square.ipynb` reprennent les étapes d'extraction de façon interactive, pour explorer un film avant de lancer la chaîne.
