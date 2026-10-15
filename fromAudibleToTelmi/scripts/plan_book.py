#!/usr/bin/env python3
"""Répartit un livre audio en chapitres Telmi.

Un livre Audible arrive déjà découpé, mais ses chapitres ne conviennent pas
toujours à la Telmi : certains durent quarante secondes (« Crédits
d'ouverture »), d'autres trois quarts d'heure. Deux façons de faire :

- « livre » : un chapitre Telmi par chapitre du livre, tel quel ;
- « durée » : des chapitres Telmi proches d'une durée choisie. Les fins de
  chapitre du livre sont les coupes idéales ; quand il faut couper à
  l'intérieur d'un chapitre trop long, on se rabat sur un silence, puis en
  dernier recours sur un point arbitraire.

Le choix des coupes est fait par programmation dynamique, comme dans
Story Maker from Movie : on minimise l'écart à la durée visée en payant un
prix pour chaque coupe mal placée.

Exemple :
    python scripts/plan_book.py "Libation/Books/Mon livre [B0XXXXXXXX]" -d 600
    python scripts/plan_book.py "Libation/Books/Mon livre [B0XXXXXXXX]" --mode livre -o chapitres
"""

import argparse
import bisect
import json
import math
import sys
from pathlib import Path

from ffmpeg_tools import detect_silences, extract_audio_segment
from read_book import format_time, load_book

# Un silence de cette durée (en secondes) est presque aussi bon qu'une fin de chapitre
FULL_STRENGTH_SILENCE = 3.0
# Un silence, même long, vaut toujours un peu moins qu'une vraie fin de chapitre
SILENCE_CEILING = 0.8
# Deux points de coupe plus proches que cela sont fusionnés
MERGE_DISTANCE = 1.0
# Au-delà de cette durée, un chapitre du livre mérite qu'on cherche ses silences
LONG_CHAPTER = 15 * 60


def cut_label(quality: float) -> str:
    """Décrit en quelques mots où tombe une coupe, d'après sa qualité."""
    if quality >= 1.0:
        return "fin de chapitre"
    if quality > 0.0:
        return "silence"
    return "arbitraire"


def needs_silences(chapters: list[dict]) -> bool:
    """Faut-il chercher les silences ? Oui s'il manque de quoi bien couper."""
    return not chapters or any(c["end"] - c["start"] > LONG_CHAPTER for c in chapters)


def build_candidates(
    duration: float, boundaries: list[float],
    silences: list[tuple[float, float]], grid_step: float,
) -> list[tuple[float, float]]:
    """Points de coupe possibles, avec leur qualité (1.0 = fin de chapitre)."""
    candidates: dict[float, float] = {}
    for moment in boundaries:
        if 0 < moment < duration:
            candidates[moment] = 1.0

    for start, end in silences:
        middle = (start + end) / 2
        if 0 < middle < duration and not any(
            abs(middle - b) < MERGE_DISTANCE for b in boundaries
        ):
            strength = SILENCE_CEILING * min(1.0, (end - start) / FULL_STRENGTH_SILENCE)
            candidates[middle] = max(candidates.get(middle, 0.0), strength)

    # Points de repli réguliers : un découpage reste toujours possible
    for i in range(1, int(duration / grid_step) + 1):
        moment = i * grid_step
        if moment < duration and not any(
            abs(moment - existing) < MERGE_DISTANCE for existing in candidates
        ):
            candidates.setdefault(moment, 0.0)

    merged: list[tuple[float, float]] = []
    for moment in sorted(candidates):
        if merged and moment - merged[-1][0] < MERGE_DISTANCE:
            if candidates[moment] > merged[-1][1]:
                merged[-1] = (moment, candidates[moment])
        else:
            merged.append((moment, candidates[moment]))
    return merged


