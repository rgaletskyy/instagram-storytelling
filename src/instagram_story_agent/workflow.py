"""The campaign workflow. Every entry point -- CLI, MCP server, module -- lands here."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

from . import ffmpeg, llm, slide_html
from .config import (
    DEFAULT_SLIDES,
    FORMATS,
    GEMINI_IMAGE_PRO_MODEL,
    IMAGE_SUFFIXES,
    INPUT_DIR,
    MAX_SLIDES,
    MIN_SLIDES,
    OUTPUT_DIR,
    POST_FORMAT,
    STORY_FORMAT,
    TOPIC_FILE,
    VERIFY_RETRIES,
    VIDEO_SUFFIXES,
    CanvasFormat,
)
from .models import (
    Campaign,
    CampaignScript,
    MediaDescription,
    SlideSpec,
    SlideVerdict,
)
from .products import extract_skus, get_products

_URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)


def _slug(text: str, limit: int = 40) -> str:
    """A filesystem-safe stem from the topic, transliteration-free."""
    normalised = unicodedata.normalize("NFKD", text.strip().lower())
    slug = re.sub(r"[^\w\s-]", "", normalised, flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return (slug[:limit].rstrip("-")) or "story"


def _new_project_dir(brief: str, fmt: CanvasFormat = STORY_FORMAT) -> Path:
    """A fresh folder per run.

    The timestamp only has second resolution, so two runs started in the same
    second would collide and the second would overwrite the first. Suffix until
    the name is free -- a campaign must never clobber an earlier one.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = OUTPUT_DIR / f"{_slug(brief)}-{fmt.name}-{stamp}"
    candidate = base
    counter = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{counter}")
        counter += 1
    candidate.mkdir(parents=True)
    return candidate


def read_topic() -> str:
    if not TOPIC_FILE.exists():
        raise FileNotFoundError(
            f"no topic brief at {TOPIC_FILE}. Write one describing the story."
        )
    topic = TOPIC_FILE.read_text(encoding="utf-8").strip()
    if not topic:
        raise ValueError(f"{TOPIC_FILE} is empty")
    return topic


def _input_files(input_dir: Path) -> tuple[list[Path], list[Path]]:
    images = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )
    videos = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
    )
    return images, videos


