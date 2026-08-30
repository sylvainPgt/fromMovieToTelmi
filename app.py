#!/usr/bin/env python3
"""Interface graphique locale pour fabriquer un pack Telmi depuis un film.

Lance un petit serveur web sur votre machine et ouvre votre navigateur.
Aucune dépendance en dehors de la bibliothèque standard de Python : le
serveur réutilise directement les scripts du dossier scripts/.

Rien ne sort de votre ordinateur : le serveur n'écoute que sur 127.0.0.1.

    python app.py
"""

import json
import mimetypes
import os
import socket
import string
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_pack import create_pack  # noqa: E402
from ffmpeg_tools import (  # noqa: E402
    detect_silences, extract_audio_segment, extract_full_audio, media_duration,
)
from split_chapters import format_time, plan_chapters  # noqa: E402
from subtitles import parse_srt  # noqa: E402

WEB_DIR = ROOT / "webapp"
VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".webm", ".mpg", ".mpeg", ".wmv",
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac",
}

# Un seul film à la fois : c'est un outil personnel, pas un service partagé
STATE: dict = {
    "video": None, "duration": 0.0, "silences": [], "speech": [],
    "chapters": [], "workdir": None, "pack_dir": None,
}
JOB: dict = {"state": "idle", "label": "", "progress": 0.0, "error": None, "result": None}
LOCK = threading.Lock()


def set_job(**fields) -> None:
    with LOCK:
        JOB.update(fields)


def snapshot(store: dict) -> dict:
    with LOCK:
        return dict(store)


# --------------------------------------------------------------------------
# Traitements longs, exécutés dans un fil d'exécution séparé
# --------------------------------------------------------------------------

def analyze_worker(params: dict) -> None:
    """Lit le film, transcrit si demandé, puis repère les silences."""
    try:
        video = Path(params["video"]).expanduser()
        if not video.is_file():
            raise RuntimeError(f"Fichier introuvable : {video}")

        set_job(state="running", label="Lecture du film...", progress=0.0, error=None)
        duration = media_duration(video)
        workdir = video.parent / f"{video.stem}_telmi"
        workdir.mkdir(parents=True, exist_ok=True)

        speech = []
        if params.get("transcribe"):
            wav = workdir / "audio_transcription.wav"
            set_job(label="Extraction de la bande son...", progress=0.0)
            extract_full_audio(
                video, wav,
                on_progress=lambda t: set_job(progress=min(99.0, 100 * t / duration)),
            )
            set_job(label="Transcription des dialogues (le plus long)...", progress=0.0)
            try:
                import whisper
            except ImportError:
                raise RuntimeError(
                    "La transcription demande le paquet openai-whisper. "
                    "Installez-le avec : pip install openai-whisper"
                )
            model = whisper.load_model(params.get("model", "base"))
            result = model.transcribe(str(wav), language="fr", fp16=False)
            srt_path = workdir / "dialogues.srt"
            with open(srt_path, "w", encoding="utf-8") as handle:
                for number, segment in enumerate(result["segments"], start=1):
                    handle.write(
                        f"{number}\n{_srt_time(segment['start'])} --> "
                        f"{_srt_time(segment['end'])}\n{segment['text'].strip()}\n\n"
                    )
            speech = parse_srt(srt_path)

        set_job(label="Analyse des silences du film...", progress=0.0)
        silences = detect_silences(
            video,
            float(params.get("noise", -30.0)),
            float(params.get("min_silence", 0.6)),
            on_progress=lambda t: set_job(progress=min(99.0, 100 * t / duration)),
        )

        with LOCK:
            STATE.update({
                "video": video, "duration": duration, "silences": silences,
                "speech": speech, "workdir": workdir, "chapters": [], "pack_dir": None,
            })
        set_job(
            state="done", label="Analyse terminée", progress=100.0,
            result={
                "duration": duration,
                "duration_label": format_time(duration),
                "silences": len(silences),
                "speech": len(speech),
                "workdir": str(workdir),
                "name": video.name,
            },
        )
    except Exception as error:  # noqa: BLE001 - remonté tel quel à l'interface
        traceback.print_exc()
        set_job(state="error", error=str(error), label="", progress=0.0)


