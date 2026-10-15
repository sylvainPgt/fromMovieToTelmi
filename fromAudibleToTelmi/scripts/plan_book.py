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
import re
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
# En mode « livre », un chapitre plus court (crédits, jingle) rejoint son voisin
SHORT_CHAPTER = 90.0
# Titres sans intérêt dans un menu dès qu'il y a autre chose à montrer
FILLER_RE = re.compile(r"cr[ée]dits|g[ée]n[ée]rique|ouverture|opening|closing", re.I)


VOLUME_RE = re.compile(
    r"\b(?:tome|livre|volume|vol\.|book|partie|part|saison)\s*(\d+|[ivxlc]+)\b", re.I)
CHAPTER_NUMBER_RE = re.compile(r"^\s*(?:chapitre|chapter|chap\.|ch\.)?\s*(\d+)\b", re.I)
GENERIC_PREFIX_RE = re.compile(
    r"^\s*(?:chapitre|chapter|chap\.|ch\.|partie|part)?\s*\d+\s*$", re.I)
# Chapitres qui ouvrent un tome sans encore en faire partie par leur titre
OPENING_RE = re.compile(
    r"ouverture|introduction|\bintro\b|pr[ée]ambule|prologue|opening|"
    r"g[ée]n[ée]rique(?! de fin)", re.I)


def _prefix(title: str) -> str | None:
    """« La Pierre de Jovénia - Chapitre 3 » → « La Pierre de Jovénia »."""
    parts = re.split(r"\s+[-–—]\s+|\s*:\s+", title, maxsplit=1)
    if len(parts) < 2:
        return None
    prefix = parts[0].strip()
    return None if not prefix or GENERIC_PREFIX_RE.match(prefix) else prefix


def _volume_title(title: str) -> str:
    """« Les Légendaires, Tome 1 : La Pierre de Jovénia » → « Tome 1 : La Pierre de Jovénia »."""
    match = VOLUME_RE.search(title)
    if not match:
        return title
    number = match.group(1).upper()
    rest = title[match.end():].strip(" :-–—,.")
    name = _prefix(rest) or rest
    if not name or GENERIC_PREFIX_RE.match(name) or CHAPTER_NUMBER_RE.match(name):
        return f"Tome {number}"
    return f"Tome {number} : {name}"


def _changes(values: list) -> list[int]:
    """Indices où la valeur (connue) change, en ignorant les valeurs absentes."""
    starts, last = [0], None
    for index, value in enumerate(values):
        if value is None:
            continue
        if last is not None and value != last:
            starts.append(index)
        last = value
    return starts


def detect_volumes(chapters: list[dict]) -> list[dict]:
    """Repère les tomes d'une compilation d'après les titres des chapitres.

    Trois indices, essayés dans l'ordre :
    1. un numéro de tome explicite (« Tome 3 », « Livre II ») ;
    2. un préfixe commun qui change (« La Pierre de Jovénia - Chapitre 1 ») ;
    3. une numérotation des chapitres qui repart à zéro.

    Un chapitre d'ouverture (crédits, introduction) placé juste avant un
    nouveau tome lui est rattaché. Retourne une liste de
    {"start": indice du premier chapitre, "title": titre proposé} ; une
    seule entrée si rien ne ressemble à une compilation.
    """
    titles = [c["title"] for c in chapters]
    count = len(titles)
    if count < 2:
        return [{"start": 0, "title": ""}]

    numbers = []
    for title in titles:
        match = VOLUME_RE.search(title)
        numbers.append(match.group(1).lower() if match else None)
    prefixes = [_prefix(t) for t in titles]

    starts, kind = [0], None
    by_number = _changes(numbers)
    if len(by_number) >= 2:
        starts, kind = by_number, "tome"
    else:
        by_prefix = _changes(prefixes)
        # Un préfixe qui change à chaque chapitre n'est pas un nom de tome
        if 2 <= len(by_prefix) <= count / 2:
            starts, kind = by_prefix, "prefixe"
        else:
            last = None
            for index, title in enumerate(titles):
                match = CHAPTER_NUMBER_RE.match(title)
                if not match:
                    continue
                value = int(match.group(1))
                if last is not None and value <= last and index > starts[-1] + 1:
                    starts.append(index)
                last = value
            kind = "numerotation" if len(starts) >= 2 else None

    # Les crédits d'ouverture vont avec le tome qu'ils ouvrent
    adjusted = [0]
    for start in starts[1:]:
        while start - 1 > adjusted[-1] and OPENING_RE.search(titles[start - 1]):
            start -= 1
        adjusted.append(start)

    volumes = []
    for position, start in enumerate(adjusted):
        end = adjusted[position + 1] if position + 1 < len(adjusted) else count
        title = ""
        for index in range(start, end):
            if OPENING_RE.search(titles[index]):
                continue
            if kind == "prefixe" and prefixes[index]:
                title = prefixes[index]
            elif kind == "tome" and numbers[index]:
                title = _volume_title(titles[index])
            break
        volumes.append({"start": start, "title": title or (
            f"Tome {position + 1}" if len(adjusted) > 1 else "")})
    return volumes


def volume_spans(chapters: list[dict], starts: list[int], duration: float) -> list[tuple[float, float]]:
    """Début et fin, en secondes, de chaque tome."""
    starts = sorted(set(s for s in starts if 0 <= s < len(chapters)) | {0})
    spans = []
    for position, start in enumerate(starts):
        begin = 0.0 if position == 0 else chapters[start]["start"]
        end = chapters[starts[position + 1]]["start"] if position + 1 < len(starts) else duration
        spans.append((begin, end))
    return spans


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


