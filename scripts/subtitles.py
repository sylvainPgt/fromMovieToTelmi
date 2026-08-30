"""Lecture des fichiers .srt produits par scripts/transcribe.py."""

import re
from pathlib import Path

_TIME_RE = re.compile(
    r"(\d+):(\d\d):(\d\d)[,.](\d+)\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d+)"
)


def _to_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis.ljust(3, "0")[:3]) / 1000
    )


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    """Retourne les répliques sous forme de (début, fin, texte), en secondes."""
    segments: list[tuple[float, float, str]] = []
    pending: tuple[float, float] | None = None
    lines: list[str] = []

    def flush() -> None:
        if pending is not None:
            text = " ".join(line.strip() for line in lines).strip()
            if text:
                segments.append((pending[0], pending[1], text))

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _TIME_RE.search(raw_line)
        if match:
            flush()
            groups = match.groups()
            pending = (_to_seconds(*groups[:4]), _to_seconds(*groups[4:]))
            lines = []
        elif raw_line.strip() and not raw_line.strip().isdigit():
            lines.append(raw_line)
        elif not raw_line.strip():
            flush()
            pending, lines = None, []

    flush()
    segments.sort(key=lambda seg: seg[0])
    return segments


def text_between(
    segments: list[tuple[float, float, str]], start: float, end: float
) -> str:
    """Concatène les répliques dont le centre tombe entre start et end."""
    parts = [
        text for seg_start, seg_end, text in segments
        if start <= (seg_start + seg_end) / 2 < end
    ]
    return " ".join(parts).strip()
