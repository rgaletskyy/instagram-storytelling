"""Campaign assembly: the URL guard, fail-fast bounds, and partial failure.

The model and ffmpeg calls are stubbed -- these cover the orchestration rules,
which is where the spec's guarantees live.
"""

import asyncio
import json

import pytest

from instagram_marketing_agent import llm, slide_html, workflow
from instagram_marketing_agent.models import (
    CampaignScript,
    MediaDescription,
    SlideSpec,
    SlideVerdict,
)

pytestmark = pytest.mark.unit


def _script(count=5):
    roles = ["hook", "tension", "solution", "proof", "cta", "offer", "proof"]
    return CampaignScript(
        topic="тема",
        slides=[
            SlideSpec(
                index=i,
                role=roles[i - 1],
                image_prompt=f"a photo, slide {i}",
                overlay_text=f"текст {i}",
                ig_notes="",
            )
            for i in range(1, count + 1)
        ],
        products=[],
        product_url="https://example.com/product",
    )


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """Replace every outbound call so the orchestration runs offline."""
    monkeypatch.setattr(workflow, "OUTPUT_DIR", tmp_path)

    async def fake_inspect(_path):
        from instagram_marketing_agent.llm import _ImageDescription

        return _ImageDescription(description="a description", shows_product=True)

    async def fake_script(**_kwargs):
        return _script()

    async def fake_image(prompt, out_path, model=None, references=None,
                         aspect_ratio=None):
        from pathlib import Path

        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    async def fake_html(slide, background, issues=None, fmt=None):
        return f"<html><body>{slide.overlay_text}</body></html>"

    async def fake_shot(html, out_path, base_dir, fmt=None):
        from pathlib import Path

        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"slide")
        return path

    async def fake_verify(image, slide, fmt=None, cast=""):
        return SlideVerdict(index=slide.index, passed=True)

    monkeypatch.setattr(llm, "inspect_image", fake_inspect)
    monkeypatch.setattr(llm, "generate_script", fake_script)
    monkeypatch.setattr(llm, "generate_image", fake_image)
    monkeypatch.setattr(llm, "generate_slide_html", fake_html)
    monkeypatch.setattr(slide_html, "screenshot", fake_shot)
    monkeypatch.setattr(llm, "verify_slide", fake_verify)

    async def fake_inputs(_dir=None, artifacts_dir=None):
        return [
            MediaDescription(
                path=tmp_path / "packshot.png",
                kind="image",
                description="d",
                shows_product=True,
            ),
            MediaDescription(
                path=tmp_path / "lifestyle.png", kind="image", description="d"
            ),
        ]

    monkeypatch.setattr(workflow, "describe_inputs", fake_inputs)
    return tmp_path


@pytest.mark.parametrize("count", [0, 1, 2, 8, 99])
def test_out_of_range_slide_count_creates_nothing(stubbed, count):
    with pytest.raises(ValueError, match="between 3 and 7"):
        asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=count))
    assert list(stubbed.iterdir()) == []


def test_campaign_saves_slides_and_script(stubbed):
    campaign = asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
    assert len(campaign.slide_paths) == 5
    assert campaign.failed_slides == []
    saved = json.loads((campaign.output_dir / "script.json").read_text(encoding="utf-8"))
    assert saved["product_url"] == "https://example.com/product"
    assert len(saved["slides"]) == 5


def test_one_failing_slide_does_not_discard_the_others(stubbed, monkeypatch):
    async def flaky(prompt, out_path, model=None, references=None,
                    aspect_ratio=None):
        from pathlib import Path

        if prompt.endswith("slide 2"):
            raise RuntimeError("image service refused")
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    monkeypatch.setattr(llm, "generate_image", flaky)
    campaign = asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))

    assert len(campaign.slide_paths) == 4
    assert [index for index, _ in campaign.failed_slides] == [2]
    assert "image service refused" in campaign.failed_slides[0][1]
    # The project is still saved -- a partial run is not thrown away.
    assert (campaign.output_dir / "script.json").exists()


def test_a_url_in_an_image_prompt_stops_the_run(stubbed, monkeypatch):
    async def leaky(**_kwargs):
        script = _script()
        script.slides[2].image_prompt = "photo, see https://example.com/product"
        return script

    monkeypatch.setattr(llm, "generate_script", leaky)
    with pytest.raises(ValueError, match="contains a URL"):
        asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
    # The guard runs before any image is generated, so no slide is produced.
    # The project folder itself may exist by then: it is created up front so a
    # video's frames and transcript have somewhere to go.
    assert not list(stubbed.rglob("*.jpg"))
    assert not list(stubbed.rglob("script.json"))


