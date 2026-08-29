#!/usr/bin/env python3
"""Choisit une image illustrative par chapitre, directement dans le film.

Pour chaque chapitre, le script échantillonne plusieurs images au cœur du
chapitre et retient la plus lisible : les fondus au noir et les plans
uniformes sont écartés au profit d'une image contrastée et détaillée.
Les images sont enregistrées en PNG 640x480, le format attendu par la Telmi.

Exemple :
    python scripts/extract_chapter_images.py mon_film.mkv chapitres/chapters.json
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from ffmpeg_tools import media_duration

TARGET_SIZE = (640, 480)
# En dessous/au-dessus de ces luminosités moyennes, l'image est un fondu
DARK_LIMIT = 30.0
BRIGHT_LIMIT = 30.0


def frame_score(frame: np.ndarray) -> float:
    """Note la lisibilité d'une image : contraste élevé, ni trop sombre ni trop claire."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    detail = float(gray.std())
    # Écarte progressivement les fondus au noir et les images délavées
    darkness = min(1.0, mean / DARK_LIMIT)
    brightness = min(1.0, (255.0 - mean) / BRIGHT_LIMIT)
    return detail * darkness * brightness


def best_frame(capture: cv2.VideoCapture, start: float, end: float, samples: int):
    """Retourne la meilleure image trouvée au cœur de l'intervalle [start, end]."""
    # On reste dans les 60 % centraux : les bords d'un chapitre sont souvent
    # des transitions ou des fondus
    span_start = start + (end - start) * 0.2
    span_end = start + (end - start) * 0.8
    step = (span_end - span_start) / max(1, samples - 1) if samples > 1 else 0.0

    best_image, best_value, best_time = None, -1.0, span_start
    for index in range(samples):
        moment = span_start + index * step
        capture.set(cv2.CAP_PROP_POS_MSEC, moment * 1000)
        success, frame = capture.read()
        if not success or frame is None:
            continue
        value = frame_score(frame)
        if value > best_value:
            best_image, best_value, best_time = frame, value, moment
    return best_image, best_value, best_time


def save_png(frame: np.ndarray, destination: Path) -> None:
    """Recadre au centre en 640x480 sans déformation et enregistre en PNG."""
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    fitted = ImageOps.fit(
        image, TARGET_SIZE, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    fitted.save(destination, "PNG")


def format_time(seconds: float) -> str:
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video", type=Path, help="Fichier vidéo source")
    parser.add_argument(
        "manifest", type=Path,
        help="Fichier chapters.json produit par split_chapters.py",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Dossier de sortie des images (défaut : à côté de chapters.json)",
    )
    parser.add_argument(
        "-s", "--samples", type=int, default=9,
        help="Nombre d'images testées par chapitre (défaut : 9)",
    )
    args = parser.parse_args()

    if not args.video.is_file():
        sys.exit(f"Erreur : fichier introuvable : {args.video}")
    if not args.manifest.is_file():
        sys.exit(f"Erreur : fichier introuvable : {args.manifest}")
    if args.samples < 1:
        sys.exit("Erreur : --samples doit valoir au moins 1.")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    chapters = manifest.get("chapters", [])
    if not chapters:
        sys.exit("Erreur : aucun chapitre trouvé dans le manifeste.")

    output_dir = args.output or args.manifest.parent
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        sys.exit(f"Erreur : impossible d'ouvrir la vidéo : {args.video}")

    # Un manifeste issu d'un autre film (ou d'une autre version du montage)
    # donnerait des images sans rapport : mieux vaut le signaler tout de suite
    video_duration = media_duration(args.video)
    source_duration = manifest.get("source_duration")
    if source_duration and abs(video_duration - source_duration) > 2.0:
        print(
            f"⚠️  La vidéo dure {format_time(video_duration)} alors que le "
            f"découpage porte sur {format_time(source_duration)}.\n"
            "   Vérifiez qu'il s'agit bien du film qui a servi à produire "
            "chapters.json.\n"
        )

    print(f"Sélection d'une image pour {len(chapters)} chapitres "
          f"({args.samples} candidates testées par chapitre)...")

    written = 0
    for chapter in chapters:
        name = Path(chapter["file"]).stem + ".png"
        frame, score, moment = best_frame(
            capture, chapter["start"], chapter["end"], args.samples
        )
        if frame is None:
            reason = (
                "ce passage est au-delà de la fin de la vidéo"
                if chapter["start"] >= video_duration
                else "aucune image lisible à cet endroit"
            )
            print(f"  ⚠️  Chapitre {chapter['index'] + 1} : {reason}.")
            continue
        save_png(frame, output_dir / name)
        chapter["image"] = name
        chapter["image_time"] = round(moment, 3)
        note = "  (image peu contrastée)" if score < 12 else ""
        print(f"  ✅ {name}  — image prise à {format_time(moment)}{note}")
        written += 1

    capture.release()

    args.manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nTerminé. {written} images écrites dans '{output_dir}' "
          f"et référencées dans {args.manifest.name}.")


if __name__ == "__main__":
    main()
