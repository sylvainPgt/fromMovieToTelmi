#!/usr/bin/env python3
"""Assemble un pack d'histoire Telmi à partir des chapitres découpés.

Produit l'arborescence attendue par Telmi OS : metadata.json, nodes.json,
notes.json, title.mp3, title.png, puis les dossiers audios/ et images/.
L'histoire s'ouvre sur un menu des chapitres, comme les histoires de la
collection « Telmi - Histoires » ; une fois un chapitre choisi, les
suivants s'enchaînent d'eux-mêmes et la fin rend la main à la Telmi.

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

from ffmpeg_tools import make_chime, make_silent_mp3

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


def build_nodes(count: int, show_image: bool = True, has_cover: bool = True) -> dict:
    """Construit le graphe d'une histoire à menu de chapitres.

    Le graphe reprend trait pour trait celui des histoires classiques de la
    collection « Telmi - Histoires » (relevé dans un nodes.json installé) :

    - s0 : l'introduction, couverture à l'écran et court carillon, qui
      enchaîne d'elle-même sur le menu ; le bouton maison y quitte l'histoire.
    - s1 à sN : le menu (action a1), une scène par chapitre que l'on parcourt
      à la molette ; chacune montre son image et joue son annonce.
    - s(N+1) à s(2N) : l'écoute des chapitres (actions a2 à a(N+1)), en
      pause possible ; chaque chapitre enchaîne sur le suivant, et la maison
      ramène au menu sur le chapitre en cours. Les histoires officielles n'y
      affichent aucune image : c'est le mode « écran éteint ».
    - s(2N+1) : la fin, couverture à l'écran, qui rend la main à la Telmi.

    Chaque fichier porte le nom de sa scène (sN.mp3, sN.png).
    """
    cover = "s0.png" if has_cover else None
    stages: dict[str, dict] = {
        "s0": {
            "image": cover,
            "audio": "s0.mp3",
            "ok": {"action": "a1", "index": 0},
            "home": None,
            "control": {"wheel": False, "ok": True, "home": True,
                        "pause": False, "autoplay": True},
        },
    }
    actions: dict[str, list] = {
        "a0": [{"stage": "s0"}],
        "a1": [{"stage": f"s{i}"} for i in range(1, count + 1)],
    }
    end_action = f"a{count + 2}"

    for number in range(1, count + 1):
        play = count + number
        stages[f"s{number}"] = {
            "image": f"s{number}.png",
            "audio": f"s{number}.mp3",
            "ok": {"action": f"a{number + 1}", "index": 0},
            "home": {"action": "a0", "index": 0},
            "control": {"wheel": True, "ok": True, "home": True,
                        "pause": False, "autoplay": False},
        }
        next_action = f"a{number + 2}" if number < count else end_action
        stages[f"s{play}"] = {
            "image": f"s{play}.png" if show_image else None,
            "audio": f"s{play}.mp3",
            "ok": {"action": next_action, "index": 0},
            "home": {"action": "a1", "index": number - 1},
            "control": {"wheel": False, "ok": False, "home": True,
                        "pause": True, "autoplay": True},
        }
        actions[f"a{number + 1}"] = [{"stage": f"s{play}"}]

    end_stage = f"s{2 * count + 1}"
    stages[end_stage] = {
        "image": cover,
        "audio": f"{end_stage}.mp3",
        "ok": None,
        "home": None,
        "control": {"wheel": False, "ok": False, "home": False,
                    "pause": False, "autoplay": False},
    }
    actions[end_action] = [{"stage": end_stage}]

    return {
        "startAction": {"action": "a0", "index": 0},
        "stages": stages,
        "actions": actions,
    }


def build_notes(chapters: list[dict]) -> dict:
    """Résumé de chaque scène, affiché dans le Studio de Telmi Sync.

    Le Studio attend une entrée pour chaque scène du graphe, introduction et
    fin comprises, faute de quoi il cherche une note qui n'existe pas.
    """
    count = len(chapters)
    notes = {"s0": {"title": "Introduction", "notes": "", "color": "blue"}}
    for index, chapter in enumerate(chapters):
        number = index + 1
        text = (chapter.get("text") or "").strip()
        if len(text) > 500:
            text = text[:497].rstrip() + "..."
        title = chapter.get("title") or f"Chapitre {number}"
        color = NOTE_COLORS[index % len(NOTE_COLORS)]
        notes[f"s{number}"] = {"title": f"Menu · {title}", "notes": "", "color": color}
        notes[f"s{count + number}"] = {"title": title, "notes": text, "color": color}
    notes[f"s{2 * count + 1}"] = {"title": "Fin", "notes": "", "color": "blue"}
    return notes


def create_pack(
    chapters: list[dict], source_dir: Path, pack_dir: Path, title: str,
    age: str = "5", category: str | None = None, description: str | None = None,
    title_audio: Path | None = None, cover: Path | None = None,
    identifier: str | None = None, show_image: bool = True,
    chapter_audios: dict[int, Path] | None = None,
) -> dict:
    """Écrit le pack complet sur le disque.

    chapter_audios associe un numéro de chapitre (à partir de 0) à un audio
    qui l'annonce dans le menu ; les autres reçoivent le carillon.

    Retourne un compte rendu : chapitres sans image, et si title.mp3 est
    resté un simple silence. Lève FileNotFoundError si un audio manque.
    """
    identifier = identifier or telmi_uuid()
    chapter_audios = chapter_audios or {}
    audios_dir = pack_dir / "audios"
    images_dir = pack_dir / "images"
    audios_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    missing_images: list[int] = []
    count = len(chapters)
    chime = audios_dir / "s0.mp3"
    make_chime(chime)
    shutil.copy2(chime, audios_dir / f"s{2 * count + 1}.mp3")

    for index, chapter in enumerate(chapters):
        number = index + 1
        play = count + number
        audio_source = source_dir / chapter["file"]
        if not audio_source.is_file():
            raise FileNotFoundError(
                f"Audio manquant : {audio_source}. "
                "Lancez d'abord la découpe pour produire les MP3."
            )
        shutil.copy2(audio_source, audios_dir / f"s{play}.mp3")

        # Annonce du chapitre dans le menu : la voix enregistrée si elle
        # existe, sinon le carillon. Un fichier par scène, comme dans les
        # histoires installées.
        announced = chapter_audios.get(index)
        if announced is not None and Path(announced).is_file():
            shutil.copy2(announced, audios_dir / f"s{number}.mp3")
        else:
            shutil.copy2(chime, audios_dir / f"s{number}.mp3")

        image_name = chapter.get("image") or (Path(chapter["file"]).stem + ".png")
        image_source = source_dir / image_name
        if image_source.is_file():
            shutil.copy2(image_source, images_dir / f"s{number}.png")
            if show_image:
                shutil.copy2(image_source, images_dir / f"s{play}.png")
        else:
            missing_images.append(number)

    # Couverture fournie par l'utilisateur, sinon celle du premier chapitre.
    # Elle sert de title.png et d'image aux scènes d'introduction et de fin.
    first_image = images_dir / "s1.png"
    if cover is not None and Path(cover).is_file():
        cover_source: Path | None = Path(cover)
    elif first_image.is_file():
        cover_source = first_image
    else:
        cover_source = None
    has_cover = cover_source is not None
    if cover_source is not None:
        shutil.copy2(cover_source, pack_dir / "title.png")
        shutil.copy2(cover_source, images_dir / "s0.png")

    (pack_dir / "nodes.json").write_text(
        json.dumps(build_nodes(count, show_image, has_cover), indent=2) + "\n", encoding="utf-8"
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
    # Ces deux champs sont facultatifs, mais un lecteur qui les suppose
    # présents planterait sur leur absence : on les écrit toujours.
    metadata["category"] = category or "Mes histoires"
    metadata["description"] = description or title
    (pack_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

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
    parser.add_argument(
        "--screen-off", action="store_true",
        help="N'affiche pas l'image pendant l'écoute d'un chapitre : l'écran "
             "s'éteint et la batterie dure plus longtemps.",
    )
    args = parser.parse_args()

    # Annonces de chapitres enregistrées à la main : titres/t0.mp3, t1.mp3...
    # à côté du manifeste. Les chapitres sans annonce reçoivent un carillon.
    titres = args.manifest.parent / "titres"
    chapter_audios = {
        index: titres / f"t{index}.mp3"
        for index in range(10_000) if (titres / f"t{index}.mp3").is_file()
    } if titres.is_dir() else {}

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
            show_image=not args.screen_off, chapter_audios=chapter_audios,
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