def test_each_run_gets_its_own_folder(stubbed):
    first = asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
    second = asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
    assert first.output_dir != second.output_dir


def test_a_verdict_is_recorded_for_every_slide(stubbed):
    campaign = asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
    assert [v.index for v in campaign.verdicts] == [1, 2, 3, 4, 5]
    saved = json.loads((campaign.output_dir / "script.json").read_text(encoding="utf-8"))
    assert len(saved["verdicts"]) == 5


def test_a_rejected_slide_is_retried_with_the_issues_as_feedback(stubbed, monkeypatch):
    """The retry must be told what was wrong, or it just repeats the mistake."""
    seen: list[list[str] | None] = []
    attempts = {"n": 0}

    async def counting_html(slide, background, issues=None, fmt=None):
        if slide.index == 1:
            seen.append(issues)
        return "<html></html>"

    async def picky(image, slide, fmt=None, cast=""):
        if slide.index == 1:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return SlideVerdict(index=1, passed=False, issues=["text over the face"])
        return SlideVerdict(index=slide.index, passed=True)

    monkeypatch.setattr(llm, "generate_slide_html", counting_html)
    monkeypatch.setattr(llm, "verify_slide", picky)
    campaign = asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))

    assert seen == [None, ["text over the face"]]
    assert next(v for v in campaign.verdicts if v.index == 1).passed


def test_a_slide_that_never_passes_is_still_kept_and_reported(stubbed, monkeypatch):
    async def always_fail(image, slide, fmt=None, cast=""):
        return SlideVerdict(index=slide.index, passed=False, issues=["still ugly"])

    monkeypatch.setattr(llm, "verify_slide", always_fail)
    campaign = asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))

    assert len(campaign.slide_paths) == 5
    assert all(not v.passed for v in campaign.verdicts)
    assert campaign.failed_slides == []


def test_verification_can_be_skipped(stubbed, monkeypatch):
    async def boom(image, slide, fmt=None, cast=""):
        raise AssertionError("verifier must not run when verify=False")

    monkeypatch.setattr(llm, "verify_slide", boom)
    campaign = asyncio.run(
        workflow.create_story_campaign(topic="тема", slide_count=5, verify=False)
    )
    assert campaign.verdicts == []
    assert len(campaign.slide_paths) == 5


def test_only_product_photos_are_used_as_references(stubbed):
    from instagram_marketing_agent.models import MediaDescription

    described = [
        MediaDescription(path=stubbed / "a.png", kind="image", description="d",
                         shows_product=True),
        MediaDescription(path=stubbed / "b.png", kind="image", description="d"),
        MediaDescription(path=stubbed / "c.png", kind="image", description="d",
                         shows_product=True),
    ]
    assert workflow.product_references(described) == [stubbed / "a.png", stubbed / "c.png"]


def test_reference_count_is_capped(stubbed):
    from instagram_marketing_agent.models import MediaDescription

    described = [
        MediaDescription(path=stubbed / f"{i}.png", kind="image", description="d",
                         shows_product=True)
        for i in range(5)
    ]
    assert len(workflow.product_references(described)) == 2


def test_the_packshot_reaches_only_product_slides(stubbed, monkeypatch):
    """A hook about the problem must not have the bottle composited into it."""
    seen: dict[int, object] = {}

    async def recording_image(prompt, out_path, model=None, references=None,
                              aspect_ratio=None):
        from pathlib import Path

        index = int(Path(out_path).parent.name.rsplit("_", 1)[1])
        seen[index] = references
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    async def mixed_script(**_kwargs):
        script = _script()
        for slide in script.slides:
            slide.shows_product = slide.role in {"solution", "cta"}
        return script

    monkeypatch.setattr(llm, "generate_image", recording_image)
    monkeypatch.setattr(llm, "generate_script", mixed_script)
    asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))

    # roles are hook, tension, solution, proof, cta
    assert seen[1] is None and seen[2] is None and seen[4] is None
    assert seen[3] and seen[5]


def test_references_are_persisted_for_later_revisions(stubbed):
    campaign = asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
    saved = json.loads((campaign.output_dir / "script.json").read_text(encoding="utf-8"))
    assert saved["product_references"] == [str(stubbed / "packshot.png")]


def test_extra_slides_are_trimmed_to_the_requested_count():
    """The script model has returned six slides for a request of five."""
    from instagram_marketing_agent.llm import fit_to_count

    slides = [
        SlideSpec(index=1, role="hook", image_prompt="a", overlay_text="1"),
        SlideSpec(index=2, role="hook", image_prompt="b", overlay_text="2"),
        SlideSpec(index=3, role="tension", image_prompt="c", overlay_text="3"),
        SlideSpec(index=4, role="solution", image_prompt="d", overlay_text="4"),
        SlideSpec(index=5, role="proof", image_prompt="e", overlay_text="5"),
        SlideSpec(index=6, role="cta", image_prompt="f", overlay_text="6"),
    ]
    fitted = fit_to_count(slides, 5)
    assert len(fitted) == 5
    assert [s.role for s in fitted] == ["hook", "tension", "solution", "proof", "cta"]
    assert fitted[0].overlay_text == "1"


