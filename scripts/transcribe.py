#!/usr/bin/env python3
"""Transcrit un fichier audio en texte avec Whisper.

Produit un fichier texte brut et, en option, un fichier .srt avec les
horodatages (pratique pour retrouver les moments clés du film).

Exemple :
    python scripts/transcribe.py audio_du_film.wav -m base --srt
"""

import argparse
import sys
import time
from pathlib import Path

import whisper

MODELS = ("tiny", "base", "small", "medium", "large", "turbo")


def format_srt_time(seconds: float) -> str:
    """Formate un temps en secondes au format SRT (hh:mm:ss,mmm)."""
    millis = int(round(seconds * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def write_srt(segments, srt_path: Path) -> None:
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            start = format_srt_time(segment["start"])
            end = format_srt_time(segment["end"])
            f.write(f"{i}\n{start} --> {end}\n{segment['text'].strip()}\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio", type=Path, help="Chemin du fichier audio")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Fichier texte de sortie (défaut : <nom_audio>.txt)",
    )
    parser.add_argument(
        "-m", "--model", choices=MODELS, default="base",
        help="Taille du modèle Whisper : 'base' est un bon compromis "
             "vitesse/précision, 'medium' et 'large' sont plus lents mais "
             "bien meilleurs (défaut : base)",
    )
    parser.add_argument(
        "-l", "--language", default="fr",
        help="Langue de l'audio (défaut : fr). Passer '' pour la détection automatique.",
    )
    parser.add_argument(
        "--srt", action="store_true",
        help="Génère aussi un fichier .srt avec les horodatages",
    )
    args = parser.parse_args()

    if not args.audio.is_file():
        sys.exit(f"Erreur : fichier introuvable : {args.audio}")

    text_path = args.output or args.audio.with_suffix(".txt")

    print(f"Chargement du modèle Whisper ({args.model})...")
    model = whisper.load_model(args.model)

    print(f"Transcription de {args.audio.name} (cela peut prendre du temps)...")
    start_time = time.time()
    try:
        result = model.transcribe(
            str(args.audio), language=args.language or None, fp16=False
        )
    except Exception as e:
        sys.exit(
            f"Erreur : {e}\n"
            "Assurez-vous que FFmpeg est installé et que le fichier audio est valide."
        )
    print(f"Transcription terminée en {time.time() - start_time:.0f} secondes.")

    with open(text_path, "w", encoding="utf-8") as f:
        f.write(result["text"].strip() + "\n")
    print(f"Texte sauvegardé : {text_path}")

    if args.srt:
        srt_path = text_path.with_suffix(".srt")
        write_srt(result["segments"], srt_path)
        print(f"Sous-titres horodatés sauvegardés : {srt_path}")


if __name__ == "__main__":
    main()
