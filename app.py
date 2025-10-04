"""Flask web UI for browsing sleep monitor recordings."""
from __future__ import annotations

import datetime as dt
import logging
import queue
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from flask import (
    Flask,
    Response,
    abort,
    render_template,
    send_from_directory,
    url_for,
)

logger = logging.getLogger("sleep_monitor.webapp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

APP_ROOT = Path(__file__).resolve().parent
RECORDINGS_DIR = APP_ROOT / "recordings"
THUMBNAILS_DIR = RECORDINGS_DIR / ".thumbnails"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
THUMBNAIL_EXTENSION = ".jpg"
FFMPEG_BIN = "ffmpeg"
THUMBNAIL_SCALE = "480:-1"

TIMESTAMP_PATTERN = re.compile(r"video_(?P<date>\d{8})_(?P<time>\d{6})")

PLACEHOLDER_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 160 90' "
    "preserveAspectRatio='xMidYMid slice'>"
    "<rect width='160' height='90' fill='#1f2937'/>"
    "<polygon points='64,30 64,60 90,45' fill='#4ade80'/></svg>"
)


@dataclass
class VideoMeta:
    filename: str
    display_name: str
    timestamp: dt.datetime
    timestamp_label: str
    filesize_bytes: int
    filesize_label: str
    thumbnail_name: str
    thumbnail_exists: bool

    @property
    def video_url(self) -> str:
        return url_for("serve_video", filename=self.filename)

    @property
    def thumbnail_url(self) -> str:
        return url_for("serve_thumbnail", filename=self.thumbnail_name)


thumbnail_queue: "queue.Queue[Path]" = queue.Queue()
queued_videos: set[Path] = set()
queue_lock = threading.Lock()
worker_started = threading.Event()

app = Flask(__name__)


def ensure_directories() -> None:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)


def iter_video_files() -> Iterable[Path]:
    if not RECORDINGS_DIR.exists():
        return []
    for path in RECORDINGS_DIR.iterdir():
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            yield path


def thumbnail_path_for(video_path: Path) -> Path:
    return THUMBNAILS_DIR / f"{video_path.stem}{THUMBNAIL_EXTENSION}"


def parse_timestamp_from_filename(video_path: Path) -> dt.datetime | None:
    match = TIMESTAMP_PATTERN.match(video_path.stem)
    if not match:
        return None
    try:
        combined = match.group("date") + match.group("time")
        return dt.datetime.strptime(combined, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def human_filesize(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def enqueue_thumbnail(video_path: Path) -> None:
    resolved = video_path.resolve()
    with queue_lock:
        if resolved in queued_videos:
            return
        queued_videos.add(resolved)
    thumbnail_queue.put(resolved)
    logger.debug("Queued thumbnail generation for %s", resolved)


def generate_thumbnail(video_path: Path) -> None:
    thumb_path = thumbnail_path_for(video_path)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    if not video_path.exists():
        logger.warning("Video %s disappeared before thumbnail generation", video_path)
        return
    command = [
        FFMPEG_BIN,
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        f"thumbnail,scale={THUMBNAIL_SCALE}",
        str(thumb_path),
    ]
    logger.info("Generating thumbnail: %s", " ".join(command))
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        logger.error("ffmpeg binary not found while generating thumbnail for %s: %s", video_path, exc)
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg failed to create thumbnail for %s (exit code %s)", video_path, exc.returncode)
    else:
        logger.info("Thumbnail created at %s", thumb_path)


def thumbnail_worker() -> None:
    worker_started.set()
    while True:
        video_path = thumbnail_queue.get()
        try:
            generate_thumbnail(video_path)
        finally:
            with queue_lock:
                queued_videos.discard(video_path)
            thumbnail_queue.task_done()


def start_thumbnail_worker() -> None:
    if worker_started.is_set():
        return
    thread = threading.Thread(target=thumbnail_worker, name="ThumbnailWorker", daemon=True)
    thread.start()


def collect_video_metadata() -> List[VideoMeta]:
    videos: List[VideoMeta] = []
    for video_path in iter_video_files():
        stat = video_path.stat()
        timestamp = parse_timestamp_from_filename(video_path)
        if timestamp is None:
            timestamp = dt.datetime.fromtimestamp(stat.st_mtime)
        thumb_path = thumbnail_path_for(video_path)
        thumbnail_exists = thumb_path.exists()
        if not thumbnail_exists:
            enqueue_thumbnail(video_path)
        videos.append(
            VideoMeta(
                filename=video_path.name,
                display_name=video_path.stem.replace("_", " "),
                timestamp=timestamp,
                timestamp_label=timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                filesize_bytes=stat.st_size,
                filesize_label=human_filesize(stat.st_size),
                thumbnail_name=thumb_path.name,
                thumbnail_exists=thumbnail_exists,
            )
        )
    videos.sort(key=lambda video: video.timestamp, reverse=True)
    return videos


@app.route("/")
def index() -> str:
    videos = collect_video_metadata()
    return render_template("index.html", videos=videos)


def _resolve_within(root: Path, filename: str) -> Path:
    candidate = (root / filename).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FileNotFoundError(filename) from exc
    return candidate


@app.route("/videos/<path:filename>")
def serve_video(filename: str):
    try:
        _resolve_within(RECORDINGS_DIR, filename)
    except FileNotFoundError:
        abort(404)
    return send_from_directory(RECORDINGS_DIR, filename)


@app.route("/thumbnail/<path:filename>")
def serve_thumbnail(filename: str):
    try:
        _resolve_within(THUMBNAILS_DIR, filename)
    except FileNotFoundError:
        return Response(PLACEHOLDER_SVG, mimetype="image/svg+xml")
    thumb_path = THUMBNAILS_DIR / filename
    if not thumb_path.exists():
        return Response(PLACEHOLDER_SVG, mimetype="image/svg+xml")
    return send_from_directory(THUMBNAILS_DIR, filename)


ensure_directories()
start_thumbnail_worker()


def enqueue_all_missing_thumbnails() -> None:
    for video_path in iter_video_files():
        thumb_path = thumbnail_path_for(video_path)
        if not thumb_path.exists():
            enqueue_thumbnail(video_path)


enqueue_all_missing_thumbnails()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=False)