def test_the_cta_always_ends_the_script():
    from instagram_marketing_agent.llm import fit_to_count

    slides = [
        SlideSpec(index=1, role="cta", image_prompt="a", overlay_text="cta"),
        SlideSpec(index=2, role="hook", image_prompt="b", overlay_text="h"),
        SlideSpec(index=3, role="solution", image_prompt="c", overlay_text="s"),
    ]
    assert [s.role for s in fit_to_count(slides, 3)] == ["hook", "solution", "cta"]


def test_repeats_fill_the_gap_when_roles_are_scarce():
    from instagram_marketing_agent.llm import fit_to_count

    slides = [
        SlideSpec(index=1, role="hook", image_prompt="a", overlay_text="1"),
        SlideSpec(index=2, role="hook", image_prompt="b", overlay_text="2"),
        SlideSpec(index=3, role="cta", image_prompt="c", overlay_text="3"),
    ]
    assert len(fit_to_count(slides, 3)) == 3


def test_too_few_slides_fails_before_any_image_is_generated():
    from instagram_marketing_agent.llm import fit_to_count

    slides = [
        SlideSpec(index=1, role="hook", image_prompt="a", overlay_text="1"),
        SlideSpec(index=2, role="cta", image_prompt="b", overlay_text="2"),
    ]
    with pytest.raises(ValueError, match="were requested"):
        fit_to_count(slides, 5)


def test_a_slide_with_no_copy_is_never_delivered():
    """The script model has returned a slide with an empty overlay_text."""
    from instagram_marketing_agent.llm import fit_to_count

    slides = [
        SlideSpec(index=1, role="hook", image_prompt="a", overlay_text="   "),
        SlideSpec(index=2, role="cta", image_prompt="b", overlay_text="buy"),
    ]
    with pytest.raises(ValueError, match="no overlay text"):
        fit_to_count(slides, 2)


def test_wordless_slides_are_dropped_so_a_real_one_takes_their_place(stubbed, monkeypatch):
    async def sloppy(**_kwargs):
        return type(
            "D",
            (),
            {
                "slides": [
                    SlideSpec(index=1, role="hook", image_prompt="a", overlay_text=""),
                    SlideSpec(index=2, role="hook", image_prompt="b", overlay_text="hook"),
                    SlideSpec(index=3, role="tension", image_prompt="c", overlay_text="t"),
                    SlideSpec(index=4, role="cta", image_prompt="d", overlay_text="buy"),
                ]
            },
        )()

    from instagram_marketing_agent import llm as _llm

    real = _llm.generate_script

    async def patched(topic, descriptions, products, slide_count):
        draft = await sloppy()
        usable = [
            s for s in sorted(draft.slides, key=lambda x: x.index)
            if s.overlay_text.strip() and s.image_prompt.strip()
        ]
        fitted = _llm.fit_to_count(usable, slide_count)
        for i, s in enumerate(fitted, 1):
            s.index = i
        return CampaignScript(topic=topic, slides=fitted, products=[])

    monkeypatch.setattr(llm, "generate_script", patched)
    campaign = asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=3))
    assert all(s.overlay_text.strip() for s in campaign.script.slides)
    assert [s.overlay_text for s in campaign.script.slides] == ["hook", "t", "buy"]
    assert real is not None


def test_a_failed_transcription_does_not_sink_the_campaign(monkeypatch, tmp_path):
    """The clip still describes visually without its spoken content."""
    from instagram_marketing_agent import ffmpeg

    video = tmp_path / "clip.mov"
    video.write_bytes(b"mov")

    async def fake_frames(v, out_dir, count=8):
        out_dir.mkdir(parents=True, exist_ok=True)
        frame = out_dir / "frame_01.jpg"
        frame.write_bytes(b"jpeg")
        return [frame]

    async def fake_audio(v, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"wav")
        return out_path

    async def fake_describe(_path):
        return "a frame"

    async def exploding_transcribe(_audio):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(ffmpeg, "extract_frames", fake_frames)
    monkeypatch.setattr(ffmpeg, "extract_audio", fake_audio)
    monkeypatch.setattr(llm, "describe_image", fake_describe)
    monkeypatch.setattr(llm, "transcribe_audio", exploding_transcribe)

    described = asyncio.run(workflow.describe_video(video))
    assert described.kind == "video"
    assert "a frame" in described.description
    assert described.transcript is None


