#!/usr/bin/env python3
"""Interface graphique locale pour fabriquer un pack Telmi depuis un livre Audible.

Le livre doit d'abord être « libéré » par Libation : on part du dossier
qu'il produit (ou directement du fichier .m4b / .mp3).

Lance un petit serveur web sur votre machine et ouvre votre navigateur.
Aucune dépendance en dehors de la bibliothèque standard de Python, de
Pillow et d'un FFmpeg : le serveur réutilise directement les scripts du
dossier scripts/.

Rien ne sort de votre ordinateur : le serveur n'écoute que sur 127.0.0.1.

    python app.py
"""

import base64
import json
import mimetypes
import os
import shutil
import socket
import string
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_pack import create_pack, pack_folder_name, telmi_uuid  # noqa: E402
from ffmpeg_tools import convert_to_mp3, detect_silences, extract_audio_segment  # noqa: E402
from make_images import make_cover, make_images  # noqa: E402
from plan_book import detect_volumes, needs_silences, plan_book, volume_spans  # noqa: E402
from read_book import (  # noqa: E402
    AUDIO_EXTENSIONS, PROTECTED_EXTENSIONS, format_time, load_book,
)

WEB_DIR = ROOT / "webapp"

# Un seul livre à la fois : c'est un outil personnel, pas un service partagé
STATE: dict = {"book": None, "silences": [], "chapters": [], "volumes": [], "workdir": None}
JOB: dict = {"state": "idle", "label": "", "progress": 0.0, "error": None, "result": None}
LOCK = threading.Lock()


def set_job(**fields) -> None:
    with LOCK:
        JOB.update(fields)


def snapshot(store: dict) -> dict:
    with LOCK:
        return dict(store)


def _parse_clock(value: str) -> float:
    """Convertit « MM:SS » ou « HH:MM:SS » en secondes."""
    total = 0.0
    for part in value.split(":"):
        total = total * 60 + float(part)
    return total


def read_instant(value, fallback: float) -> float:
    """Lit un instant saisi « 1:52:12 », « 0:30 » ou en secondes."""
    if value is None or value == "":
        return fallback
    try:
        return max(0.0, _parse_clock(str(value).strip()))
    except (ValueError, AttributeError):
        return fallback


# --------------------------------------------------------------------------
# Traitements longs, exécutés dans un fil d'exécution séparé
# --------------------------------------------------------------------------

def analyze_worker(params: dict) -> None:
    """Lit le livre : chapitres, couverture, et silences si nécessaire."""
    try:
        source = Path(params["book"]).expanduser()
        set_job(state="running", label="Lecture du livre...", progress=10.0, error=None)
        stem = source.name if source.is_dir() else source.stem
        workdir = source.parent / f"{stem}_telmi"
        book = load_book(source, workdir)
        duration = book["duration"]

        silences = []
        if params.get("silences") or needs_silences(book["chapters"]):
            set_job(label="Recherche des silences...", progress=0.0)
            silences = detect_silences(
                book["audio"], float(params.get("noise", -35.0)), 0.6,
                on_progress=lambda t: set_job(progress=min(99.0, 100 * t / duration)),
            )

        with LOCK:
            STATE.update({"book": book, "silences": silences,
                          "chapters": [], "volumes": [], "workdir": workdir})
        # Couvertures et annonces choisies lors d'une lecture précédente
        for pattern in ("couverture_histoire_*", "apercu_histoire_*", "titre_histoire_*"):
            for old in workdir.glob(pattern):
                old.unlink(missing_ok=True)

        cover_name = None
        if book["cover"] is not None:
            make_cover(book["cover"], workdir / "apercu_livre.png")
            cover_name = "apercu_livre.png"
        volumes = detect_volumes(book["chapters"]) if book["chapters"] else []

        set_job(
            state="done", label="Lecture terminée", progress=100.0,
            result={
                "title": book["title"],
                "author": book["author"],
                "duration": duration,
                "duration_label": format_time(duration),
                "source_kind": book["source_kind"],
                "silences": len(silences),
                "cover": cover_name,
                "chapters": [
                    {"title": c["title"], "start_label": format_time(c["start"]),
                     "duration_label": format_time(c["end"] - c["start"]),
                     "duration": c["end"] - c["start"]}
                    for c in book["chapters"]
                ],
                # Compilation repérée d'après les titres : une histoire par tome
                "volumes": volumes if len(volumes) > 1 else [],
                "workdir": str(workdir),
            },
        )
    except Exception as error:  # noqa: BLE001 - remonté tel quel à l'interface
        traceback.print_exc()
        set_job(state="error", error=str(error), label="", progress=0.0)


