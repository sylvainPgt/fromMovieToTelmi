#!/usr/bin/env python3
"""Découpe intelligemment la bande son d'un film en chapitres.

Au lieu de couper toutes les N minutes au hasard, le script repère les
silences du film et choisit la meilleure combinaison de points de coupe :
des chapitres proches de la durée souhaitée, qui tombent sur de vraies
respirations et jamais au milieu d'une réplique.

Exemples :
    # Aperçu du découpage sans rien encoder (rapide, pour régler les réglages)
    python scripts/split_chapters.py audio_du_film.wav --preview

    # Découpe en chapitres d'environ 5 minutes, en s'aidant de la transcription
    python scripts/split_chapters.py audio_du_film.wav -d 300 --srt audio_du_film.srt
"""

import argparse
import bisect
import json
import math
import sys
from pathlib import Path

from ffmpeg_tools import detect_silences, extract_audio_segment, media_duration
from subtitles import parse_srt, text_between

# Un silence de cette durée (en secondes) est considéré comme une coupure idéale
FULL_STRENGTH_SILENCE = 3.0
# Deux points de coupe plus proches que cela sont fusionnés
MERGE_DISTANCE = 1.0


def format_time(seconds: float) -> str:
    """Formate un temps en h:mm:ss."""
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def build_candidates(
    duration: float,
    silences: list[tuple[float, float]],
    speech: list[tuple[float, float, str]],
    grid_step: float,
) -> list[tuple[float, float]]:
    """Construit la liste des points de coupe possibles, avec leur qualité.

    La qualité vaut 1.0 pour un long silence, 0.0 pour un point de repli
    régulier, et devient négative si le point tombe au milieu d'une réplique.
    """
    candidates: dict[float, float] = {}

    for start, end in silences:
        middle = (start + end) / 2
        if 0 < middle < duration:
            strength = min(1.0, (end - start) / FULL_STRENGTH_SILENCE)
            candidates[middle] = max(candidates.get(middle, 0.0), strength)

    # Points de repli réguliers : ils garantissent qu'un découpage reste
    # toujours possible, même sur un passage musical sans aucun silence.
    steps = int(duration / grid_step)
    for i in range(1, steps + 1):
        moment = i * grid_step
        if moment < duration and not any(
            abs(moment - existing) < MERGE_DISTANCE for existing in candidates
        ):
            candidates.setdefault(moment, 0.0)

    # Pénalise fortement une coupe qui tomberait au milieu d'une phrase
    if speech:
        speech_starts = [seg[0] for seg in speech]
        for moment in list(candidates):
            index = bisect.bisect_right(speech_starts, moment) - 1
            if index >= 0 and speech[index][1] > moment:
                candidates[moment] = -1.0

    merged: list[tuple[float, float]] = []
    for moment in sorted(candidates):
        if merged and moment - merged[-1][0] < MERGE_DISTANCE:
            # Garde le meilleur des deux points trop proches
            if candidates[moment] > merged[-1][1]:
                merged[-1] = (moment, candidates[moment])
        else:
            merged.append((moment, candidates[moment]))
    return merged


