#!/usr/bin/env python3
"""Assemble un pack d'histoire Telmi à partir des chapitres découpés.

Produit l'arborescence attendue par Telmi OS : metadata.json, nodes.json,
notes.json, title.mp3, title.png, puis les dossiers audios/ et images/.
Les chapitres s'enchaînent automatiquement les uns après les autres
(autoplay), et le dernier clôt l'histoire.

Exemple :
    python scripts/build_pack.py chapitres/chapters.json -t "Mon histoire" -o pack
"""

import argparse
import json
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

from ffmpeg_tools import make_silent_mp3

# Longueur à laquelle Telmi Sync tronque le titre dans le nom de dossier,
# déduite des histoires déjà installées (deux s'arrêtent net à 32 caractères)
TITLE_IN_FOLDER = 32

# Couleurs acceptées par Telmi Sync pour les vignettes de scènes
NOTE_COLORS = ("blue", "pink", "purple3", "red2")


def telmi_uuid() -> str:
    """Fabrique un identifiant à la manière de Telmi.

    Les histoires installées portent un identifiant « xxxxxx-<horodatage> »,
    où l'horodatage est le nombre de millisecondes depuis 1970, en
    hexadécimal. Le préfixe reprend celui de l'exemple de la documentation.
    """
    return f"ffffff-{int(time.time() * 1000):x}"


def folder_title(title: str) -> str:
    """Nettoie un titre pour l'insérer dans un nom de dossier.

    Les histoires installées sont sans accent ni apostrophe et tronquées
    à 32 caractères.
    """
    sans_accent = "".join(
        lettre for lettre in unicodedata.normalize("NFKD", title)
        if not unicodedata.combining(lettre)
    )
    propre = re.sub(r"[^A-Za-z0-9 \-]", " ", sans_accent)
    return re.sub(r"\s+", " ", propre).strip()[:TITLE_IN_FOLDER].strip()


def pack_folder_name(title: str, age, identifier: str, category: str | None = None) -> str:
    """Nom de dossier attendu par Telmi Sync : éditeur_âge_titre_identifiant."""
    try:
        age_texte = f"{int(age):02d}"
    except (TypeError, ValueError):
        age_texte = "00"
    return f"{(category or 'Mes histoires').strip()}_{age_texte}_" \
           f"{folder_title(title)}_{identifier}"


def build_nodes(count: int) -> dict:
    """Construit le graphe d'une histoire linéaire de `count` chapitres.

    L'action aN mène à la scène sN ; la scène sN enchaîne sur l'action
    a(N+1) à la fin de son audio. La dernière scène n'a pas de suite.
    """
    stages: dict[str, dict] = {}
    actions: dict[str, list] = {}

    for index in range(count):
        is_last = index == count - 1
        stages[f"s{index}"] = {
            "image": f"s{index}.png",
            "audio": f"s{index}.mp3",
            "ok": None if is_last else {"action": f"a{index + 1}", "index": 0},
            "home": {"action": "backAction", "index": 0},
            "control": {"ok": not is_last, "home": True, "autoplay": not is_last},
        }
        actions[f"a{index}"] = [{"stage": f"s{index}"}]

    stages["backStage"] = {
        "image": None,
        "audio": None,
        "ok": {"action": "backChildAction", "index": 0},
        "home": {"action": "backAction", "index": 0},
        "control": {"ok": True, "home": False, "autoplay": True},
    }
    actions["backAction"] = [{"stage": "backStage"}]
    actions["backChildAction"] = []

    return {
        "startAction": {"action": "a0", "index": 0},
        "stages": stages,
        "actions": actions,
    }


def build_notes(chapters: list[dict]) -> dict:
    """Résumé de chaque scène, affiché dans Telmi Sync (sans effet sur la lecture)."""
    notes = {}
    for index, chapter in enumerate(chapters):
        text = (chapter.get("text") or "").strip()
        if len(text) > 500:
            text = text[:497].rstrip() + "..."
        notes[f"s{index}"] = {
            "title": chapter.get("title") or f"Chapitre {index + 1}",
            "notes": text,
            "color": NOTE_COLORS[index % len(NOTE_COLORS)],
        }
    return notes


