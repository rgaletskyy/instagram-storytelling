"""Paths, model IDs and canvas constants.

Everything tunable lives here so the rest of the package holds no magic values.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Paths -------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = ROOT / "content" / "input"
OUTPUT_DIR = ROOT / "content" / "output"
RESOURCES_DIR = ROOT / "src" / "resources"

TOPIC_FILE = INPUT_DIR / "topic.md"
# The real catalogue is kept out of version control. Fall back to the committed
# sample so a fresh clone runs without one.
_PRODUCTS_REAL = RESOURCES_DIR / "products.xlsx"
_PRODUCTS_SAMPLE = RESOURCES_DIR / "products.sample.xlsx"
PRODUCTS_XLSX = _PRODUCTS_REAL if _PRODUCTS_REAL.exists() else _PRODUCTS_SAMPLE
DESIGN_GUIDELINES = RESOURCES_DIR / "story-design-guidelines.md"
STORYTELLING_RULES = RESOURCES_DIR / "story-telling-rules.md"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi"}

# --- Credentials -------------------------------------------------------------

ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"
GEMINI_KEY_ENV = "GEMINI_API_KEY"

# --- Models ------------------------------------------------------------------
# Pinned in specs/001-instagram-story-agent/plan.md. GEMINI_TRANSCRIBE_MODEL is a
# deliberate substitution: requirements.md named an image-generation model, which
# cannot accept audio input. See research.md R2.

CLAUDE_DESCRIBE_MODEL = "claude-sonnet-5"
CLAUDE_SCRIPT_MODEL = "claude-opus-5"
GEMINI_IMAGE_MODEL = "gemini-3-pro-image"
GEMINI_IMAGE_PRO_MODEL = "gemini-3-pro-image"
GEMINI_TRANSCRIBE_MODEL = "gemini-3.5-transcribe"

# --- Canvas ------------------------------------------------------------------
# From src/resources/story-design-guidelines.md section 1.

CANVAS_W = 1080
CANVAS_H = 1920
SIDE_MARGIN = 72
SAFE_TOP = 250
SAFE_BOTTOM = 1670

SCREENSHOT_QUALITY = 92

# The text block, including whatever card or scrim sits behind it, gets a budget.
# Left unbounded the layout model reaches for a full-bleed band that swallows a
# fifth of the frame and lands on the subject.
TEXT_BLOCK_MAX_H = 520          # px, ~27% of canvas height
HEADLINE_MAX_PX = 64
BODY_MAX_PX = 34

# Brand fonts, loaded by the rendered page from Google Fonts. Rendering in a
# browser means the guidelines' mandated typefaces can finally be used rather
# than substituted -- see research.md R6.
FONT_HEADING = "Bitter"
FONT_BODY = "Noto Sans"
GOOGLE_FONTS_HREF = (
    "https://fonts.googleapis.com/css2"
    "?family=Bitter:wght@700;800&family=Noto+Sans:wght@400;600;700&display=swap"
)

# --- Story shape -------------------------------------------------------------
# src/resources/story-telling-rules.md section 2.

VERIFY_RETRIES = 1

MIN_SLIDES = 3
MAX_SLIDES = 7
DEFAULT_SLIDES = 5

SLIDE_ROLES = ("hook", "tension", "solution", "proof", "offer", "cta")


def load_dotenv() -> None:
    """Read .env into the environment without adding a dependency.

    Real environment variables win, matching the note in .env.example.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _tool(env_var: str, default: str) -> str:
    """Resolve a binary path, treating a relative one as repo-relative.

    Relative to the repo rather than the working directory, so the setting keeps
    working whichever folder the server or CLI is launched from.
    """
    value = os.environ.get(env_var, default)
    if "/" in value:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return str(candidate)
    return value


# .env must be read before the constants below consult the environment.
load_dotenv()

# --- ffmpeg ------------------------------------------------------------------
# Rendering needs a build with the drawtext filter, which requires libfreetype.
# Homebrew's bottle does not ship it, so allow pointing at another binary
# instead of shadowing a system install.
FFMPEG_BIN = _tool("STORY_FFMPEG", "ffmpeg")
FFPROBE_BIN = _tool("STORY_FFPROBE", "ffprobe")