def choose_cuts(
    duration: float, candidates: list[tuple[float, float]], target: float,
    min_length: float, max_length: float, boundary_weight: float,
) -> list[tuple[float, float]]:
    """Choisit les coupes : chapitres proches de la cible, coupes bien placées."""
    points = [(0.0, 1.0), *candidates, (duration, 1.0)]
    times = [point[0] for point in points]
    last = len(points) - 1
    best = [math.inf] * len(points)
    previous = [-1] * len(points)
    best[0] = 0.0

    for i in range(1, len(points)):
        lowest = bisect.bisect_left(times, times[i] - max_length)
        highest = bisect.bisect_right(times, times[i] - min_length) - 1
        # Le dernier chapitre peut être plus court : la fin du livre est une
        # coupe parfaite, inutile de la refuser pour quelques minutes
        if i == last:
            highest = i - 1
        for j in range(lowest, highest + 1):
            if best[j] == math.inf:
                continue
            deviation = (times[i] - times[j] - target) / target
            score = best[j] + deviation * deviation
            if score < best[i]:
                best[i], previous[i] = score, j
        if best[i] != math.inf and i != last:
            best[i] += boundary_weight * (1.0 - points[i][1])

    if best[last] == math.inf:
        return []
    chosen = []
    node = last
    while node != -1:
        chosen.append(points[node])
        node = previous[node]
    chosen.reverse()
    return chosen


def titles_between(chapters: list[dict], start: float, end: float) -> list[str]:
    """Titres des chapitres du livre entendus dans [start, end[.

    Un morceau qui reprend un chapitre déjà entamé le signale par « (suite) ».
    """
    titles = []
    for chapter in chapters:
        if chapter["start"] >= end - MERGE_DISTANCE or chapter["end"] <= start + MERGE_DISTANCE:
            continue
        if chapter["start"] < start - MERGE_DISTANCE:
            titles.append(f"{chapter['title']} (suite)")
        else:
            titles.append(chapter["title"])
    return titles


def describe(titles: list[str]) -> str:
    if not titles:
        return ""
    if len(titles) == 1:
        return titles[0]
    return f"{titles[0]} → {titles[-1]}"