def story_cover(workdir: Path, volume: int, book: dict):
    """Image choisie pour cette histoire, sinon la couverture du livre."""
    chosen = workdir / f"couverture_histoire_{volume}.png"
    return chosen if chosen.is_file() else book["cover"]


def generate_worker(params: dict) -> None:
    """Encode les MP3, fabrique les images, puis assemble un pack par histoire."""
    try:
        state = snapshot(STATE)
        chapters, book, workdir = state["chapters"], state["book"], state["workdir"]
        volumes = state["volumes"]
        if not chapters:
            raise RuntimeError("Aucun découpage à générer.")

        total = len(chapters)
        set_job(state="running", label="Encodage des chapitres...", progress=0.0, error=None)
        for position, chapter in enumerate(chapters):
            extract_audio_segment(
                book["audio"], workdir / chapter["file"],
                chapter["start"], chapter["duration"],
                bitrate=params.get("bitrate", "128k"),
            )
            set_job(progress=100.0 * (position + 1) / total,
                    label=f"Encodage du chapitre {position + 1} sur {total}...")

        titles = params.get("titles") or {}
        age = str(params.get("age", "7"))
        categorie = (params.get("category") or "Livres audio").strip()
        destination = telmi_stories_dir() if params.get("install") else None
        packs, all_images = [], []

        for volume, info in enumerate(volumes):
            set_job(label=f"Assemblage de l'histoire {volume + 1} sur {len(volumes)}...",
                    progress=100.0 * volume / len(volumes))
            own = [c for c in chapters if c["volume"] == volume]
            cover_source = story_cover(workdir, volume, book)
            images = make_images(own, workdir, cover_source,
                                 numbered=bool(params.get("numbered", True)))
            all_images += [{**image, "volume": volume} for image in images]
            pack_cover = workdir / f"couverture_pack_{volume}.png"
            has_cover = make_cover(cover_source, pack_cover)

            nom_histoire = (titles.get(str(volume)) or info["title"] or book["title"]).strip()
            (workdir / f"chapters_{volume + 1:02d}.json").write_text(json.dumps({
                "source": str(book["audio"]), "title": nom_histoire,
                "cover": str(cover_source) if cover_source else None,
                "chapters": own,
            }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            titre = workdir / f"titre_histoire_{volume}.mp3"
            identifiant = telmi_uuid()
            # Deux packs créés dans la même milliseconde auraient le même identifiant
            time.sleep(0.01)
            pack_dir = workdir / pack_folder_name(nom_histoire, age, identifiant, categorie)
            report = create_pack(
                own, workdir, pack_dir,
                title=nom_histoire, age=age, category=categorie,
                description=book.get("description") or None,
                title_audio=titre if titre.is_file() else None,
                cover=pack_cover if has_cover else None,
                identifier=identifiant,
                show_image=bool(params.get("show_image", True)),
                chapter_audios={
                    c["index"]: workdir / "titres" / f"t{c['gindex']}.mp3"
                    for c in own
                    if (workdir / "titres" / f"t{c['gindex']}.mp3").is_file()
                },
            )
            report["title"] = nom_histoire
            if params.get("install"):
                if destination is None:
                    report["installed"] = None
                else:
                    cible = destination / pack_dir.name
                    shutil.rmtree(cible, ignore_errors=True)
                    shutil.copytree(pack_dir, cible)
                    report["installed"] = str(cible)
            packs.append(report)

        install_error = None
        if params.get("install") and destination is None:
            install_error = ("Dossier de Telmi Sync introuvable : copiez les packs "
                             "vous-même dans .telmi/stories.")
        set_job(
            state="done", label="Terminé", progress=100.0,
            result={"workdir": str(workdir), "chapters": total, "images": all_images,
                    "packs": packs, "install_error": install_error},
        )
    except Exception as error:  # noqa: BLE001
        traceback.print_exc()
        set_job(state="error", error=str(error), label="", progress=0.0)


def telmi_stories_dir() -> Path | None:
    """Dossier où Telmi Sync range ses histoires, s'il existe."""
    dossier = Path.home() / ".telmi" / "stories"
    return dossier if dossier.is_dir() else None


def start_job(worker, params: dict) -> dict:
    """Démarre un traitement de fond, sauf si un autre tourne déjà."""
    if snapshot(JOB)["state"] == "running":
        return {"ok": False, "error": "Un traitement est déjà en cours."}
    set_job(state="running", label="Démarrage...", progress=0.0, error=None,
            result=None, started=time.time())
    threading.Thread(target=worker, args=(params,), daemon=True).start()
    return {"ok": True}


# --------------------------------------------------------------------------
# Envois depuis la page : couverture, annonces
# --------------------------------------------------------------------------

# Au-delà, c'est sûrement une erreur de manipulation
MAX_UPLOAD = 25 * 1024 * 1024


def decode_upload(params: dict) -> bytes:
    """Décode un fichier envoyé par la page, en refusant l'excessif."""
    brut = params.get("data") or ""
    if "," in brut[:120] and brut[:5] == "data:":
        brut = brut.split(",", 1)[1]
    try:
        contenu = base64.b64decode(brut, validate=False)
    except Exception:
        raise RuntimeError("Fichier illisible.")
    if not contenu:
        raise RuntimeError("Fichier vide.")
    if len(contenu) > MAX_UPLOAD:
        raise RuntimeError("Fichier trop volumineux (25 Mo maximum).")
    return contenu


def read_volume(params: dict) -> int:
    """Numéro d'histoire (à partir de 0) envoyé par la page."""
    try:
        volume = int(params.get("volume", 0))
    except (TypeError, ValueError):
        raise RuntimeError("Histoire invalide.")
    if volume < 0 or volume > 99:
        raise RuntimeError("Histoire invalide.")
    return volume


def api_cover(params: dict) -> dict:
    """Choisit l'image d'une histoire, à la place de la couverture du livre."""
    state = snapshot(STATE)
    if not state["workdir"]:
        return {"error": "Choisissez d'abord un livre."}
    workdir = Path(state["workdir"])
    try:
        from io import BytesIO

        from PIL import Image

        volume = read_volume(params)
        chosen = workdir / f"couverture_histoire_{volume}.png"
        with Image.open(BytesIO(decode_upload(params))) as image:
            image.convert("RGB").save(chosen, "PNG")
        make_cover(chosen, workdir / f"apercu_histoire_{volume}.png")
    except RuntimeError as erreur:
        return {"error": str(erreur)}
    except Exception:
        return {"error": "Ce fichier n'est pas une image exploitable."}
    return {"ok": True, "name": f"apercu_histoire_{volume}.png"}


def api_title_audio(params: dict) -> dict:
    """Enregistre l'annonce du titre, convertie au format Telmi."""
    state = snapshot(STATE)
    if not state["workdir"]:
        return {"error": "Choisissez d'abord un livre."}
    workdir = Path(state["workdir"])
    try:
        volume = read_volume(params)
        brut = workdir / "titre_source"
        brut.write_bytes(decode_upload(params))
        convert_to_mp3(brut, workdir / f"titre_histoire_{volume}.mp3")
        brut.unlink(missing_ok=True)
    except RuntimeError as erreur:
        return {"error": str(erreur)}
    except Exception:
        return {"error": "Cet enregistrement n'a pas pu être converti."}
    return {"ok": True}


def api_chapter_audio(params: dict) -> dict:
    """Enregistre l'annonce d'un chapitre pour le menu, convertie en MP3."""
    state = snapshot(STATE)
    if not state["workdir"]:
        return {"error": "Choisissez d'abord un livre."}
    try:
        index = int(params.get("index", -1))
    except (TypeError, ValueError):
        return {"error": "Chapitre invalide."}
    if not 0 <= index < len(state["chapters"]):
        return {"error": "Chapitre inconnu."}
    dossier = Path(state["workdir"]) / "titres"
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        brut = dossier / f"t{index}_source"
        brut.write_bytes(decode_upload(params))
        convert_to_mp3(brut, dossier / f"t{index}.mp3")
        brut.unlink(missing_ok=True)
    except RuntimeError as erreur:
        return {"error": str(erreur)}
    except Exception:
        return {"error": "Cet enregistrement n'a pas pu être converti."}
    return {"ok": True, "index": index}


# --------------------------------------------------------------------------
# Explorateur et découpage
# --------------------------------------------------------------------------

def available_drives() -> list[dict]:
    """Lecteurs disponibles sous Windows (C:, D:, clé USB...)."""
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
            try:
                present = Path(f"{letter}:\\").exists()
            except OSError:
                present = False
        if present:
            drives.append({"name": f"{letter}:", "path": f"{letter}:\\"})
    return drives


def default_folder() -> Path:
    """Dossier des livres de Libation s'il existe, sinon le dossier personnel."""
    for candidate in (Path.home() / "Libation" / "Books",
                      Path.home() / "Documents" / "Libation" / "Books"):
        if candidate.is_dir():
            return candidate
    return Path.home()


def holds_audio(folder: Path) -> bool:
    """Le dossier contient-il un livre (fichier audio ou .aax) ?"""
    try:
        return any(p.suffix.lower() in AUDIO_EXTENSIONS | PROTECTED_EXTENSIONS
                   for p in folder.iterdir() if p.is_file())
    except OSError:
        return False


def api_browse(path_value: str | None) -> dict:
    """Liste un dossier : sous-dossiers (les livres sont signalés) et fichiers audio."""
    drives = available_drives()
    if not path_value:
        current = default_folder().resolve()
    else:
        candidate = Path(path_value.strip().strip('"')).expanduser()
        if candidate.is_file():
            if candidate.suffix.lower() not in AUDIO_EXTENSIONS | PROTECTED_EXTENSIONS:
                return {"error": f"Ce fichier n'est pas un livre audio : {candidate.name}",
                        "drives": drives}
            return {"pick": {"name": candidate.name, "path": str(candidate.resolve())}}
        if not candidate.is_dir():
            return {"error": f"Chemin introuvable : {candidate}", "drives": drives}
        current = candidate.resolve()

    directories, files = [], []
    try:
        for entry in sorted(current.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith(".") or entry.name.endswith("_telmi"):
                continue
            try:
                if entry.is_dir():
                    directories.append({"name": entry.name, "path": str(entry),
                                        "book": holds_audio(entry)})
                elif entry.suffix.lower() in AUDIO_EXTENSIONS | PROTECTED_EXTENSIONS:
                    files.append({"name": entry.name, "path": str(entry),
                                  "size": entry.stat().st_size,
                                  "protected": entry.suffix.lower() in PROTECTED_EXTENSIONS})
            except OSError:
                continue
    except PermissionError:
        return {"error": f"Dossier non lisible : {current}", "drives": drives}

    parent = str(current.parent) if current.parent != current else None
    return {"path": str(current), "parent": parent, "drives": drives,
            "dirs": directories, "files": files, "book": holds_audio(current)}


def api_segment(params: dict) -> dict:
    """Recalcule le découpage. Instantané : tout est déjà en mémoire.

    params["volumes"] liste les chapitres du livre (indices) qui ouvrent une
    nouvelle histoire ; absent ou vide, tout le livre fait une seule histoire.
    """
    state = snapshot(STATE)
    book = state["book"]
    if not book:
        return {"error": "Choisissez d'abord un livre."}
    duration = book["duration"]
    mode = params.get("mode", "duree")
    if mode == "livre" and not book["chapters"]:
        return {"error": "Ce livre n'a pas de chapitres : choisissez une durée."}
    target = float(params.get("target", 600))
    if target <= 0:
        return {"error": "La durée visée doit être positive."}

    begin = read_instant(params.get("trim_start"), 0.0)
    finish = read_instant(params.get("trim_end"), duration)
    if finish <= begin:
        return {"error": "La fin de l'histoire doit venir après son début."}

    starts = [0]
    if book["chapters"]:
        try:
            starts = sorted({0, *(int(v) for v in (params.get("volumes") or []))})
        except (TypeError, ValueError):
            return {"error": "Découpage en histoires invalide."}
        starts = [s for s in starts if 0 <= s < len(book["chapters"])]
    spans = (volume_spans(book["chapters"], starts, duration)
             if book["chapters"] else [(0.0, duration)])

    chapters, volumes = [], []
    for volume, (v_begin, v_end) in enumerate(spans):
        low, high = max(begin, v_begin), min(finish, v_end)
        if high <= low:
            return {"error": f"L'histoire {volume + 1} est vide : vérifiez le début "
                             "et la fin retenus."}
        plan = plan_book(
            duration, book["chapters"], state["silences"], target, mode,
            tolerance=float(params.get("tolerance", 0.5)),
            boundary_weight=float(params.get("boundary_weight", 0.4)),
            begin=low, finish=high,
        )
        if not plan:
            return {"error": "Aucun découpage possible avec ces réglages. "
                             "Assouplissez la régularité ou changez la durée visée."}
        for chapter in plan:
            # Noms de fichiers uniques d'une histoire à l'autre
            stem = f"h{volume + 1:02d}_chapitre_{chapter['index'] + 1:02d}"
            chapter.update({"volume": volume, "gindex": len(chapters),
                            "file": f"{stem}.mp3", "image": f"{stem}.png"})
            chapters.append(chapter)
        preview = Path(state["workdir"]) / f"apercu_histoire_{volume}.png"
        volumes.append({
            "index": volume,
            "start_chapter": starts[volume] if book["chapters"] else 0,
            "title": "",
            "duration_label": format_time(high - low),
            "chapters": len(plan),
            "preview": preview.name if preview.is_file() else None,
            "has_title_audio": (Path(state["workdir"]) / f"titre_histoire_{volume}.mp3").is_file(),
        })

    with LOCK:
        STATE["chapters"] = chapters
        STATE["volumes"] = volumes
    # Les annonces enregistrées étaient liées à l'ancien découpage
    if state["workdir"]:
        shutil.rmtree(Path(state["workdir"]) / "titres", ignore_errors=True)
    return {
        "chapters": [
            {**c, "start_label": format_time(c["start"]),
             "end_label": format_time(c["end"]),
             "duration_label": format_time(c["duration"])}
            for c in chapters
        ],
        "volumes": volumes,
        "weak": sum(1 for c in chapters if c["cut_quality"] <= 0.0),
        "kept_label": format_time(finish - begin),
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
        if route == "/api/telmi":
            dossier = telmi_stories_dir()
            return self._send_json({"found": dossier is not None,
                                    "path": str(dossier) if dossier else None})
        if route == "/api/job":
            job = snapshot(JOB)
            if job.get("started"):
                job["elapsed"] = round(time.time() - job["started"], 1)
            return self._send_json(job)
        if route == "/api/thumb":
            return self._serve_thumb(query)
        if route.startswith("/api/"):
            return self._send_json({"error": "Route inconnue"}, 404)
        return self._serve_static(route.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        payload = self._read_json()
        routes = {
            "/api/analyze": lambda: start_job(analyze_worker, payload),
            "/api/segment": lambda: api_segment(payload),
            "/api/cover": lambda: api_cover(payload),
            "/api/title-audio": lambda: api_title_audio(payload),
            "/api/chapter-audio": lambda: api_chapter_audio(payload),
            "/api/generate": lambda: start_job(generate_worker, payload),
        }
        if route in routes:
            return self._send_json(routes[route]())
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
        """Sert une image, uniquement depuis le dossier de travail."""
        state = snapshot(STATE)
        workdir = state.get("workdir")
        name = (query.get("name") or [""])[0]
        if not workdir or not name:
            return self._send(404, b"Introuvable", "text/plain; charset=utf-8")
        racine = Path(workdir).resolve()
        target = (racine / unquote(name)).resolve()
        if not target.is_relative_to(racine) or not target.is_file():
            return self._send(404, b"Introuvable", "text/plain; charset=utf-8")
        type_image = "image/jpeg" if target.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        return self._send(200, target.read_bytes(), type_image)


def find_port(preferred: int = 8766) -> int:
    """Retourne un port libre, en partant du port souhaité.

    Pas le même que Story Maker from Movie : les deux peuvent tourner ensemble.
    """
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0


def main() -> None:
    if not (WEB_DIR / "index.html").is_file():
        sys.exit(f"Erreur : interface introuvable dans {WEB_DIR}")
    port = find_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print("\n  📚  Story Maker from Audible")
    print(f"  Interface ouverte sur {url}")
    print("  Fermez cette fenêtre (ou Ctrl+C) pour arrêter.\n")
    if "--no-browser" not in sys.argv:
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
