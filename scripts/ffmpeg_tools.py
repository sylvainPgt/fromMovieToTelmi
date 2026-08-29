"""Outils partagés pour appeler FFmpeg (détection de silences, découpe, durées).

FFmpeg est cherché d'abord dans le PATH ; à défaut on utilise le binaire
embarqué par imageio-ffmpeg (installé automatiquement avec moviepy), ce qui
évite d'avoir à l'installer soi-même.
"""

import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator, Optional

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d\.\d+)")
_TIME_RE = re.compile(r"time=\s*(\d+):(\d\d):(\d\d\.\d+)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")

# Callback appelé avec la position courante en secondes pendant un traitement
ProgressCallback = Optional[Callable[[float], None]]


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """Retourne le chemin d'un exécutable FFmpeg utilisable."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit(
            "Erreur : FFmpeg est introuvable.\n"
            "Installez-le depuis https://ffmpeg.org/ et assurez-vous qu'il est "
            "dans votre PATH, ou installez le paquet Python 'imageio-ffmpeg'."
        )


def run_ffmpeg(args: list[str]) -> str:
    """Lance FFmpeg et retourne sa sortie stderr (là où il écrit ses logs)."""
    result = subprocess.run(
        [ffmpeg_path(), "-hide_banner", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    return result.stderr


def stream_ffmpeg(args: list[str], on_progress: ProgressCallback = None) -> Iterator[str]:
    """Lance FFmpeg et livre ses lignes de log au fur et à mesure.

    FFmpeg sépare ses lignes d'avancement par des retours chariot, d'où la
    lecture par blocs plutôt que ligne à ligne. Chaque ligne `time=` rencontrée
    est transmise à on_progress sous forme de position en secondes.
    """
    process = subprocess.Popen(
        [ffmpeg_path(), "-hide_banner", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        bufsize=1,
    )
    buffer = ""
    assert process.stderr is not None
    while True:
        chunk = process.stderr.read(256)
        if not chunk:
            break
        buffer += chunk
        pieces = re.split(r"[\r\n]", buffer)
        buffer = pieces.pop()
        for piece in pieces:
            match = _TIME_RE.search(piece)
            if match and on_progress:
                hours, minutes, seconds = match.groups()
                on_progress(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
            yield piece
    if buffer:
        yield buffer
    process.wait()


def media_duration(path: Path) -> float:
    """Durée du média en secondes, lue dans les métadonnées FFmpeg."""
    stderr = run_ffmpeg(["-i", str(path)])
    match = _DURATION_RE.search(stderr)
    if not match:
        raise RuntimeError(
            f"Impossible de lire la durée de {Path(path).name}. "
            "Le fichier est peut-être corrompu ou dans un format non supporté."
        )
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def detect_silences(
    audio_path: Path,
    noise_db: float = -30.0,
    min_duration: float = 0.6,
    on_progress: ProgressCallback = None,
) -> list[tuple[float, float]]:
    """Détecte les passages silencieux et retourne une liste de (début, fin).

    noise_db : seuil en dB sous lequel le son est considéré comme du silence.
    min_duration : durée minimale d'un silence pour être signalé, en secondes.
    """
    silences: list[tuple[float, float]] = []
    pending_start: float | None = None

    for line in stream_ffmpeg(
        [
            "-i", str(audio_path),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
            "-f", "null", "-",
        ],
        on_progress,
    ):
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            # Un silence qui commence avant 0 est tronqué à 0
            pending_start = max(0.0, float(start_match.group(1)))
            continue
        end_match = _SILENCE_END_RE.search(line)
        if end_match and pending_start is not None:
            silences.append((pending_start, float(end_match.group(1))))
            pending_start = None
    return silences


def extract_audio_segment(
    source: Path, destination: Path, start: float, duration: float,
    bitrate: str = "128k", sample_rate: int = 44100,
) -> None:
    """Extrait un segment audio et l'encode en MP3 au format attendu par la Telmi."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    stderr = run_ffmpeg([
        "-y",
        "-ss", f"{start:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-vn",
        "-ar", str(sample_rate),
        "-ac", "2",
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        str(destination),
    ])
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"Échec de l'encodage de {destination.name} :\n{stderr[-800:]}")


def extract_full_audio(
    source: Path, destination: Path, sample_rate: int = 16000,
    on_progress: ProgressCallback = None,
) -> None:
    """Extrait toute la bande son en WAV mono, format idéal pour Whisper."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    for _ in stream_ffmpeg([
        "-y", "-i", str(source),
        "-vn", "-ar", str(sample_rate), "-ac", "1",
        str(destination),
    ], on_progress):
        pass
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"Échec de l'extraction audio vers {destination.name}.")


def make_silent_mp3(destination: Path, duration: float = 1.0, sample_rate: int = 44100) -> None:
    """Crée un court MP3 silencieux (utilisé comme title.mp3 par défaut)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r={sample_rate}:cl=stereo",
        "-t", f"{duration:.3f}",
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        str(destination),
    ])
