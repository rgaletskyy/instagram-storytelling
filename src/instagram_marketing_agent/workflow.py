"""The campaign workflow. Every entry point -- CLI, MCP server, module -- lands here."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import ffmpeg, llm, slide_html
from .config import (
    DEFAULT_LIFESTYLE_IMAGES,
    DEFAULT_SLIDES,
    DEFAULT_VIDEO_FRAMES,
    FORMATS,
    FRAME_INSPECT_LIMIT,
    GEMINI_IMAGE_PRO_MODEL,
    IMAGE_SUFFIXES,
    INPUT_DIR,
    LIFESTYLE_FORMAT,
    MAX_LIFESTYLE_IMAGES,
    MAX_SLIDES,
    MIN_SLIDES,
    OUTPUT_DIR,
    POST_FORMAT,
    PRODUCT_REFERENCE_LIMIT,
    REFERENCE_LIMIT,
    STORY_FORMAT,
    TOPIC_FILE,
    VERIFY_RETRIES,
    VIDEO_SUFFIXES,
    CanvasFormat,
)
from .models import (
    Campaign,
    CampaignScript,
    LifestyleFrame,
    LifestyleShot,
    MediaDescription,
    SlideSpec,
    SlideVerdict,
)
from .products import (
    download_product_image,
    extract_skus,
    get_products,
    local_product_photos,
)

logger = logging.getLogger(__name__)

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


@contextlib.contextmanager
def _video_workspace(video: Path, artifacts_dir: Path | None):
    """Where a clip's frames and transcript are written.

    With an artifacts directory the extracted frames and the transcript are kept
    alongside the campaign, so what the script was written from can be read back
    afterwards. Without one they are scratch and discarded.
    """
    if artifacts_dir is None:
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp), False
    else:
        keep = artifacts_dir / video.stem
        keep.mkdir(parents=True, exist_ok=True)
        yield keep, True


async def describe_video(
    video: Path,
    frame_count: int = DEFAULT_VIDEO_FRAMES,
    artifacts_dir: Path | None = None,
) -> MediaDescription:
    """Frames described one by one, merged with the transcript.

    When `artifacts_dir` is given, the sampled frames and the transcript are
    saved there rather than thrown away.
    """
    with _video_workspace(video, artifacts_dir) as (work, keeping):
        frames = await ffmpeg.extract_frames(video, work, frame_count)
        frame_texts = await asyncio.gather(
            *(llm.describe_image(f) for f in frames), return_exceptions=True
        )

        audio = await ffmpeg.extract_audio(video, work / "audio.wav")
        transcript = ""
        if audio:
            try:
                transcript = await llm.transcribe_audio(audio)
            except Exception as exc:  # noqa: BLE001 - transcription is optional
                # A clip still describes visually without its spoken content, so
                # a transcription failure must not sink the whole campaign.
                transcript = ""
                logger.warning("could not transcribe %s: %s", video.name, exc)

        described = [t for t in frame_texts if isinstance(t, str)]
        merged = "\n".join(f"Frame {i}: {t}" for i, t in enumerate(described, 1))

        if keeping:
            # The audio is an intermediate; the frames and the words are not.
            if audio is not None:
                audio.unlink(missing_ok=True)
            if transcript:
                (work / "transcript.txt").write_text(transcript, encoding="utf-8")
            if merged:
                (work / "frames.md").write_text(
                    f"# {video.name}\n\n{merged}\n", encoding="utf-8"
                )

    return MediaDescription(
        path=video,
        kind="video",
        description=merged or "Video could not be described.",
        transcript=transcript or None,
        # Only frames that outlive this call can serve as references later.
        frames=list(frames) if keeping else [],
    )


async def describe_inputs(
    input_dir: Path | None = None, artifacts_dir: Path | None = None
) -> list[MediaDescription]:
    """Describe every image and video in the input folder.

    `artifacts_dir` is where a video's frames and transcript are kept.
    """
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

    described: list[MediaDescription] = []
    refused: list[str] = []
    for path, result in zip(images, image_results, strict=True):
        if isinstance(result, BaseException):
            refused.append(f"{path.name}: {type(result).__name__}: {result}")
            logger.warning("could not describe %s: %s", path.name, result)
            continue
        described.append(
            MediaDescription(
                path=path,
                kind="image",
                description=result.description,
                shows_product=result.shows_product,
            )
        )

    # Every photo failing is not a partial result -- the script would be written
    # with no sight of the input at all, which looks like success and is not.
    if images and not described:
        raise RuntimeError(
            "none of the supplied images could be described, so the campaign "
            "would be written without seeing them:\n  "
            + "\n  ".join(refused[:5])
        )
    if refused:
        logger.warning("%d of %d images could not be described", len(refused), len(images))

    for video in videos:
        described.append(
            await describe_video(video, artifacts_dir=artifacts_dir)
        )
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


@dataclass(frozen=True)
class SubjectReferences:
    """Real photographs of what appears in a scene.

    The image prompt describes the scene; who and what is in it comes from
    these. A subject described in words is a subject the model reinvents.
    """

    product: list[Path] = field(default_factory=list)
    dog: list[Path] = field(default_factory=list)
    person: list[Path] = field(default_factory=list)
    # Frames from the supplied video, for scenes that recreate what it shows.
    footage: list[Path] = field(default_factory=list)

    def for_slide(
        self,
        shows_product: bool,
        has_dog: bool,
        has_human: bool,
        from_footage: bool = False,
    ) -> list[Path]:
        """The references to attach, capped so the model is not swamped.

        Every product goes in, not just the first: given one packshot for a
        scene calling for three bottles, the model invents the other two and
        then applies its invention to all of them.
        """
        chosen: list[Path] = []
        if from_footage:
            # First: the scene is that shot, so its look leads.
            chosen += self.footage[:1]
        if shows_product:
            chosen += self.product[:PRODUCT_REFERENCE_LIMIT]
        if has_dog:
            chosen += self.dog[:1]
        if has_human:
            chosen += self.person[:1]
        # Preserve order, drop repeats: one photo may serve two subjects.
        seen: list[Path] = []
        for path in chosen:
            if path not in seen:
                seen.append(path)
        return seen[:REFERENCE_LIMIT]


def _frames_of(descriptions: list[MediaDescription]) -> list[Path]:
    """Frames already sampled from a supplied video, newest description first."""
    frames: list[Path] = []
    for described in descriptions:
        if described.kind == "video" and described.frames:
            frames.extend(described.frames)
    return frames


def catalogue_packshots(products, work: Path) -> list[Path]:
    """Download the official photo of every SKU named in the brief."""
    shots: list[Path] = []
    for product in products:
        downloaded = download_product_image(product, work)
        if downloaded is not None:
            shots.append(downloaded)
        else:
            logger.warning("no catalogue photo for %s", product.sku)
    return shots


async def subject_references(
    descriptions: list[MediaDescription],
    packshots: list[Path] | None = None,
) -> SubjectReferences:
    """Pick a real photograph for each subject that may appear in a scene.

    Video frames count for the dog and the owner: they show the actual animal
    and person in motion, which is usually a better likeness than a posed photo.

    For the PRODUCT they do not. A catalogue packshot is the authoritative
    image of the packaging -- shot straight, label sharp and complete -- while a
    frame catches a bottle at an angle, half out of focus or partly out of
    shot. So packshots always come first, and a frame is only used for a product
    when no packshot exists.
    """
    stills = [d for d in descriptions if d.kind == "image"]
    product = list(packshots or [])
    product += [d.path for d in stills if d.shows_product]
    dog = [d.path for d in stills if d.shows_dog]
    person = [d.path for d in stills if d.shows_person]

    frames = _frames_of(descriptions)
    if frames and not (dog and person):
        # Only pay to inspect frames when a still has not already supplied the
        # subject we are missing.
        looked = await asyncio.gather(
            *(llm.inspect_image(f) for f in frames[:FRAME_INSPECT_LIMIT]),
            return_exceptions=True,
        )
        for frame, result in zip(frames[:FRAME_INSPECT_LIMIT], looked, strict=True):
            if isinstance(result, BaseException):
                continue
            if result.shows_dog:
                dog.append(frame)
            if result.shows_person:
                person.append(frame)
            if result.shows_product and not packshots:
                # A packshot, when we have one, always outranks a video frame.
                product.append(frame)

    return SubjectReferences(
        product=product, dog=dog, person=person, footage=frames
    )


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
    cast: str = "",
    subjects: SubjectReferences | None = None,
) -> tuple[Path, SlideVerdict | None]:
    """Background -> HTML layout -> browser screenshot -> verification.

    Each slide gets its own working folder so the browser can load the background
    as a relative asset and concurrent slides cannot collide on the filename.
    """
    work = out_dir / f".slide_{slide.index}"
    work.mkdir(parents=True, exist_ok=True)
    background = work / "background.jpg"
    prompt = slide.image_prompt
    if slide.has_human:
        prompt += llm._cast_clause(cast)

    # The prompt carries the scene; the subjects come from real photographs, so
    # the dog and the owner stay the same ones rather than being reinvented.
    if subjects is not None:
        attached = subjects.for_slide(
            slide.shows_product,
            slide.has_dog,
            slide.has_human,
            slide.from_footage,
        )
    else:
        attached = list(references or []) if slide.shows_product else []

    await llm.generate_image(
        prompt,
        background,
        model=model,
        references=attached or None,
        aspect_ratio=fmt.aspect_ratio,
    )

    out_path = out_dir / f"{slide.index}.jpg"
    verdict: SlideVerdict | None = None
    issues: list[str] = []

    for attempt in range(VERIFY_RETRIES + 1):
        try:
            html = await llm.generate_slide_html(
                slide, background, issues or None, fmt
            )
            await slide_html.screenshot(html, out_path, work, fmt)
        except Exception as exc:  # noqa: BLE001
            if out_path.exists():
                # A retry that fails must not discard the render that worked.
                logger.warning(
                    "slide %s: retry failed, keeping the earlier render: %s",
                    slide.index,
                    exc,
                )
                break
            raise
        if not verify:
            break
        verdict = await llm.verify_slide(out_path, slide, fmt, cast)
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

    # Created before the input is described so a video's frames and transcript
    # can be written straight into the project rather than to scratch space.
    out_dir = _new_project_dir(brief, fmt)
    descriptions = await describe_inputs(artifacts_dir=out_dir / "source")

    script = await llm.generate_script(
        topic=brief,
        descriptions=[d.as_context() for d in descriptions],
        products=products,
        slide_count=slide_count,
    )
    _guard_prompts(script)

    references = product_references(descriptions)
    # Kept beside the video frames: these are what the packaging was copied
    # from, so a slide with a wrong label can be checked against its source.
    packshots = catalogue_packshots(products, out_dir / "source" / "packshots")
    subjects = await subject_references(descriptions, packshots)
    results = await asyncio.gather(
        *(
            _build_slide(
                s,
                out_dir,
                llm.GEMINI_IMAGE_MODEL,
                verify=verify,
                references=references,
                fmt=fmt,
                cast=script.cast,
                subjects=subjects,
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

    # Everything the campaign generated from is still in source/, so a
    # single-slide redo reuses it rather than re-describing every input.
    source = out_dir / "source"
    subjects = SubjectReferences(
        product=sorted((source / "packshots").glob("*"))
        or [Path(r) for r in payload.get("product_references", []) if Path(r).exists()],
        footage=sorted(source.glob("*/frame_*.jpg")),
    )
    rendered, _verdict = await _build_slide(
        revised,
        out_dir,
        GEMINI_IMAGE_PRO_MODEL,
        fmt=FORMATS.get(payload.get("format", "story"), STORY_FORMAT),
        cast=script.cast,
        subjects=subjects,
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


# --- Lifestyle content -------------------------------------------------------


def _packshot(
    product, work: Path, allow_local: bool = True
) -> tuple[Path | None, list[Path]]:
    """The product photograph to hold the generation to.

    Prefers the catalogue's own image. A photo from the input folder is only
    accepted as a fallback when it can be attributed to this product -- with
    several SKUs in one brief there is no way to tell which one a loose input
    photo depicts, and guessing would put the wrong packaging on a frame.
    """
    if product is not None:
        downloaded = download_product_image(product, work)
        if downloaded is not None:
            return downloaded, [downloaded]

    if not allow_local:
        return None, []

    local = local_product_photos()
    return (local[0] if local else None), local


async def _build_frame(
    shot: LifestyleShot,
    out_dir: Path,
    references: list[Path],
    verify: bool = True,
    prefix: str = "",
    cast: str = "",
) -> LifestyleFrame:
    """Generate one lifestyle frame and judge it.

    No layout pass: the brief rejects baked-in text, so a frame is the finished
    deliverable and copy is applied later in design.
    """
    stem = f"{prefix}-{shot.index}-{shot.role}" if prefix else f"{shot.index}-{shot.role}"
    out_path = out_dir / f"{stem}.jpg"
    verdict = None
    issues: list[str] = []

    for _attempt in range(VERIFY_RETRIES + 1):
        prompt = shot.prompt
        if shot.has_human:
            prompt += llm._cast_clause(cast)
        if shot.excludes:
            prompt = f"{prompt}\n\nDo not include: {shot.excludes}"
        if issues:
            # Section 13 asks for a targeted correction naming the defect,
            # rather than a fresh invention of the whole scene.
            prompt = (
                f"{prompt}\n\nThe previous attempt was rejected. Keep everything "
                f"that worked and fix only these defects:\n"
                + "\n".join(f"- {i}" for i in issues)
            )

        try:
            await llm.generate_image(
                prompt,
                out_path,
                references=references or None,
                aspect_ratio=LIFESTYLE_FORMAT.aspect_ratio,
            )
            slide_html.normalize(out_path, LIFESTYLE_FORMAT)
        except Exception as exc:  # noqa: BLE001
            if out_path.exists():
                logger.warning(
                    "frame %s: retry failed, keeping the earlier render: %s",
                    shot.index,
                    exc,
                )
                break
            raise
        if not verify:
            break
        verdict = await llm.verify_lifestyle_frame(out_path, shot, cast)
        if verdict.passed:
            break
        issues = verdict.issues

    return LifestyleFrame(
        index=shot.index, role=shot.role, path=out_path, verdict=verdict
    )


async def _product_set(
    brief: str,
    product,
    out_dir: Path,
    count: int,
    verify: bool,
    packshot: Path | None,
    references: list[Path],
) -> dict:
    """One lifestyle set for one product, held to an already-resolved packshot."""
    prefix = product.sku if product else ""

    shot_list = await llm.generate_shot_list(brief, product, packshot, count)

    results = await asyncio.gather(
        *(
            _build_frame(s, out_dir, references, verify, prefix, shot_list.cast)
            for s in shot_list.shots
        ),
        return_exceptions=True,
    )

    frames: list[LifestyleFrame] = []
    failed: list[tuple[int, str]] = []
    for shot, result in zip(shot_list.shots, results, strict=True):
        if isinstance(result, BaseException):
            failed.append((shot.index, f"{type(result).__name__}: {result}"))
        else:
            frames.append(result)

    return {
        "sku": product.sku if product else None,
        "product": product.model_dump(mode="json") if product else None,
        "packshot": str(packshot) if packshot else None,
        "images": [str(f.path) for f in frames],
        "shots": shot_list.model_dump(mode="json"),
        "failed_images": [list(f) for f in failed],
        "verdicts": [f.verdict.model_dump(mode="json") for f in frames if f.verdict],
    }


async def create_lifestyle_content(
    topic: str | None = None,
    image_count: int = DEFAULT_LIFESTYLE_IMAGES,
    verify: bool = True,
) -> dict:
    """Lifestyle photography for every product named in the brief.

    `image_count` is per product: a brief naming three SKUs yields three sets.
    Same building blocks as a story campaign -- SKU lookup, product-referenced
    generation, verification -- minus the script and layout steps, because a
    lifestyle set is images only.
    """
    if not 1 <= image_count <= MAX_LIFESTYLE_IMAGES:
        raise ValueError(
            f"image_count must be between 1 and {MAX_LIFESTYLE_IMAGES}, "
            f"got {image_count}"
        )

    brief = topic or read_topic()
    products, missing = get_products(extract_skus(brief))
    out_dir = _new_project_dir(brief, LIFESTYLE_FORMAT)

    # A brief naming no SKU still produces a set, worked from the brief alone.
    targets = products or [None]
    # A loose photo in the input folder can only be attributed to a product when
    # the brief names exactly one.
    allow_local = len(targets) == 1

    sets: list[dict] = []
    skipped: list[dict] = []
    for product in targets:
        work = out_dir / f".source-{product.sku if product else 'unknown'}"
        packshot, references = _packshot(product, work, allow_local=allow_local)
        if product is not None and packshot is None:
            # Generating without the real packaging produces a plausible bottle
            # carrying an invented label, which is worse than no frame at all.
            skipped.append(
                {
                    "sku": product.sku,
                    "reason": "no product image available"
                    + (
                        "; the catalogue row has no photo URL"
                        if not product.image_url.startswith("http")
                        else "; the photo URL could not be downloaded"
                    ),
                }
            )
            logger.warning("skipping %s: no product image", product.sku)
            continue
        sets.append(
            await _product_set(
                brief, product, out_dir, image_count, verify, packshot, references
            )
        )

    if not sets:
        raise RuntimeError(
            "no product image could be obtained for any SKU in the brief, so "
            "every frame would carry invented packaging:\n  "
            + "\n  ".join(f"{s['sku']}: {s['reason']}" for s in skipped)
        )

    payload = {
        "output_dir": str(out_dir),
        "format": LIFESTYLE_FORMAT.name,
        "images_per_product": image_count,
        "sets": sets,
        "skipped": skipped,
        "images": [image for s in sets for image in s["images"]],
        "missing_skus": missing,
        "failed_images": [f for s in sets for f in s["failed_images"]],
        "verdicts": [v for s in sets for v in s["verdicts"]],
    }
    (out_dir / "shots.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload
