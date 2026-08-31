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
# En dessous de ce score, l'image est plate : on le signale à l'utilisateur
LOW_DETAIL_SCORE = 12.0
# Taille des vignettes de proposition : même cadrage que l'image finale,
# pour que ce que l'on choisit soit exactement ce que l'on obtient
THUMB_SIZE = (320, 240)
CANDIDATES_DIR = "propositions"


def format_time(seconds: float) -> str:
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


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
    destination.parent.mkdir(parents=True, exist_ok=True)
    fit_image(frame, TARGET_SIZE).save(destination, "PNG")


def fit_image(frame: np.ndarray, size) -> Image.Image:
    """Recadre au centre à la taille demandée, sans déformation."""
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    return ImageOps.fit(
        image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )


def propose_candidates(
    video: Path, chapters: list[dict], output_dir: Path,
    per_chapter: int = 12, on_progress=None,
) -> dict:
    """Extrait plusieurs images par chapitre et les propose au choix.

    Les vignettes couvrent tout le chapitre, bords exclus, et la mieux notée
    est pré-sélectionnée : il ne reste qu'à corriger là où l'on n'est pas
    d'accord avec la machine.
    """
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir la vidéo : {video}")

    dossier = output_dir / CANDIDATES_DIR
    dossier.mkdir(parents=True, exist_ok=True)
    total = 0

    for position, chapter in enumerate(chapters):
        debut, fin = chapter["start"], chapter["end"]
        # On evite les tout premiers et derniers instants : souvent des
        # transitions ou des fondus
        span_debut = debut + (fin - debut) * 0.05
        span_fin = debut + (fin - debut) * 0.95
        pas = (span_fin - span_debut) / max(1, per_chapter - 1)

        propositions = []
        for index in range(per_chapter):
            moment = span_debut + index * pas
            capture.set(cv2.CAP_PROP_POS_MSEC, moment * 1000)
            success, frame = capture.read()
            if not success or frame is None:
                continue
            nom = f"{CANDIDATES_DIR}/ch{position + 1:02d}_{index + 1:02d}.jpg"
            fit_image(frame, THUMB_SIZE).save(
                output_dir / nom, "JPEG", quality=82
            )
            propositions.append({
                "time": round(moment, 3),
                "file": nom,
                "score": round(frame_score(frame), 1),
                "label": format_time(moment),
            })
            total += 1

        chapter["candidates"] = propositions
        if propositions:
            meilleure = max(propositions, key=lambda c: c["score"])
            chapter["chosen_time"] = meilleure["time"]
        if on_progress:
            on_progress(position + 1, len(chapters))

    capture.release()
    return {"written": total, "chapters": len(chapters)}


def generate_images(
    video: Path, chapters: list[dict], output_dir: Path, samples: int = 9,
    source_duration: float | None = None, on_progress=None,
) -> dict:
    """Écrit une image par chapitre et complète chaque chapitre avec son nom.

    Retourne un compte rendu : nombre d'images écrites, avertissements, et
    éventuel décalage entre la vidéo et le découpage.
    """
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir la vidéo : {video}")

    video_duration = media_duration(video)
    mismatch = None
    if source_duration and abs(video_duration - source_duration) > 2.0:
        mismatch = (
            f"La vidéo dure {format_time(video_duration)} alors que le découpage "
            f"porte sur {format_time(source_duration)}. Vérifiez qu'il s'agit "
            "bien du film qui a servi à produire le découpage."
        )

    written, warnings, details = 0, [], []
    for position, chapter in enumerate(chapters):
        name = Path(chapter["file"]).stem + ".png"
        choisi = chapter.get("chosen_time")
        if choisi is not None:
            # Image retenue a la main : on la reprend telle quelle, en pleine
            # qualite cette fois
            capture.set(cv2.CAP_PROP_POS_MSEC, float(choisi) * 1000)
            success, frame = capture.read()
            frame = frame if success else None
            score, moment = (frame_score(frame) if frame is not None else 0.0), float(choisi)
        else:
            frame, score, moment = best_frame(
                capture, chapter["start"], chapter["end"], samples
            )
        if frame is None:
            reason = (
                "ce passage est au-delà de la fin de la vidéo"
                if chapter["start"] >= video_duration
                else "aucune image lisible à cet endroit"
            )
            warnings.append(f"Chapitre {position + 1} : {reason}.")
            chapter.pop("image", None)
        else:
            save_png(frame, output_dir / name)
            chapter["image"] = name
            chapter["image_time"] = round(moment, 3)
            written += 1
            details.append({
                "index": position,
                "name": name,
                "time": round(moment, 3),
                "low_detail": score < LOW_DETAIL_SCORE,
            })
        if on_progress:
            on_progress(position + 1, len(chapters))

    capture.release()
    return {
        "written": written,
        "warnings": warnings,
        "mismatch": mismatch,
        "details": details,
    }


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
    print(f"Sélection d'une image pour {len(chapters)} chapitres "
          f"({args.samples} candidates testées par chapitre)...")
    try:
        report = generate_images(
            args.video, chapters, output_dir, args.samples,
            manifest.get("source_duration"),
        )
    except RuntimeError as e:
        sys.exit(f"Erreur : {e}")

    if report["mismatch"]:
        print(f"⚠️  {report['mismatch']}\n")
    for detail in report["details"]:
        note = "  (image peu contrastée)" if detail["low_detail"] else ""
        print(f"  ✅ {detail['name']}  — image prise à "
              f"{format_time(detail['time'])}{note}")
    for warning in report["warnings"]:
        print(f"  ⚠️  {warning}")

    args.manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nTerminé. {report['written']} images écrites dans '{output_dir}' "
          f"et référencées dans {args.manifest.name}.")


if __name__ == "__main__":
    main()