def plan_book(
    duration: float, chapters: list[dict], silences: list[tuple[float, float]],
    target: float = 600.0, mode: str = "duree", tolerance: float = 0.5,
    boundary_weight: float = 0.4, begin: float = 0.0, finish: float | None = None,
) -> list[dict]:
    """Calcule les chapitres Telmi. Purement arithmétique : instantané.

    begin et finish écartent le début ou la fin du livre (le jingle Audible,
    les crédits), en secondes.
    """
    finish = duration if finish is None else min(finish, duration)
    begin = max(0.0, begin)
    if finish <= begin:
        return []

    if mode == "livre" and chapters:
        cuts = [(begin, 1.0)]
        cuts += [(c["start"], 1.0) for c in chapters if begin + MERGE_DISTANCE < c["start"] < finish - MERGE_DISTANCE]
        cuts.append((finish, 1.0))
    else:
        span = finish - begin
        if span <= target * (1 - tolerance):
            cuts = [(begin, 1.0), (finish, 1.0)]
        else:
            boundaries = [c["start"] - begin for c in chapters]
            local_silences = [(s - begin, e - begin) for s, e in silences
                              if s >= begin and e <= finish]
            candidates = build_candidates(
                span, boundaries, local_silences,
                grid_step=max(target / 4, 2 * MERGE_DISTANCE),
            )
            local = choose_cuts(
                span, candidates, target,
                min_length=target * (1 - tolerance),
                max_length=target * (1 + tolerance),
                boundary_weight=boundary_weight,
            )
            cuts = [(moment + begin, quality) for moment, quality in local]
    if len(cuts) < 2:
        return []

    plan = []
    for index in range(len(cuts) - 1):
        start, quality = cuts[index]
        end = cuts[index + 1][0]
        titles = titles_between(chapters, start, end)
        cut_quality = 1.0 if index == 0 else round(quality, 3)
        plan.append({
            "index": index,
            "file": f"chapitre_{index + 1:02d}.mp3",
            "image": f"chapitre_{index + 1:02d}.png",
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "cut_quality": cut_quality,
            "cut_label": cut_label(cut_quality),
            "title": describe(titles) or f"Chapitre {index + 1}",
            # Affiché dans le Studio de Telmi Sync : la liste des chapitres du livre
            "text": "\n".join(titles),
        })
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("book", type=Path, help="Dossier Libation du livre, ou son fichier audio")
    parser.add_argument("-o", "--output", type=Path, default=Path("chapitres"),
                        help="Dossier de sortie des chapitres (défaut : chapitres)")
    parser.add_argument("--mode", choices=("duree", "livre"), default="duree",
                        help="« livre » garde un chapitre Telmi par chapitre du livre ; "
                             "« duree » (défaut) vise une durée régulière")
    parser.add_argument("-d", "--duration", type=float, default=600.0,
                        help="Durée visée pour un chapitre, en secondes (défaut : 600)")
    parser.add_argument("--tolerance", type=float, default=0.5,
                        help="Écart toléré autour de la durée visée, de 0 à 1 (défaut : 0.5)")
    parser.add_argument("--boundary-weight", type=float, default=0.4,
                        help="Prix d'une coupe hors fin de chapitre (défaut : 0.4)")
    parser.add_argument("--skip-start", type=float, default=0.0,
                        help="Secondes à écarter au début (jingle, crédits)")
    parser.add_argument("--skip-end", type=float, default=0.0,
                        help="Secondes à écarter à la fin (crédits)")
    parser.add_argument("--silences", action="store_true",
                        help="Cherche toujours les silences, même si les chapitres suffisent")
    parser.add_argument("--noise", type=float, default=-35.0,
                        help="Seuil de silence en dB (défaut : -35, livres audio très propres)")
    parser.add_argument("--bitrate", default="128k", help="Débit MP3 (défaut : 128k)")
    parser.add_argument("--preview", action="store_true",
                        help="Affiche le découpage sans rien encoder")
    args = parser.parse_args()

    if not 0 < args.tolerance <= 1:
        sys.exit("Erreur : --tolerance doit être compris entre 0 (exclu) et 1.")
    try:
        book = load_book(args.book, args.output / "_travail")
    except RuntimeError as error:
        sys.exit(f"Erreur : {error}")

    print(f"Livre : {book['title']} — {format_time(book['duration'])}")
    print(f"{len(book['chapters'])} chapitres dans le livre ({book['source_kind']})")

    silences = []
    if args.mode == "duree" and (args.silences or needs_silences(book["chapters"])):
        print("Recherche des silences (une à deux minutes par heure d'écoute)...")
        silences = detect_silences(book["audio"], args.noise, 0.6)
        print(f"  {len(silences)} silences trouvés.")

    plan = plan_book(
        book["duration"], book["chapters"], silences, args.duration, args.mode,
        args.tolerance, args.boundary_weight,
        begin=args.skip_start, finish=book["duration"] - args.skip_end,
    )
    if not plan:
        sys.exit("Erreur : aucun découpage possible. Assouplissez --tolerance "
                 "ou changez la durée visée.")

    print(f"\n{len(plan)} chapitres Telmi :\n")
    for chapter in plan:
        print(f"  {chapter['index'] + 1:>3}  {format_time(chapter['start']):>8}  "
              f"{format_time(chapter['duration']):>8}  {chapter['cut_label']:<16} "
              f"{chapter['title']}")

    if args.preview:
        print("\nMode aperçu : rien n'a été encodé.")
        return

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"\nEncodage dans '{args.output}'...")
    for chapter in plan:
        extract_audio_segment(book["audio"], args.output / chapter["file"],
                              chapter["start"], chapter["duration"], bitrate=args.bitrate)
        print(f"  ✅ {chapter['file']}")

    manifest = {
        "source": str(book["audio"]),
        "title": book["title"],
        "cover": str(book["cover"]) if book["cover"] else None,
        "source_duration": round(book["duration"], 3),
        "chapters": plan,
    }
    (args.output / "chapters.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nTerminé. Étape suivante :")
    print(f'  python scripts/make_images.py {args.output}/chapters.json')
    print(f'  python scripts/build_pack.py {args.output}/chapters.json -t "{book["title"]}"')


if __name__ == "__main__":
    main()
