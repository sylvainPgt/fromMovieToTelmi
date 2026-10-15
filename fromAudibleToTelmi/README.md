# 📚 Story Maker from Audible

Transformez un livre audio Audible en histoire à chapitres, prête pour la conteuse **Telmi**.

Petit frère de [Story Maker from Movie](../README.md), rangé dans le même dépôt : même installation, même interface, même pack Telmi à l'arrivée.

Usage strictement personnel, à partir des livres que vous avez achetés.

## Avant de commencer : Libation

Les fichiers téléchargés depuis Audible (`.aax`) sont protégés et ne se lisent nulle part ailleurs. [Libation](https://getlibation.com/), logiciel libre, télécharge les livres de votre bibliothèque Audible et les convertit en fichiers audio ordinaires.

Une fois le livre « libéré », Libation crée un dossier `Titre [B0XXXXXXXX]` dans `Libation\Books`. **C'est ce dossier que l'application lit.**

Tous les réglages de Libation conviennent : un seul fichier `.m4b` ou `.mp3` avec ses chapitres (le défaut), ou un fichier par chapitre.

## 🚀 Démarrage rapide

### 1. Installez Python (une seule fois)

Téléchargez-le sur [python.org/downloads](https://www.python.org/downloads/) et lancez l'installateur.

> **Sous Windows, cochez la case « Add python.exe to PATH »** sur le premier écran de l'installateur.

### 2. Téléchargez le projet et double-cliquez

Sur la page du dépôt : bouton vert **Code → Download ZIP**, décompressez, ouvrez le dossier **`fromAudibleToTelmi`**, puis double-cliquez sur le lanceur de votre système :

| Système | Fichier |
|---|---|
| Windows | `lancer-windows.bat` |
| macOS | `lancer-mac.command` |
| Linux | `lancer-linux.sh` |

Au premier lancement, tout s'installe tout seul (quelques dizaines de Mo seulement, bien moins que la version film). Ensuite votre navigateur s'ouvre sur l'application.

Tout se passe **sur votre ordinateur** : aucun fichier n'est envoyé nulle part.

## 🎯 Comment ça marche

Un livre Audible arrive déjà découpé en chapitres, mais ils conviennent rarement tels quels à la Telmi : des « Crédits d'ouverture » de trente secondes, puis des chapitres de quarante minutes. L'application les adapte en trois étapes :

1. **Le livre** — l'explorateur s'ouvre directement sur `Libation\Books`, et les dossiers de livres y sont marqués 📚 : un clic suffit. L'application lit le titre, l'auteur, la couverture et les chapitres.
2. **Les chapitres** — deux façons de faire :
   - **Garder les chapitres du livre**, un pour un ;
   - **Viser une durée** : les petits chapitres sont regroupés et les longs recoupés. Les fins de chapitre du livre sont les coupes préférées ; à l'intérieur d'un chapitre trop long, l'application coupe sur un silence. Le tableau se recalcule en direct et indique le contenu de chaque chapitre (« Chapitre 2 (suite) → Chapitre 3 »).

   Indiquez aussi où l'histoire commence et finit, pour écarter le jingle Audible et les crédits. Les crédits de quelques secondes sont rattachés au chapitre voisin plutôt que de faire un chapitre à part.
3. **Le pack** — âge, collection, puis pour chaque histoire : son titre, son image (la couverture du livre par défaut) et l'annonce du titre au micro. Générez.

### 📦 Une compilation ? Une histoire par tome

Pour un livre qui réunit plusieurs tomes (« Les Légendaires, Tomes 1-8 »), cochez **Une histoire par tome** à l'étape 2. L'application repère les tomes d'après les titres des chapitres (« Tome 3 », un nom de tome qui change, une numérotation qui repart à 1) et coche les chapitres qui ouvrent chaque tome. Corrigez d'un clic si besoin : la liste des chapitres du livre est affichée, cocher un chapitre y fait commencer une nouvelle histoire.

Chaque tome devient une histoire à part sur la Telmi, avec son propre menu de chapitres, son titre et **son image** — à choisir pour chacune à l'étape 3. Un seul clic sur « Générer » produit tous les packs.

Sur la Telmi, l'histoire se présente comme celles de la collection « Telmi - Histoires » : la couverture, puis un **menu des chapitres** que l'on parcourt à la molette. Comme toutes les images reprennent la couverture, chacune porte une **pastille numérotée** pour s'y retrouver. La couverture, souvent carrée, est posée entière sur un fond flouté plutôt que rognée : son titre reste lisible.

Si l'application trouve le dossier de Telmi Sync, elle propose d'y **installer le pack directement**. Relancez ensuite Telmi Sync : l'histoire apparaît dans votre bibliothèque.

Tout est écrit dans un dossier `<nom_du_livre>_telmi/` à côté du livre.

## 🔧 En cas de problème

**« Ce fichier .aax est encore protégé »** — le livre n'est pas passé par Libation. Ouvrez Libation, libérez-le, puis choisissez le dossier qu'il produit.

**Un chapitre de 40 minutes reste d'un seul tenant** — passez en mode « Viser une durée ». Si les coupes sont « arbitraires », cochez « Repérer aussi les silences » dans les réglages avancés de l'étape 1 et relisez le livre.

**Le pack n'apparaît pas dans Telmi Sync** — Telmi Sync lit ses histoires dans `C:\Users\<vous>\.telmi\stories` (Windows) ou `~/.telmi/stories` (macOS, Linux). Copiez-y le dossier produit tel quel, puis relancez Telmi Sync.

Pour le reste (Python introuvable, avertissement de Windows), voir le [README de Story Maker from Movie](../README.md#-en-cas-de-problème).

## ⌨️ La ligne de commande

Chaque script accepte `--help`. Utilisez le Python de l'environnement isolé (`.venv\Scripts\python` sous Windows, `.venv/bin/python` ailleurs).

```bash
# 1. Ce que contient le livre : titre, couverture, chapitres
python scripts/read_book.py "Libation/Books/Mon livre [B0XXXXXXXX]"

# 2. Le découpage : d'abord un aperçu, qui n'encode rien
#    (ajoutez --tomes pour une compilation : un sous-dossier tome_01, tome_02... par tome,
#     et --tome-starts 1,24,51 pour imposer les chapitres qui ouvrent chaque tome)
python scripts/plan_book.py "Libation/Books/Mon livre [B0XXXXXXXX]" -d 600 --skip-start 30 --preview
#    puis la découpe réelle (ou --mode livre pour garder les chapitres tels quels)
python scripts/plan_book.py "Libation/Books/Mon livre [B0XXXXXXXX]" -d 600 --skip-start 30 -o chapitres

# 3. Les images, tirées de la couverture (ou d'une image à vous avec --cover)
python scripts/make_images.py chapitres/chapters.json

# 4. Le pack Telmi
python scripts/build_pack.py chapitres/chapters.json -t "Le titre de l'histoire" --age 7 -o pack
```

`build_pack.py`, `ffmpeg_tools.py` et `convert_to_telmi.py` sont repris de Story Maker from Movie : le pack produit est identique (`metadata.json`, `nodes.json`, `notes.json`, `title.mp3`, `title.png`, `audios/`, `images/`).