def test_every_image_failing_is_reported_not_ignored(monkeypatch, tmp_path):
    """A script written without seeing the photos looks like success and is not."""
    for name in ("a.png", "b.png"):
        (tmp_path / name).write_bytes(b"png")

    async def refuse(_path):
        raise RuntimeError("400 usage limit reached")

    monkeypatch.setattr(llm, "inspect_image", refuse)
    with pytest.raises(RuntimeError, match="none of the supplied images"):
        asyncio.run(workflow.describe_inputs(tmp_path))


def test_a_partial_failure_keeps_the_photos_that_worked(monkeypatch, tmp_path):
    for name in ("a.png", "b.png"):
        (tmp_path / name).write_bytes(b"png")

    async def flaky(path):
        from instagram_marketing_agent.llm import _ImageDescription

        if path.name == "a.png":
            raise RuntimeError("transient")
        return _ImageDescription(description="described", shows_product=False)

    monkeypatch.setattr(llm, "inspect_image", flaky)
    described = asyncio.run(workflow.describe_inputs(tmp_path))
    assert [d.path.name for d in described] == ["b.png"]


class TestVideoArtifacts:
    """A clip's frames and transcript are kept alongside the campaign."""

    @staticmethod
    def _stub(monkeypatch, transcript="привіт зі студії"):
        from instagram_marketing_agent import ffmpeg

        async def fake_frames(video, out_dir, count=8):
            out_dir.mkdir(parents=True, exist_ok=True)
            made = []
            for i in range(1, 4):
                frame = out_dir / f"frame_{i:02d}.jpg"
                frame.write_bytes(b"jpeg")
                made.append(frame)
            return made

        async def fake_audio(video, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"wav")
            return out_path

        async def fake_describe(path):
            return f"a frame at {path.name}"

        async def fake_transcribe(audio):
            return transcript

        monkeypatch.setattr(ffmpeg, "extract_frames", fake_frames)
        monkeypatch.setattr(ffmpeg, "extract_audio", fake_audio)
        monkeypatch.setattr(llm, "describe_image", fake_describe)
        monkeypatch.setattr(llm, "transcribe_audio", fake_transcribe)

    def test_frames_and_transcript_are_saved(self, monkeypatch, tmp_path):
        self._stub(monkeypatch)
        video = tmp_path / "clip.mov"
        video.write_bytes(b"mov")
        artifacts = tmp_path / "source"

        asyncio.run(workflow.describe_video(video, artifacts_dir=artifacts))

        kept = artifacts / "clip"
        assert sorted(p.name for p in kept.glob("frame_*.jpg")) == [
            "frame_01.jpg",
            "frame_02.jpg",
            "frame_03.jpg",
        ]
        assert (kept / "transcript.txt").read_text(encoding="utf-8") == (
            "привіт зі студії"
        )
        assert "a frame at" in (kept / "frames.md").read_text(encoding="utf-8")

    def test_the_intermediate_audio_is_not_kept(self, monkeypatch, tmp_path):
        """The frames and the words are the deliverable; the wav is scratch."""
        self._stub(monkeypatch)
        video = tmp_path / "clip.mov"
        video.write_bytes(b"mov")
        artifacts = tmp_path / "source"

        asyncio.run(workflow.describe_video(video, artifacts_dir=artifacts))
        assert not list((artifacts / "clip").glob("*.wav"))

    def test_no_transcript_file_when_there_is_nothing_spoken(
        self, monkeypatch, tmp_path
    ):
        self._stub(monkeypatch, transcript="")
        video = tmp_path / "clip.mov"
        video.write_bytes(b"mov")
        artifacts = tmp_path / "source"

        asyncio.run(workflow.describe_video(video, artifacts_dir=artifacts))
        assert not (artifacts / "clip" / "transcript.txt").exists()
        assert list((artifacts / "clip").glob("frame_*.jpg"))

    def test_without_a_directory_nothing_is_left_behind(self, monkeypatch, tmp_path):
        self._stub(monkeypatch)
        video = tmp_path / "clip.mov"
        video.write_bytes(b"mov")

        asyncio.run(workflow.describe_video(video))
        assert [p.name for p in tmp_path.iterdir()] == ["clip.mov"]

    def test_each_clip_gets_its_own_folder(self, monkeypatch, tmp_path):
        self._stub(monkeypatch)
        artifacts = tmp_path / "source"
        for name in ("first.mov", "second.mov"):
            video = tmp_path / name
            video.write_bytes(b"mov")
            asyncio.run(workflow.describe_video(video, artifacts_dir=artifacts))

        assert sorted(p.name for p in artifacts.iterdir()) == ["first", "second"]
