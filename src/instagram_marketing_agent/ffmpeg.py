"""Thin async wrapper over the local ffmpeg binary.

Only video work lives here -- pulling audio and frames out of a supplied clip.
Slides are laid out as HTML and screenshotted in a browser (see slide_html.py),
so no text is drawn with ffmpeg and no libfreetype build is required.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from .config import FFMPEG_BIN, FFPROBE_BIN


class FFmpegMissingError(RuntimeError):
    """Raised when no usable ffmpeg binary can be found."""


def require_ffmpeg() -> str:
    """Return a usable ffmpeg path, or explain how to get one.

    Only called when a video is actually supplied; an images-only campaign needs
    no ffmpeg at all.
    """
    path = shutil.which(FFMPEG_BIN) or (
        FFMPEG_BIN if Path(FFMPEG_BIN).is_file() else None
    )
    if not path:
        raise FFmpegMissingError(
            f"ffmpeg not found (looked for {FFMPEG_BIN!r}), and it is needed to "
            f"read video input. Install it with `brew install ffmpeg`, or set "
            f"STORY_FFMPEG to a binary path."
        )
    return path


async def _run(*args: str) -> None:
    """Run ffmpeg, raising with its stderr when it fails."""
    exe = require_ffmpeg()
    proc = await asyncio.create_subprocess_exec(
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {detail}")


async def _has_audio(video: Path) -> bool:
    """True when the file carries at least one audio stream."""
    probe = shutil.which(FFPROBE_BIN) or (
        FFPROBE_BIN if Path(FFPROBE_BIN).is_file() else None
    )
    if not probe:
        return False
    proc = await asyncio.create_subprocess_exec(
        probe,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(video),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return bool(stdout.strip())


async def extract_audio(video: Path, out_path: Path) -> Path | None:
    """Pull the audio track out of a video. Returns None when there is none."""
    if not await _has_audio(video):
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    await _run("-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(out_path))
    return out_path


def _probe(video: Path, entry: str) -> str:
    """Read one ffprobe field. Returns "" when ffprobe is absent or fails."""
    probe = shutil.which(FFPROBE_BIN) or (
        FFPROBE_BIN if Path(FFPROBE_BIN).is_file() else None
    )
    if not probe:
        return ""
    try:
        result = subprocess.run(
            [probe, "-v", "error", "-show_entries", entry,
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def duration(video: Path) -> float:
    """Length of the clip in seconds, or 0.0 when it cannot be determined."""
    try:
        return float(_probe(video, "format=duration"))
    except ValueError:
        return 0.0


async def extract_frames_every(
    video: Path, out_dir: Path, every_seconds: float
) -> list[Path]:
    """Sample one frame every `every_seconds`, across the whole clip.

    The only way frames come out of a video here. A caller that wants a fixed
    count divides the clip's duration by it; a caller cataloguing a clip picks
    the spacing outright. Naming is `frame_001.jpg` upward, which is how a saved
    campaign's footage is found again.
    """
    if every_seconds <= 0:
        raise ValueError(f"the interval must be positive, got {every_seconds}")

    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "frame_%03d.jpg"
    await _run(
        "-i",
        str(video),
        "-vf",
        f"fps=1/{every_seconds:g}",
        "-q:v",
        "3",
        str(pattern),
    )
    return sorted(out_dir.glob("frame_*.jpg"))