def choose_cuts(
    duration: float,
    candidates: list[tuple[float, float]],
    target: float,
    min_length: float,
    max_length: float,
    boundary_weight: float,
) -> list[tuple[float, float]]:
    """Choisit les points de coupe par programmation dynamique.

    Minimise l'écart des chapitres à la durée cible tout en favorisant les
    coupes qui tombent sur un vrai silence. Retourne la liste des points
    retenus sous forme de (instant, qualité), début et fin inclus.
    """
    points = [(0.0, 0.0), *candidates, (duration, 0.0)]
    times = [point[0] for point in points]
    last = len(points) - 1

    best = [math.inf] * len(points)
    previous = [-1] * len(points)
    best[0] = 0.0

    for i in range(1, len(points)):
        # Seuls les points situés à une distance autorisée peuvent précéder i
        lowest = bisect.bisect_left(times, times[i] - max_length)
        highest = bisect.bisect_right(times, times[i] - min_length) - 1
        for j in range(lowest, highest + 1):
            if best[j] == math.inf:
                continue
            deviation = (times[i] - times[j] - target) / target
            score = best[j] + deviation * deviation
            if score < best[i]:
                best[i], previous[i] = score, j
        # Pénalise une coupe mal placée : nulle sur un silence franc, maximale
        # sur un point arbitraire ou au milieu d'une réplique. Formulée en
        # pénalité (et non en bonus) pour que multiplier les chapitres bancals
        # coûte plus cher que de s'écarter un peu de la durée visée.
        if best[i] != math.inf and i != last:
            best[i] += boundary_weight * (1.0 - points[i][1])

    if best[last] == math.inf:
        return []

    chosen: list[tuple[float, float]] = []
    node = last
    while node != -1:
        chosen.append(points[node])
        node = previous[node]
    chosen.reverse()
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio", type=Path, help="Fichier audio (ou vidéo) à découper")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("chapitres"),
        help="Dossier de sortie des chapitres (défaut : chapitres)",
    )
    parser.add_argument(
        "-d", "--duration", type=float, default=300.0,
        help="Durée visée pour un chapitre, en secondes (défaut : 300, soit 5 min)",
    )
    parser.add_argument(
        "-n", "--chapters", type=int, default=None,
        help="Nombre de chapitres souhaité (approximatif). Remplace --duration.",
    )
    parser.add_argument(
        "--tolerance", type=float, default=0.5,
        help="Écart toléré autour de la durée visée, de 0 à 1 (défaut : 0.5, "
             "soit des chapitres entre 50%% et 150%% de la cible)",
    )
    parser.add_argument(
        "--srt", type=Path, default=None,
        help="Fichier .srt de la transcription : évite de couper au milieu "
             "d'une réplique et remplit le texte de chaque chapitre",
    )
    parser.add_argument(
        "--noise", type=float, default=-30.0,
        help="Seuil de silence en dB (défaut : -30). Baissez-le (ex. -40) si "
             "le film est bruyant et qu'aucun silence n'est trouvé.",
    )
    parser.add_argument(
        "--min-silence", type=float, default=0.6,
        help="Durée minimale d'un silence pour être un point de coupe (défaut : 0.6 s)",
    )
    parser.add_argument(
        "--boundary-weight", type=float, default=0.25,
        help="Prix payé pour une coupe mal placée, face au respect de la durée "
             "cible (défaut : 0.25). Augmentez-le pour privilégier les beaux "
             "silences quitte à avoir des chapitres inégaux.",
    )
    parser.add_argument(
        "--bitrate", default="128k",
        help="Débit MP3, entre 64k et 192k pour la Telmi (défaut : 128k)",
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Affiche le découpage proposé sans encoder les fichiers audio",
    )
    args = parser.parse_args()

    if not args.audio.is_file():
        sys.exit(f"Erreur : fichier introuvable : {args.audio}")
    if not 0 < args.tolerance <= 1:
        sys.exit("Erreur : --tolerance doit être compris entre 0 (exclu) et 1.")

    if args.chapters is not None and args.chapters < 1:
        sys.exit("Erreur : --chapters doit valoir au moins 1.")

    duration = media_duration(args.audio)
    target = duration / args.chapters if args.chapters else args.duration
    if target <= 0:
        sys.exit("Erreur : la durée visée doit être strictement positive.")
    if duration <= target:
        sys.exit(
            f"Erreur : l'audio ne dure que {format_time(duration)}, "
            f"soit moins que la durée d'un chapitre ({format_time(target)}). "
            "Réduisez --duration ou augmentez --chapters."
        )

    print(f"Audio : {args.audio.name} — durée {format_time(duration)}")
    print(f"Objectif : des chapitres d'environ {format_time(target)}")

    speech = parse_srt(args.srt) if args.srt else []
    if args.srt:
        if not args.srt.is_file():
            sys.exit(f"Erreur : fichier introuvable : {args.srt}")
        print(f"Transcription : {len(speech)} répliques lues dans {args.srt.name}")

    print("Analyse des silences (cela peut prendre une minute)...")
    silences = detect_silences(args.audio, args.noise, args.min_silence)
    print(f"  {len(silences)} silences détectés.")
    if not silences:
        print("  Aucun silence trouvé : essayez un seuil plus permissif, "
              "par exemple --noise -40 ou --min-silence 0.4.")

    candidates = build_candidates(
        duration, silences, speech,
        # Assez serré pour toujours offrir un repli, assez large pour que deux
        # points de repli ne se confondent pas
        grid_step=max(target / 4, 2 * MERGE_DISTANCE),
    )
    cuts = choose_cuts(
        duration, candidates, target,
        min_length=target * (1 - args.tolerance),
        max_length=target * (1 + args.tolerance),
        boundary_weight=args.boundary_weight,
    )
    if not cuts:
        sys.exit(
            "Erreur : aucun découpage possible avec ces réglages. "
            "Augmentez --tolerance ou changez la durée visée."
        )

    chapters = []
    for index in range(len(cuts) - 1):
        start, quality = cuts[index]
        end = cuts[index + 1][0]
        chapters.append({
            "index": index,
            "file": f"chapitre_{index + 1:02d}.mp3",
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            # Qualité de la coupe qui ouvre ce chapitre (le chapitre 1 démarre
            # au début du film, donc toujours parfaitement placé)
            "cut_quality": round(quality, 3) if index > 0 else 1.0,
            "text": text_between(speech, start, end) if speech else "",
        })

    print(f"\n{len(chapters)} chapitres proposés :\n")
    print(f"  {'#':>3}  {'Début':>8}  {'Fin':>8}  {'Durée':>7}  Coupe")
    weak = 0
    for chapter in chapters:
        quality = chapter["cut_quality"]
        if quality >= 0.6:
            label = "franche"
        elif quality > 0.0:
            label = "correcte"
        elif quality == 0.0:
            label = "arbitraire"
        else:
            label = "sur une réplique !"
        if quality <= 0.0:
            weak += 1
        print(f"  {chapter['index'] + 1:>3}  {format_time(chapter['start']):>8}  "
              f"{format_time(chapter['end']):>8}  "
              f"{format_time(chapter['duration']):>7}  {label}")

    if weak:
        print(f"\n  {weak} coupe(s) sans silence franc. Pour améliorer : "
              "essayez --noise -40, --min-silence 0.4 ou --tolerance 0.7.")

    manifest = {
        "source": str(args.audio),
        "source_duration": round(duration, 3),
        "target_duration": round(target, 3),
        "chapters": chapters,
    }

    if args.preview:
        print("\nMode aperçu : aucun fichier audio encodé.")
        print("Relancez sans --preview pour produire les MP3.")
        return

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"\nEncodage des chapitres dans '{args.output}'...")
    for chapter in chapters:
        destination = args.output / chapter["file"]
        extract_audio_segment(
            args.audio, destination,
            chapter["start"], chapter["duration"], bitrate=args.bitrate,
        )
        print(f"  ✅ {chapter['file']}  ({format_time(chapter['duration'])})")

    manifest_path = args.output / "chapters.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nTerminé. {len(chapters)} chapitres et {manifest_path.name} "
          f"écrits dans '{args.output}'.")


if __name__ == "__main__":
    main()
