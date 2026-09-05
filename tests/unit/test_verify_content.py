"""Reviewing finished slides a person made by hand."""

import io

import pytest
from PIL import Image

from instagram_marketing_agent import llm, workflow
from instagram_marketing_agent.llm import format_for_image
from instagram_marketing_agent.models import ContentFinding

pytestmark = pytest.mark.unit


def _image(path, size=(1080, 1920)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, "JPEG")
    path.write_bytes(buffer.getvalue())
    return path


class _Described:
    def __init__(self, description):
        self.description = description
        self.shows_product = False


@pytest.fixture
def reviewed(monkeypatch):
    """Stub the two model calls and record what they were asked about."""
    seen = {"images": [], "sequence": None}

    async def fake_inspect(path):
        return _Described(f"a description of {path.name}")

    async def fake_review(image, description, fmt):
        seen["images"].append((image.name, description, fmt.name))
        return [ContentFinding(kind="issue", detail=f"{image.name} is off-brand")]

    async def fake_sequence(descriptions):
        seen["sequence"] = descriptions
        return [ContentFinding(kind="suggestion", detail="open with the outcome")]

    monkeypatch.setattr(llm, "inspect_image", fake_inspect)
    monkeypatch.setattr(llm, "review_content", fake_review)
    monkeypatch.setattr(llm, "review_content_sequence", fake_sequence)
    return seen


async def test_every_image_in_the_folder_is_read_and_judged(tmp_path, reviewed):
    _image(tmp_path / "2-tension.jpg")
    _image(tmp_path / "1-hook.jpg")

    reviews = await workflow.verify_content(tmp_path)

    # Filename order, because that is the order the sequence rules are read in.
    assert [r.file for r in reviews[:2]] == ["1-hook.jpg", "2-tension.jpg"]
    assert reviewed["sequence"] == [
        "a description of 1-hook.jpg",
        "a description of 2-tension.jpg",
    ]
    assert reviews[0].description == "a description of 1-hook.jpg"
    assert reviews[0].findings[0].kind == "issue"


async def test_a_lone_post_is_not_judged_as_a_sequence(tmp_path, reviewed):
    """One image cannot breach an arc, so there is no set-level pass."""
    _image(tmp_path / "post.jpg", (1080, 1080))

    reviews = await workflow.verify_content(tmp_path)

    assert [r.file for r in reviews] == ["post.jpg"]
    assert reviewed["sequence"] is None
    assert reviewed["images"][0][2] == "post"


async def test_the_artboard_can_be_forced(tmp_path, reviewed):
    _image(tmp_path / "slide.jpg", (1080, 1920))

    await workflow.verify_content(tmp_path, format="post")

    assert reviewed["images"][0][2] == "post"


async def test_an_unknown_format_is_refused(tmp_path, reviewed):
    _image(tmp_path / "slide.jpg")
    with pytest.raises(ValueError, match="unknown format"):
        await workflow.verify_content(tmp_path, format="reel")


async def test_a_file_that_cannot_be_read_is_reported_not_dropped(
    tmp_path, monkeypatch, reviewed
):
    _image(tmp_path / "good.jpg")
    _image(tmp_path / "bad.jpg")

    async def half_broken(path):
        if path.name == "bad.jpg":
            raise RuntimeError("vision API said no")
        return _Described(f"a description of {path.name}")

    monkeypatch.setattr(llm, "inspect_image", half_broken)

    reviews = {r.file: r for r in await workflow.verify_content(tmp_path)}

    assert "vision API said no" in reviews["bad.jpg"].error
    assert reviews["bad.jpg"].findings == []
    assert reviews["good.jpg"].findings[0].kind == "issue"


async def test_a_single_file_can_be_reviewed(tmp_path, reviewed):
    """A folder is not required: one slide is a valid target."""
    reviews = await workflow.verify_content(_image(tmp_path / "slide.jpg"))

    assert [r.file for r in reviews] == ["slide.jpg"]
    assert reviewed["sequence"] is None


async def test_a_file_that_is_not_an_image_is_refused(tmp_path, reviewed):
    brief = tmp_path / "brief.md"
    brief.write_text("not a picture", encoding="utf-8")
    with pytest.raises(ValueError, match="not an image"):
        await workflow.verify_content(brief)


async def test_an_empty_folder_says_so(tmp_path, reviewed):
    with pytest.raises(ValueError, match="no images to review"):
        await workflow.verify_content(tmp_path)


async def test_a_missing_folder_says_so(tmp_path, reviewed):
    with pytest.raises(FileNotFoundError):
        await workflow.verify_content(tmp_path / "nowhere")


@pytest.mark.parametrize(
    "size,expected",
    [((1080, 1920), "story"), ((1080, 1080), "post"), ((1080, 1350), "lifestyle")],
)
def test_the_artboard_is_read_off_the_picture(tmp_path, size, expected):
    assert format_for_image(_image(tmp_path / "x.jpg", size)).name == expected