def generate_worker(params: dict) -> None:
    """Encode les MP3, choisit les images, puis assemble le pack."""
    try:
        state = snapshot(STATE)
        chapters = state["chapters"]
        video, workdir = state["video"], state["workdir"]
        if not chapters:
            raise RuntimeError("Aucun découpage à générer.")

        total = len(chapters)
        set_job(state="running", label="Encodage des chapitres...", progress=0.0, error=None)
        for position, chapter in enumerate(chapters):
            extract_audio_segment(
                video, workdir / chapter["file"],
                chapter["start"], chapter["duration"],
                bitrate=params.get("bitrate", "128k"),
            )
            set_job(
                progress=100.0 * (position + 1) / total,
                label=f"Encodage du chapitre {position + 1} sur {total}...",
            )

        image_report = {"warnings": [], "mismatch": None, "written": 0}
        if params.get("images"):
            set_job(label="Choix des images...", progress=0.0)
            try:
                from extract_chapter_images import generate_images
            except ImportError as error:
                raise RuntimeError(
                    "Le choix des images demande opencv-python et Pillow. "
                    f"Installez-les avec : pip install -r requirements.txt ({error})"
                )
            image_report = generate_images(
                video, chapters, workdir,
                samples=int(params.get("samples", 9)),
                source_duration=state["duration"],
                on_progress=lambda done, count: set_job(
                    progress=100.0 * done / count,
                    label=f"Choix de l'image {done} sur {count}...",
                ),
            )

        manifest = {
            "source": str(video),
            "source_duration": round(state["duration"], 3),
            "chapters": chapters,
        }
        (workdir / "chapters.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        pack_report = None
        if params.get("pack"):
            set_job(label="Assemblage du pack Telmi...", progress=50.0)
            pack_dir = workdir / "pack"
            pack_report = create_pack(
                chapters, workdir, pack_dir,
                title=params.get("title") or video.stem,
                age=str(params.get("age", "5")),
            )
            with LOCK:
                STATE["pack_dir"] = pack_dir

        set_job(
            state="done", label="Terminé", progress=100.0,
            result={
                "workdir": str(workdir),
                "chapters": total,
                "images": image_report,
                "pack": pack_report,
            },
        )
    except Exception as error:  # noqa: BLE001
        traceback.print_exc()
        set_job(state="error", error=str(error), label="", progress=0.0)


def _srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def start_job(worker, params: dict) -> dict:
    """Démarre un traitement de fond, sauf si un autre tourne déjà."""
    if snapshot(JOB)["state"] == "running":
        return {"ok": False, "error": "Un traitement est déjà en cours."}
    set_job(state="running", label="Démarrage...", progress=0.0, error=None, result=None)
    threading.Thread(target=worker, args=(params,), daemon=True).start()
    return {"ok": True}


# --------------------------------------------------------------------------
# Points d'entrée de l'interface
# --------------------------------------------------------------------------

def available_drives() -> list[dict]:
    """Lecteurs disponibles sous Windows (C:, D:, clé USB...).

    Sans cela, l'explorateur ne pourrait jamais quitter le disque système :
    la remontée par les dossiers parents s'arrête à la racine du lecteur.
    """
    if os.name != "nt":
        return []
    mask = 0
    try:
        import ctypes

        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        mask = 0

    drives = []
    for position, letter in enumerate(string.ascii_uppercase):
        if mask:
            present = bool(mask >> position & 1)
        else:
            # Repli si l'appel système a échoué
            try:
                present = Path(f"{letter}:\\").exists()
            except OSError:
                present = False
        if present:
            drives.append({"name": f"{letter}:", "path": f"{letter}:\\"})
    return drives


def api_browse(path_value: str | None) -> dict:
    """Liste un dossier : sous-dossiers et fichiers vidéo/audio.

    Accepte aussi le chemin d'un film saisi directement, pour aller droit au
    but sans naviguer.
    """
    drives = available_drives()
    if not path_value:
        current = Path.home().resolve()
    else:
        candidate = Path(path_value.strip().strip('"')).expanduser()
        if candidate.is_file():
            if candidate.suffix.lower() not in VIDEO_EXTENSIONS:
                return {"error": f"Ce fichier n'est pas une vidéo reconnue : {candidate.name}",
                        "drives": drives}
            return {"file": {
                "name": candidate.name, "path": str(candidate.resolve()),
                "size": candidate.stat().st_size,
            }}
        if not candidate.is_dir():
            return {"error": f"Chemin introuvable : {candidate}", "drives": drives}
        current = candidate.resolve()

    directories, files = [], []
    try:
        for entry in sorted(current.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    directories.append({"name": entry.name, "path": str(entry)})
                elif entry.suffix.lower() in VIDEO_EXTENSIONS:
                    files.append({
                        "name": entry.name, "path": str(entry),
                        "size": entry.stat().st_size,
                    })
            except OSError:
                continue
    except PermissionError:
        return {"error": f"Dossier non lisible : {current}", "drives": drives}

    parent = str(current.parent) if current.parent != current else None
    return {"path": str(current), "parent": parent, "drives": drives,
            "dirs": directories, "files": files}


def api_segment(params: dict) -> dict:
    """Recalcule le découpage. Instantané : les silences sont déjà en mémoire."""
    state = snapshot(STATE)
    if not state["video"]:
        return {"error": "Analysez d'abord un film."}

    duration = state["duration"]
    count = params.get("chapters")
    target = duration / int(count) if count else float(params.get("target", 300))
    if target <= 0:
        return {"error": "La durée visée doit être positive."}
    if duration <= target:
        return {"error": (
            f"Le film ne dure que {format_time(duration)}, moins qu'un chapitre "
            f"({format_time(target)}). Réduisez la durée visée."
        )}

    chapters = plan_chapters(
        duration, state["silences"], state["speech"], target,
        tolerance=float(params.get("tolerance", 0.5)),
        boundary_weight=float(params.get("boundary_weight", 0.25)),
    )
    if not chapters:
        return {"error": (
            "Aucun découpage possible avec ces réglages. "
            "Augmentez la tolérance ou changez la durée visée."
        )}

    with LOCK:
        STATE["chapters"] = chapters
    return {
        "chapters": [
            {**chapter,
             "start_label": format_time(chapter["start"]),
             "end_label": format_time(chapter["end"]),
             "duration_label": format_time(chapter["duration"])}
            for chapter in chapters
        ],
        "target_label": format_time(target),
        "weak": sum(1 for c in chapters if c["cut_quality"] <= 0.0),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # silence : la console reste lisible
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802 - imposé par BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        route, query = parsed.path, parse_qs(parsed.query)

        if route in ("/", "/index.html"):
            return self._serve_static("index.html")
        if route == "/api/browse":
            return self._send_json(api_browse((query.get("path") or [None])[0]))
        if route == "/api/job":
            return self._send_json(snapshot(JOB))
        if route == "/api/thumb":
            return self._serve_thumb(query)
        if route.startswith("/api/"):
            return self._send_json({"error": "Route inconnue"}, 404)
        return self._serve_static(route.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        payload = self._read_json()

        if route == "/api/analyze":
            return self._send_json(start_job(analyze_worker, payload))
        if route == "/api/segment":
            return self._send_json(api_segment(payload))
        if route == "/api/generate":
            return self._send_json(start_job(generate_worker, payload))
        if route == "/api/quit":
            self._send_json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        return self._send_json({"error": "Route inconnue"}, 404)

    def _serve_static(self, relative: str) -> None:
        target = (WEB_DIR / unquote(relative)).resolve()
        if WEB_DIR.resolve() not in target.parents or not target.is_file():
            return self._send(404, b"Introuvable", "text/plain; charset=utf-8")
        guessed = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if guessed.startswith("text/") or guessed == "application/javascript":
            guessed += "; charset=utf-8"
        return self._send(200, target.read_bytes(), guessed)

    def _serve_thumb(self, query: dict) -> None:
        """Sert une vignette de chapitre, uniquement depuis le dossier de travail."""
        state = snapshot(STATE)
        workdir = state.get("workdir")
        name = (query.get("name") or [""])[0]
        if not workdir or not name:
            return self._send(404, b"Introuvable", "text/plain; charset=utf-8")
        target = (Path(workdir) / unquote(name)).resolve()
        if Path(workdir).resolve() != target.parent or not target.is_file():
            return self._send(404, b"Introuvable", "text/plain; charset=utf-8")
        return self._send(200, target.read_bytes(), "image/png")


def find_port(preferred: int = 8756) -> int:
    """Retourne un port libre, en partant du port souhaité."""
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0  # laisse le système en choisir un


def main() -> None:
    if not (WEB_DIR / "index.html").is_file():
        sys.exit(f"Erreur : interface introuvable dans {WEB_DIR}")

    port = find_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}"

    print("\n  🎧  Story Maker from Movie")
    print(f"  Interface ouverte sur {url}")
    print("  Fermez cette fenêtre (ou Ctrl+C) pour arrêter.\n")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("  Arrêté.")


if __name__ == "__main__":
    main()