async def describe_video(video: Path, frame_count: int = 8) -> MediaDescription:
    """Frames described one by one, merged with the transcript."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        frames = await ffmpeg.extract_frames(video, tmp_dir, frame_count)
        frame_texts = await asyncio.gather(
            *(llm.describe_image(f) for f in frames), return_exceptions=True
        )
        audio = await ffmpeg.extract_audio(video, tmp_dir / "audio.wav")
        transcript = await llm.transcribe_audio(audio) if audio else ""

    described = [t for t in frame_texts if isinstance(t, str)]
    merged = "\n".join(f"Frame {i}: {t}" for i, t in enumerate(described, 1))
    return MediaDescription(
        path=video,
        kind="video",
        description=merged or "Video could not be described.",
        transcript=transcript or None,
    )


async def describe_inputs(input_dir: Path | None = None) -> list[MediaDescription]:
    """Describe every image and video in the input folder."""
    directory = input_dir or INPUT_DIR
    if not directory.exists():
        raise FileNotFoundError(f"input folder not found: {directory}")

    images, videos = _input_files(directory)
    if not images and not videos:
        raise ValueError(f"no images or video in {directory}")
    if videos:
        # Only video work needs ffmpeg now that slides render in a browser.
        ffmpeg.require_ffmpeg()

    image_results = await asyncio.gather(
        *(llm.inspect_image(p) for p in images), return_exceptions=True
    )
    described: list[MediaDescription] = [
        MediaDescription(
            path=path,
            kind="image",
            description=result.description,
            shows_product=result.shows_product,
        )
        for path, result in zip(images, image_results, strict=True)
        if not isinstance(result, BaseException)
    ]
    for video in videos:
        described.append(await describe_video(video))
    return described


def product_references(
    descriptions: list[MediaDescription], limit: int = 2
) -> list[Path]:
    """The supplied photographs that actually show the product.

    Fed to image generation so the real container appears. Without them the
    image model invents plausible packaging -- a bottle with the right silhouette
    and an entirely fictional label.
    """
    return [d.path for d in descriptions if d.shows_product][:limit]


def _guard_prompts(script: CampaignScript) -> None:
    """The product URL belongs in the script, never in the imagery (FR-008a)."""
    for slide in script.slides:
        if _URL_RE.search(slide.image_prompt):
            raise ValueError(
                f"slide {slide.index}: image_prompt contains a URL, which must "
                f"never reach image generation"
            )


async def _build_slide(
    slide: SlideSpec,
    out_dir: Path,
    model: str,
    verify: bool = True,
    references: list[Path] | None = None,
    fmt: CanvasFormat = STORY_FORMAT,
) -> tuple[Path, SlideVerdict | None]:
    """Background -> HTML layout -> browser screenshot -> verification.

    Each slide gets its own working folder so the browser can load the background
    as a relative asset and concurrent slides cannot collide on the filename.
    """
    work = out_dir / f".slide_{slide.index}"
    work.mkdir(parents=True, exist_ok=True)
    background = work / "background.jpg"
    await llm.generate_image(
        slide.image_prompt,
        background,
        model=model,
        # Only slides that actually feature the product get the packshot.
        references=references if slide.shows_product else None,
        aspect_ratio=fmt.aspect_ratio,
    )

    out_path = out_dir / f"{slide.index}.jpg"
    verdict: SlideVerdict | None = None
    issues: list[str] = []

    for attempt in range(VERIFY_RETRIES + 1):
        html = await llm.generate_slide_html(slide, background, issues or None, fmt)
        await slide_html.screenshot(html, out_path, work, fmt)
        if not verify:
            break
        verdict = await llm.verify_slide(out_path, slide, fmt)
        if verdict.passed:
            break
        issues = verdict.issues
        if attempt == VERIFY_RETRIES:
            # Keep the best effort rather than discarding the slide; the verdict
            # travels with the campaign so the failure is visible.
            break

    shutil.rmtree(work, ignore_errors=True)
    return out_path, verdict


def save_project(campaign: Campaign) -> Path:
    """Write the script beside the slides. The slides are already in place."""
    out_dir = campaign.output_dir
    if out_dir is None:
        raise ValueError("campaign has no output_dir")
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = campaign.script.model_dump(mode="json")
    payload["missing_skus"] = campaign.missing_skus
    payload["failed_slides"] = [list(f) for f in campaign.failed_slides]
    payload["verdicts"] = [v.model_dump(mode="json") for v in campaign.verdicts]
    payload["product_references"] = [str(p) for p in campaign.product_references]
    payload["format"] = campaign.format_name
    (out_dir / "script.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_dir


async def create_campaign(
    topic: str | None = None,
    slide_count: int = DEFAULT_SLIDES,
    verify: bool = True,
    fmt: CanvasFormat = STORY_FORMAT,
) -> Campaign:
    """Brief plus input media in, saved project folder out.

    Stories and feed posts run the identical pipeline; only the artboard
    differs, so the format is threaded through rather than branched on.
    """
    # Fail fast, before anything is generated or any directory is created.
    if not MIN_SLIDES <= slide_count <= MAX_SLIDES:
        raise ValueError(
            f"slide_count must be between {MIN_SLIDES} and {MAX_SLIDES}, "
            f"got {slide_count}"
        )
    brief = topic or read_topic()
    products, missing = get_products(extract_skus(brief))
    descriptions = await describe_inputs()

    script = await llm.generate_script(
        topic=brief,
        descriptions=[d.as_context() for d in descriptions],
        products=products,
        slide_count=slide_count,
    )
    _guard_prompts(script)

    out_dir = _new_project_dir(brief, fmt)

    references = product_references(descriptions)
    results = await asyncio.gather(
        *(
            _build_slide(
                s,
                out_dir,
                llm.GEMINI_IMAGE_MODEL,
                verify=verify,
                references=references,
                fmt=fmt,
            )
            for s in script.slides
        ),
        return_exceptions=True,
    )

    slide_paths: list[Path] = []
    failed: list[tuple[int, str]] = []
    verdicts: list[SlideVerdict] = []
    for slide, result in zip(script.slides, results, strict=True):
        if isinstance(result, BaseException):
            failed.append((slide.index, f"{type(result).__name__}: {result}"))
            continue
        path, verdict = result
        slide_paths.append(path)
        if verdict is not None:
            verdicts.append(verdict)

    campaign = Campaign(
        topic=brief,
        script=script,
        slide_paths=slide_paths,
        output_dir=out_dir,
        missing_skus=missing,
        failed_slides=failed,
        verdicts=verdicts,
        product_references=references,
        format_name=fmt.name,
    )
    save_project(campaign)
    return campaign


async def regenerate_slide(
    project_dir: str | Path, slide_index: int, comment: str
) -> Path:
    """Redo one slide from a comment, leaving the others untouched."""
    out_dir = Path(project_dir)
    script_file = out_dir / "script.json"
    if not script_file.exists():
        raise FileNotFoundError(f"no script.json in {out_dir}")

    payload = json.loads(script_file.read_text(encoding="utf-8"))
    script = CampaignScript.model_validate(payload)

    target = next((s for s in script.slides if s.index == slide_index), None)
    if target is None:
        raise ValueError(f"slide {slide_index} is not in this campaign")

    revised = await llm.revise_slide_spec(target, comment)
    if _URL_RE.search(revised.image_prompt):
        raise ValueError("revised image_prompt contains a URL")

    # Reuse the packshots recorded at generation time rather than re-describing
    # every input image for a single-slide change.
    references = [
        Path(r) for r in payload.get("product_references", []) if Path(r).exists()
    ]
    rendered, _verdict = await _build_slide(
        revised,
        out_dir,
        GEMINI_IMAGE_PRO_MODEL,
        references=references,
        fmt=FORMATS.get(payload.get("format", "story"), STORY_FORMAT),
    )

    # Rewrite only this entry, preserving everything else in the file.
    payload["slides"] = [
        revised.model_dump(mode="json") if s["index"] == slide_index else s
        for s in payload["slides"]
    ]
    script_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rendered


async def create_story_campaign(
    topic: str | None = None,
    slide_count: int = DEFAULT_SLIDES,
    verify: bool = True,
) -> Campaign:
    """A 9:16 story sequence."""
    return await create_campaign(topic, slide_count, verify, STORY_FORMAT)


async def create_post_campaign(
    topic: str | None = None,
    slide_count: int = DEFAULT_SLIDES,
    verify: bool = True,
) -> Campaign:
    """A 1:1 square feed post or carousel."""
    return await create_campaign(topic, slide_count, verify, POST_FORMAT)
