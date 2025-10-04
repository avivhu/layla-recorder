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
    render_template_string,
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


INDEX_TEMPLATE = """
<!doctype html>
<html lang="en" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sleep Monitor Recordings</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    dialog::backdrop {
      background: rgba(15, 23, 42, 0.75);
      backdrop-filter: blur(4px);
    }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
  <div class="container mx-auto px-6 py-8 max-w-7xl">
    <h1 class="text-4xl font-bold mb-8 bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent">
      Sleep Monitor Recordings
    </h1>
    
    {% if videos %}
      <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
        {% for video in videos %}
          <a href="#" 
             class="group bg-gradient-to-br from-blue-900/40 to-cyan-900/30 rounded-2xl overflow-hidden shadow-xl hover:shadow-2xl transition-all duration-200 hover:-translate-y-1 flex flex-col cursor-pointer"
             data-video-url="{{ video.video_url }}" 
             data-video-title="{{ video.display_name }}">
            <div class="relative aspect-video bg-slate-900/60 overflow-hidden">
              <img src="{{ video.thumbnail_url }}" 
                   alt="Thumbnail for {{ video.display_name }}" 
                   loading="lazy"
                   class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200">
              <div class="absolute inset-0 bg-gradient-to-t from-slate-900/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center">
                <svg class="w-12 h-12 text-white" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"/>
                </svg>
              </div>
            </div>
            <div class="p-4 flex flex-col gap-1.5">
              <div class="text-base font-semibold capitalize truncate">
                {{ video.display_name }}
              </div>
              <div class="text-sm text-slate-400">
                {{ video.timestamp_label }}
              </div>
              <div class="text-xs text-slate-500">
                {{ video.filesize_label }}
              </div>
            </div>
          </a>
        {% endfor %}
      </div>
    {% else %}
      <div class="text-center py-20 text-slate-400 text-lg">
        No recordings found in the recordings/ directory yet.
      </div>
    {% endif %}
  </div>

  <dialog id="playerDialog" 
          class="bg-slate-900/95 backdrop-blur-sm rounded-2xl p-0 max-w-4xl w-11/12 border border-slate-700/50 shadow-2xl">
    <div class="flex items-center justify-between p-5 border-b border-slate-700/50">
      <h2 id="dialogTitle" class="text-lg font-semibold text-slate-100">Recording</h2>
      <button type="button" 
              id="closeDialog"
              aria-label="Close"
              class="text-slate-400 hover:text-slate-100 text-3xl leading-none transition-colors">
        ×
      </button>
    </div>
    <video id="dialogVideo" 
           controls 
           preload="metadata"
           class="w-full rounded-b-2xl outline-none"></video>
  </dialog>

  <script>
    const dialog = document.getElementById('playerDialog');
    const closeButton = document.getElementById('closeDialog');
    const titleEl = document.getElementById('dialogTitle');
    const videoEl = document.getElementById('dialogVideo');

    function closeDialog() {
      videoEl.pause();
      videoEl.removeAttribute('src');
      videoEl.load();
      dialog.close();
    }

    closeButton.addEventListener('click', closeDialog);
    dialog.addEventListener('cancel', (event) => {
      event.preventDefault();
      closeDialog();
    });

    document.querySelectorAll('a[data-video-url]').forEach(tile => {
      tile.addEventListener('click', event => {
        event.preventDefault();
        const videoUrl = tile.dataset.videoUrl;
        const videoTitle = tile.dataset.videoTitle;
        titleEl.textContent = videoTitle;
        videoEl.src = videoUrl;
        dialog.showModal();
        const playPromise = videoEl.play();
        if (playPromise !== undefined) {
          playPromise.catch(() => {});
        }
      });
    });
  </script>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    videos = collect_video_metadata()
    return render_template_string(INDEX_TEMPLATE, videos=videos)


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
