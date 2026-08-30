#!/usr/bin/env python3
"""Extrait une image de la vidéo toutes les X secondes (planche contact).

Utilise un positionnement direct dans la vidéo (seek) au lieu de lire
toutes les images une par une : beaucoup plus rapide sur un film complet.

Exemple :
    python scripts/extract_images.py mon_film.mkv -o captures -i 8
"""

import argparse
import sys
from pathlib import Path

import cv2


def format_timestamp(seconds: float) -> str:
    """Formate un temps en secondes en 'hh-mm-ss' (compatible tri alphabétique)."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}-{minutes:02d}-{secs:02d}"


def extract_images(video_path: Path, output_dir: Path, interval: float) -> int:
    vidcap = cv2.VideoCapture(str(video_path))
    if not vidcap.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir la vidéo : {video_path}")

    fps = vidcap.get(cv2.CAP_PROP_FPS)
    frame_count = vidcap.get(cv2.CAP_PROP_FRAME_COUNT)
    if fps <= 0 or frame_count <= 0:
        vidcap.release()
        raise RuntimeError(
            "Métadonnées vidéo illisibles (FPS ou nombre d'images invalide). "
            "Le fichier est peut-être corrompu ou dans un format non supporté."
        )

    duration = frame_count / fps
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Vidéo : {video_path.name} — durée {format_timestamp(duration)}, {fps:.2f} fps")
    print(f"Capture d'une image toutes les {interval} secondes...")

    count = 0
    time_sec = 0.0
    while time_sec < duration:
        # Se positionne directement au bon moment plutôt que de décoder chaque image
        vidcap.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000)
        success, image = vidcap.read()
        if not success:
            break

        filename = f"capture_{format_timestamp(time_sec)}.jpg"
        cv2.imwrite(str(output_dir / filename), image)
        count += 1
        if count % 25 == 0:
            print(f"  {count} images extraites (position : {format_timestamp(time_sec)})")
        time_sec += interval

    vidcap.release()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video", type=Path, help="Chemin du fichier vidéo")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("captures"),
        help="Dossier de sortie des images (défaut : captures)",
    )
    parser.add_argument(
        "-i", "--interval", type=float, default=8.0,
        help="Intervalle entre deux captures, en secondes (défaut : 8)",
    )
    args = parser.parse_args()

    if not args.video.is_file():
        sys.exit(f"Erreur : fichier introuvable : {args.video}")
    if args.interval <= 0:
        sys.exit("Erreur : l'intervalle doit être strictement positif.")

    try:
        count = extract_images(args.video, args.output, args.interval)
    except RuntimeError as e:
        sys.exit(f"Erreur : {e}")

    print(f"Terminé. {count} images extraites dans '{args.output}'.")


if __name__ == "__main__":
    main()
