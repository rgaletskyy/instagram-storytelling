"""Paths, model IDs and canvas constants.

Everything tunable lives here so the rest of the package holds no magic values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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
LIFESTYLE_BRIEF = RESOURCES_DIR / "lifestyle-content-brief.md"

# .heic/.heif come straight off an iPhone. Claude's vision API does not
# accept them, so they are converted to JPEG before being described.
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
API_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
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
# Story dimensions come from src/resources/story-design-guidelines.md section 1.
# A post is the same design language on a square artboard.

CANVAS_W = 1080
CANVAS_H = 1920
SIDE_MARGIN = 72
SAFE_TOP = 250
SAFE_BOTTOM = 1670

SCREENSHOT_QUALITY = 92

# The text block, including whatever card or scrim sits behind it, gets a budget.
# Left unbounded the layout model reaches for a full-bleed band that swallows a
# fifth of the frame and lands on the subject. Held as a fraction so it scales
# with the artboard rather than being a story-shaped number.
TEXT_BLOCK_MAX_FRACTION = 0.27
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


@dataclass(frozen=True)
class CanvasFormat:
    """An artboard: its size, the aspect Gemini renders, and where text may go."""

    name: str
    width: int
    height: int
    aspect_ratio: str
    safe_top: int
    safe_bottom: int
    safe_note: str

    @property
    def text_block_max_h(self) -> int:
        return int(self.height * TEXT_BLOCK_MAX_FRACTION)


STORY_FORMAT = CanvasFormat(
    name="story",
    width=CANVAS_W,
    height=CANVAS_H,
    aspect_ratio="9:16",
    safe_top=SAFE_TOP,
    safe_bottom=SAFE_BOTTOM,
    safe_note=(
        "the top and bottom bands are covered by Instagram's progress bar, "
        "avatar and reply field"
    ),
)

# Instagram feed posts are square and carry none of the story UI, so the only
# reserved space is the margin itself.
POST_FORMAT = CanvasFormat(
    name="post",
    width=1080,
    height=1080,
    aspect_ratio="1:1",
    safe_top=SIDE_MARGIN,
    safe_bottom=1080 - SIDE_MARGIN,
    safe_note=(
        "a feed post has no story UI over it, so only the margin is reserved; "
        "keep clear of the very edge so nothing is clipped in a crop"
    ),
)

# Lifestyle frames carry no copy -- the brief makes baked-in text an automatic
# reject -- so there is no safe band to respect, only the delivery size from
# lifestyle-content-brief.md section 9.
LIFESTYLE_FORMAT = CanvasFormat(
    name="lifestyle",
    width=1080,
    height=1350,
    aspect_ratio="4:5",
    safe_top=0,
    safe_bottom=1350,
    safe_note="no copy is applied to a lifestyle frame; text is added later in design",
)

FORMATS = {f.name: f for f in (STORY_FORMAT, POST_FORMAT, LIFESTYLE_FORMAT)}


# --- Story shape -------------------------------------------------------------
# src/resources/story-telling-rules.md section 2.

VERIFY_RETRIES = 1

# Video sampling: enough frames to follow what happens in a clip, capped so a
# long video does not fan out into dozens of vision calls.
MIN_VIDEO_FRAMES = 4
MAX_VIDEO_FRAMES = 7
DEFAULT_VIDEO_FRAMES = MAX_VIDEO_FRAMES

# Lifestyle sets: the brief asks for 6-8 frames per product, but a run defaults
# to a smaller set because each frame is a separate generation.
# Reference photographs attached to one generation. A handful anchors the
# subjects; a pile of them dilutes the scene description.
REFERENCE_LIMIT = 3
# How many video frames are worth inspecting to find the dog and the owner.
FRAME_INSPECT_LIMIT = 4

DEFAULT_LIFESTYLE_IMAGES = 3
MAX_LIFESTYLE_IMAGES = 3

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
