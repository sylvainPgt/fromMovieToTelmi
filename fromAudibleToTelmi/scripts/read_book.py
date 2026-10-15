#!/usr/bin/env python3
"""Lit un livre audio produit par Libation : audio, chapitres, couverture.

Libation range chaque livre dans un dossier « Titre [ASIN] ». Selon ses
réglages, on y trouve :

- un seul fichier (.m4b ou .mp3) dont les chapitres sont inscrits dans
  les métadonnées : c'est le cas par défaut ;
- un fichier par chapitre, si l'option de découpage par chapitre est
  cochée dans Libation ;
- parfois un fichier .cue qui décrit les chapitres, et une image de
  couverture.

Ce module accepte le dossier ou directement le fichier audio, et rend
toujours la même chose : un fichier audio unique à découper, la liste des
chapitres du livre avec leurs titres, et la couverture si elle existe.

Les fichiers .aax d'Audible sont encore protégés : il faut d'abord les
libérer avec Libation, ce module ne les lit pas.

Exemple :
    python scripts/read_book.py "Libation/Books/Les Légendaires [B0GF8HJ7HM]"
"""

import argparse
import re
import sys
from pathlib import Path

from ffmpeg_tools import media_duration, run_ffmpeg

AUDIO_EXTENSIONS = {".m4b", ".m4a", ".mp3", ".aac", ".flac", ".ogg", ".opus", ".wav"}
# Fichiers Audible encore protégés : Libation doit d'abord les convertir
PROTECTED_EXTENSIONS = {".aax", ".aaxc"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

PROTECTED_MESSAGE = (
    "Ce fichier .aax est encore protégé par Audible. Ouvrez Libation, "
    "« libérez » le livre, puis choisissez le dossier qu'il produit "
    "(celui qui porte le titre du livre et son identifiant entre crochets)."
)


def natural_key(path: Path) -> list:
    """Trie « Chapitre 2 » avant « Chapitre 10 »."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", path.name)]


def read_ffmetadata(audio: Path, scratch: Path) -> tuple[dict, list[dict]]:
    """Lit les étiquettes et les chapitres inscrits dans un fichier audio.

    FFmpeg sait écrire toutes les métadonnées d'un fichier dans un format
    texte simple (ffmetadata) : un bloc d'étiquettes générales, puis un bloc
    [CHAPTER] par chapitre avec sa base de temps, son début et sa fin.
    """
    scratch.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-y", "-i", str(audio), "-f", "ffmetadata", str(scratch)])
    if not scratch.is_file():
        return {}, []
    text = scratch.read_text(encoding="utf-8", errors="replace")
    scratch.unlink(missing_ok=True)

    tags: dict[str, str] = {}
    chapters: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("["):
            current = {} if line.upper() == "[CHAPTER]" else None
            if current is not None:
                chapters.append(current)
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        # ffmetadata échappe = ; # \ et les retours à la ligne par un antislash
        value = re.sub(r"\\(.)", r"\1", value)
        target = current if current is not None else tags
        target[key.strip().lower()] = value.strip()

    result = []
    for number, chapter in enumerate(chapters, start=1):
        try:
            num, den = chapter.get("timebase", "1/1000").split("/")
            base = int(num) / int(den)
            start = int(chapter["start"]) * base
            end = int(chapter["end"]) * base
        except (KeyError, ValueError, ZeroDivisionError):
            continue
        if end > start:
            result.append({
                "title": chapter.get("title") or f"Chapitre {number}",
                "start": round(start, 3),
                "end": round(end, 3),
            })
    return tags, result


def parse_cue(cue: Path, duration: float) -> list[dict]:
    """Lit les chapitres d'un fichier .cue (pistes et index « mm:ss:ff »)."""
    text = cue.read_text(encoding="utf-8-sig", errors="replace")
    tracks: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.upper().startswith("TRACK"):
            tracks.append({"title": None, "start": None})
        elif tracks and line.upper().startswith("TITLE"):
            tracks[-1]["title"] = line[5:].strip().strip('"')
        elif tracks and line.upper().startswith("INDEX 01"):
            minutes, seconds, frames = line.split()[-1].split(":")
            # 75 trames par seconde dans la norme des .cue
            tracks[-1]["start"] = int(minutes) * 60 + int(seconds) + int(frames) / 75
    tracks = [t for t in tracks if t["start"] is not None]
    chapters = []
    for index, track in enumerate(tracks):
        end = tracks[index + 1]["start"] if index + 1 < len(tracks) else duration
        if end > track["start"]:
            chapters.append({
                "title": track["title"] or f"Chapitre {index + 1}",
                "start": round(track["start"], 3),
                "end": round(end, 3),
            })
    return chapters


def file_title(audio: Path, book_stem: str | None) -> str:
    """Titre d'un chapitre livré en fichier séparé, tiré de son nom.

    Libation nomme ces fichiers « Titre [ASIN] - 0003 - Titre du chapitre » :
    on retire le titre du livre et le numéro pour ne garder que la fin.
    """
    name = audio.stem
    if book_stem and name.startswith(book_stem):
        name = name[len(book_stem):]
    name = re.sub(r"\[[A-Z0-9]{10}\]", "", name)
    name = re.sub(r"^[\s\-_.]*\d+[\s\-_.]+", "", name.strip(" -_."))
    return name.strip(" -_.") or audio.stem


def extract_cover(audio: Path, destination: Path) -> bool:
    """Extrait la couverture incrustée dans le fichier audio, s'il y en a une."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-y", "-i", str(audio), "-an", "-map", "0:v:0", "-frames:v", "1",
        str(destination),
    ])
    return destination.is_file() and destination.stat().st_size > 0


def concat_files(files: list[Path], destination: Path) -> None:
    """Met bout à bout les fichiers d'un livre découpé, sans réencoder.

    Le conteneur Matroska accepte tous les formats audio : la copie brute
    prend quelques secondes même pour un livre de plusieurs heures.
    """
    listing = destination.with_suffix(".txt")
    lines = []
    for file in files:
        escaped = str(file.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stderr = run_ffmpeg([
        "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-vn", "-c", "copy", str(destination),
    ])
    listing.unlink(missing_ok=True)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"Assemblage des fichiers impossible :\n{stderr[-800:]}")


def locate(path: Path) -> tuple[Path, list[Path], Path | None, Path | None]:
    """Trouve, dans un dossier ou à partir d'un fichier, les éléments du livre.

    Retourne le dossier, les fichiers audio, le .cue et l'image éventuels.
    """
    path = Path(path).expanduser()
    if not path.exists():
        raise RuntimeError(f"Introuvable : {path}")
    if path.is_file():
        if path.suffix.lower() in PROTECTED_EXTENSIONS:
            raise RuntimeError(PROTECTED_MESSAGE)
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise RuntimeError(f"Ce fichier n'est pas un livre audio reconnu : {path.name}")
        folder, files = path.parent, [path]
    else:
        folder = path
        files = sorted(
            (p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS),
            key=natural_key,
        )
        if not files:
            if any(p.suffix.lower() in PROTECTED_EXTENSIONS for p in folder.iterdir()):
                raise RuntimeError(PROTECTED_MESSAGE)
            raise RuntimeError(f"Aucun fichier audio dans {folder.name}.")

    cues = sorted(folder.glob("*.cue"))
    cue = None
    if len(files) == 1:
        same = files[0].with_suffix(".cue")
        cue = same if same.is_file() else (cues[0] if len(cues) == 1 else None)

    images = sorted(
        (p for p in folder.iterdir()
         if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda p: (0 if "cover" in p.name.lower() or "couverture" in p.name.lower()
                       else 1, -p.stat().st_size),
    )
    return folder, files, cue, (images[0] if images else None)


def load_book(path: Path, workdir: Path) -> dict:
    """Rassemble tout ce qu'il faut savoir d'un livre pour le découper.

    workdir reçoit les fichiers intermédiaires : la couverture extraite et,
    pour un livre en plusieurs fichiers, l'audio assemblé.
    """
    folder, files, cue, image = locate(path)
    workdir.mkdir(parents=True, exist_ok=True)

    tags, chapters = read_ffmetadata(files[0], workdir / "metadata.txt")
    if len(files) > 1:
        # Un fichier par chapitre : on les assemble, et chaque fichier
        # devient un chapitre du livre
        audio = workdir / "livre_complet.mka"
        concat_files(files, audio)
        book_stem = re.split(r"\s+-\s+\d", files[0].stem)[0]
        chapters, position = [], 0.0
        for file in files:
            length = media_duration(file)
            chapters.append({
                "title": file_title(file, book_stem),
                "start": round(position, 3),
                "end": round(position + length, 3),
            })
            position += length
        source_kind = f"{len(files)} fichiers, un par chapitre"
    else:
        audio = files[0]
        source_kind = "chapitres inscrits dans le fichier"

    duration = media_duration(audio)
    if not chapters and cue is not None:
        chapters = parse_cue(cue, duration)
        source_kind = f"chapitres lus dans {cue.name}"
    if not chapters:
        source_kind = "aucun chapitre trouvé : découpage sur les silences"

    # Le dernier chapitre déclaré s'arrête parfois un peu avant la vraie fin
    if chapters:
        chapters[-1]["end"] = round(max(chapters[-1]["end"], duration), 3)
        chapters = [c for c in chapters if c["start"] < duration]

    cover = None
    embedded = workdir / "couverture_livre.png"
    if image is not None:
        cover = image
    elif extract_cover(files[0], embedded):
        cover = embedded

    title = tags.get("album") or tags.get("title") or re.sub(
        r"\s*\[[A-Z0-9]{10}\]\s*$", "", folder.name if len(files) > 1 else files[0].stem
    )
    return {
        "audio": audio,
        "files": files,
        "folder": folder,
        "duration": duration,
        "title": title.strip(),
        "author": tags.get("artist") or tags.get("album_artist") or "",
        "narrator": tags.get("composer") or "",
        "description": tags.get("comment") or tags.get("description") or "",
        "chapters": chapters,
        "cover": cover,
        "source_kind": source_kind,
    }


def format_time(seconds: float) -> str:
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("book", type=Path, help="Dossier Libation du livre, ou son fichier audio")
    parser.add_argument(
        "-w", "--workdir", type=Path, default=None,
        help="Dossier des fichiers intermédiaires (défaut : <livre>_telmi à côté)",
    )
    args = parser.parse_args()
    target = args.book.expanduser()
    workdir = args.workdir or target.parent / f"{target.stem}_telmi"
    try:
        book = load_book(target, workdir)
    except RuntimeError as error:
        sys.exit(f"Erreur : {error}")

    print(f"Livre : {book['title']}")
    if book["author"]:
        print(f"Auteur : {book['author']}")
    print(f"Durée : {format_time(book['duration'])} — {book['source_kind']}")
    print(f"Couverture : {book['cover'] or 'aucune'}")
    print(f"\n{len(book['chapters'])} chapitres :")
    for number, chapter in enumerate(book["chapters"], start=1):
        print(f"  {number:>3}  {format_time(chapter['start']):>8}  "
              f"{format_time(chapter['end'] - chapter['start']):>8}  {chapter['title']}")


if __name__ == "__main__":
    main()
