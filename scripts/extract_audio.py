#!/usr/bin/env python3
"""Extrait la bande son d'une vidéo vers un fichier audio (.wav par défaut).

Le format .wav est idéal pour la transcription avec Whisper.

Exemple :
    python scripts/extract_audio.py mon_film.mkv -o audio_du_film.wav
"""

import argparse
import sys
from pathlib import Path

from moviepy import VideoFileClip


def extract_audio(video_path: Path, audio_path: Path) -> None:
    with VideoFileClip(str(video_path)) as video:
        if video.audio is None:
            raise RuntimeError("Cette vidéo ne contient pas de piste audio.")
        video.audio.write_audiofile(str(audio_path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video", type=Path, help="Chemin du fichier vidéo")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Fichier audio de sortie (défaut : <nom_video>.wav)",
    )
    args = parser.parse_args()

    if not args.video.is_file():
        sys.exit(f"Erreur : fichier introuvable : {args.video}")

    audio_path = args.output or args.video.with_suffix(".wav")

    print(f"Extraction de la piste audio de {args.video.name}...")
    try:
        extract_audio(args.video, audio_path)
    except RuntimeError as e:
        sys.exit(f"Erreur : {e}")
    except Exception as e:
        sys.exit(
            f"Erreur : {e}\n"
            "Assurez-vous que le fichier vidéo est valide et que FFmpeg est installé."
        )

    print(f"Extraction terminée : {audio_path}")


if __name__ == "__main__":
    main()