def merge_short(cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Rattache les chapitres très courts (crédits, jingles) à leur voisin.

    Le premier chapitre rejoint le suivant, les autres le précédent : des
    crédits d'ouverture vont avec le début, des crédits de fin avec la fin.
    """
    cuts = list(cuts)
    changed = True
    while changed and len(cuts) > 2:
        changed = False
        for index in range(len(cuts) - 1):
            if cuts[index + 1][0] - cuts[index][0] >= SHORT_CHAPTER:
                continue
            # Retire la coupe qui isole ce chapitre
            del cuts[index + 1 if index == 0 else index]
            changed = True
            break
    return cuts


def describe(titles: list[str]) -> str:
    meaningful = [t for t in titles if not FILLER_RE.search(t)]
    titles = meaningful or titles
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
        cuts = merge_short(cuts)
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


def encode_plan(book: dict, plan: list[dict], folder: Path, bitrate: str,
                title: str, cover) -> None:
    """Encode les chapitres d'un plan et écrit son chapters.json."""
    folder.mkdir(parents=True, exist_ok=True)
    for chapter in plan:
        extract_audio_segment(book["audio"], folder / chapter["file"],
                              chapter["start"], chapter["duration"], bitrate=bitrate)
        print(f"  ✅ {folder.name}/{chapter['file']}")
    manifest = {
        "source": str(book["audio"]),
        "title": title,
        "cover": str(cover) if cover else None,
        "source_duration": round(book["duration"], 3),
        "chapters": plan,
    }
    (folder / "chapters.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def print_plan(plan: list[dict]) -> None:
    for chapter in plan:
        print(f"  {chapter['index'] + 1:>3}  {format_time(chapter['start']):>8}  "
              f"{format_time(chapter['duration']):>8}  {chapter['cut_label']:<16} "
              f"{chapter['title']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("book", type=Path, help="Dossier Libation du livre, ou son fichier audio")
    parser.add_argument("-o", "--output", type=Path, default=Path("chapitres"),
                        help="Dossier de sortie des chapitres (défaut : chapitres)")
    parser.add_argument("--mode", choices=("duree", "livre"), default="duree",
                        help="« livre » garde un chapitre Telmi par chapitre du livre ; "
                             "« duree » (défaut) vise une durée régulière")
    parser.add_argument("--tomes", action="store_true",
                        help="Compilation : une histoire par tome, chacune dans son "
                             "sous-dossier (tomes repérés d'après les titres des chapitres)")
    parser.add_argument("--tome-starts", default=None,
                        help="Avec --tomes : numéros (à partir de 1) des chapitres du "
                             "livre qui ouvrent un tome, ex. « 1,12,25 ». Remplace la détection.")
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

    begin, finish = args.skip_start, book["duration"] - args.skip_end
    if args.tomes:
        if args.tome_starts:
            try:
                starts = [int(v) - 1 for v in args.tome_starts.split(",") if v.strip()]
            except ValueError:
                sys.exit("Erreur : --tome-starts attend des numéros séparés par des virgules.")
            volumes = [{"start": s, "title": f"Tome {k + 1}"} for k, s in enumerate(sorted(set(starts) | {0}))]
        else:
            volumes = detect_volumes(book["chapters"])
        if len(volumes) < 2:
            print("\n⚠️  Aucun tome repéré dans les titres des chapitres. Indiquez-les "
                  "avec --tome-starts, en vous aidant de read_book.py.")
        spans = volume_spans(book["chapters"], [v["start"] for v in volumes], book["duration"])
        print(f"\n{len(volumes)} tome(s) :")
        plans = []
        for k, (volume, (v_begin, v_end)) in enumerate(zip(volumes, spans)):
            plan = plan_book(book["duration"], book["chapters"], silences, args.duration,
                             args.mode, args.tolerance, args.boundary_weight,
                             begin=max(begin, v_begin), finish=min(finish, v_end))
            plans.append(plan)
            print(f"\n— {volume['title']} ({format_time(v_end - v_begin)}, "
                  f"à partir du chapitre {volume['start'] + 1}) —")
            print_plan(plan)
        if args.preview:
            print("\nMode aperçu : rien n'a été encodé.")
            return
        for k, (volume, plan) in enumerate(zip(volumes, plans)):
            folder = args.output / f"tome_{k + 1:02d}"
            encode_plan(book, plan, folder, args.bitrate, volume["title"], book["cover"])
        print("\nTerminé. Pour chaque tome :")
        print(f"  python scripts/make_images.py {args.output}/tome_01/chapters.json --cover image_du_tome.jpg")
        print(f'  python scripts/build_pack.py {args.output}/tome_01/chapters.json -t "Titre du tome"')
        return

    plan = plan_book(book["duration"], book["chapters"], silences, args.duration,
                     args.mode, args.tolerance, args.boundary_weight,
                     begin=begin, finish=finish)
    if not plan:
        sys.exit("Erreur : aucun découpage possible. Assouplissez --tolerance "
                 "ou changez la durée visée.")
    print(f"\n{len(plan)} chapitres Telmi :\n")
    print_plan(plan)
    if args.preview:
        print("\nMode aperçu : rien n'a été encodé.")
        return
    print(f"\nEncodage dans '{args.output}'...")
    encode_plan(book, plan, args.output, args.bitrate, book["title"], book["cover"])
    print("\nTerminé. Étape suivante :")
    print(f'  python scripts/make_images.py {args.output}/chapters.json')
    print(f'  python scripts/build_pack.py {args.output}/chapters.json -t "{book["title"]}"')


if __name__ == "__main__":
    main()