def create_pack(
    chapters: list[dict], source_dir: Path, pack_dir: Path, title: str,
    age: str = "5", category: str | None = None, description: str | None = None,
    title_audio: Path | None = None, cover: Path | None = None,
    identifier: str | None = None,
) -> dict:
    """Écrit le pack complet sur le disque.

    Retourne un compte rendu : chapitres sans image, et si title.mp3 est
    resté un simple silence. Lève FileNotFoundError si un audio manque.
    """
    identifier = identifier or telmi_uuid()
    audios_dir = pack_dir / "audios"
    images_dir = pack_dir / "images"
    audios_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    missing_images: list[int] = []
    for index, chapter in enumerate(chapters):
        audio_source = source_dir / chapter["file"]
        if not audio_source.is_file():
            raise FileNotFoundError(
                f"Audio manquant : {audio_source}. "
                "Lancez d'abord la découpe pour produire les MP3."
            )
        shutil.copy2(audio_source, audios_dir / f"s{index}.mp3")

        image_name = chapter.get("image") or (Path(chapter["file"]).stem + ".png")
        image_source = source_dir / image_name
        if image_source.is_file():
            shutil.copy2(image_source, images_dir / f"s{index}.png")
        else:
            missing_images.append(index + 1)

    (pack_dir / "nodes.json").write_text(
        json.dumps(build_nodes(len(chapters)), indent=2) + "\n", encoding="utf-8"
    )
    (pack_dir / "notes.json").write_text(
        json.dumps(build_notes(chapters), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    metadata = {
        "title": title,
        "uuid": identifier,
        "image": "title.png",
        "version": 2,
        "age": str(age),
    }
    if category:
        metadata["category"] = category
    if description:
        metadata["description"] = description
    (pack_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Couverture fournie par l'utilisateur, sinon celle du premier chapitre
    first_image = images_dir / "s0.png"
    if cover is not None and Path(cover).is_file():
        shutil.copy2(cover, pack_dir / "title.png")
        has_cover = True
    elif first_image.is_file():
        shutil.copy2(first_image, pack_dir / "title.png")
        has_cover = True
    else:
        has_cover = False

    silent_title = title_audio is None
    if title_audio is not None:
        shutil.copy2(title_audio, pack_dir / "title.mp3")
    else:
        make_silent_mp3(pack_dir / "title.mp3")

    return {
        "missing_images": missing_images,
        "silent_title": silent_title,
        "has_cover": has_cover,
        "pack_dir": str(pack_dir),
        "uuid": identifier,
        "folder_name": pack_folder_name(title, age, identifier, category),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "manifest", type=Path,
        help="Fichier chapters.json produit par split_chapters.py",
    )
    parser.add_argument("-t", "--title", required=True, help="Titre de l'histoire")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("pack"),
        help="Dossier du pack à créer (défaut : pack)",
    )
    parser.add_argument("--age", default="5", help="Âge conseillé (défaut : 5)")
    parser.add_argument("--category", default=None, help="Catégorie (optionnel)")
    parser.add_argument("--description", default=None, help="Description (optionnel)")
    parser.add_argument(
        "--title-audio", type=Path, default=None,
        help="MP3 annonçant le titre. Sans lui, un court silence est mis en place.",
    )
    args = parser.parse_args()

    if not args.manifest.is_file():
        sys.exit(f"Erreur : fichier introuvable : {args.manifest}")
    if args.title_audio and not args.title_audio.is_file():
        sys.exit(f"Erreur : fichier introuvable : {args.title_audio}")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    chapters = manifest.get("chapters", [])
    if not chapters:
        sys.exit("Erreur : aucun chapitre trouvé dans le manifeste.")

    print(f"Construction du pack « {args.title} » ({len(chapters)} chapitres)...")
    try:
        report = create_pack(
            chapters, args.manifest.parent, args.output, args.title,
            args.age, args.category, args.description, args.title_audio,
        )
    except FileNotFoundError as e:
        sys.exit(f"Erreur : {e}")

    if report["missing_images"]:
        print("\n⚠️  Images manquantes pour le(s) chapitre(s) "
              f"{', '.join(str(n) for n in report['missing_images'])}.")
        print("   Lancez extract_chapter_images.py, ou déposez vous-même des "
              "PNG 640x480 dans le dossier images/ du pack.")
    if not report["has_cover"]:
        print("⚠️  Pas de title.png : ajoutez une image de couverture 640x480.")
    if report["silent_title"]:
        print("ℹ️  title.mp3 est un silence d'une seconde. Remplacez-le par un "
              "enregistrement du titre, ou passez --title-audio.")

    print(f"\nPack écrit dans '{args.output}'.")
    print("Copiez ce dossier dans vos histoires via Telmi Sync.")


if __name__ == "__main__":
    main()
