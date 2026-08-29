"""Lifestyle content: a set of frames, no script and no layout pass."""

import asyncio
import json

import pytest

from instagram_marketing_agent import llm, slide_html, workflow
from instagram_marketing_agent.config import LIFESTYLE_FORMAT, MAX_LIFESTYLE_IMAGES
from instagram_marketing_agent.models import (
    LifestyleSet,
    LifestyleShot,
    Product,
    SlideVerdict,
)

pytestmark = pytest.mark.unit

ROLES = ["hero", "in_use", "with_dog", "in_hand", "detail", "flat_lay"]


def _shots(count):
    return LifestyleSet(
        topic="тема",
        shots=[
            LifestyleShot(
                index=i,
                role=ROLES[(i - 1) % len(ROLES)],
                prompt=f"scene {i}",
                excludes="text overlays",
                has_human=i != 1,
            )
            for i in range(1, count + 1)
        ],
    )


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow, "OUTPUT_DIR", tmp_path)

    packshot = tmp_path / "packshot.png"
    packshot.write_bytes(b"png")

    async def fake_shot_list(topic, product, packshot_path, count):
        return _shots(count)

    async def fake_image(prompt, out_path, model=None, references=None,
                         aspect_ratio=None):
        from pathlib import Path

        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    async def fake_verify(image, shot, cast=""):
        return SlideVerdict(index=shot.index, passed=True)

    monkeypatch.setattr(llm, "generate_shot_list", fake_shot_list)
    monkeypatch.setattr(llm, "generate_image", fake_image)
    monkeypatch.setattr(llm, "verify_lifestyle_frame", fake_verify)
    monkeypatch.setattr(slide_html, "normalize", lambda p, fmt: p)
    monkeypatch.setattr(
        workflow,
        "get_products",
        lambda skus: (
            [Product(sku="ND-PAWS-01", name="Balm", image_url="https://x/i.png")],
            [],
        ),
    )
    monkeypatch.setattr(workflow, "download_product_image", lambda p, d: packshot)
    monkeypatch.setattr(workflow, "local_product_photos", lambda *a, **k: [])
    return tmp_path


def test_three_images_is_the_default(stubbed):
    result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))
    assert len(result["images"]) == 3


def test_the_requested_count_is_honoured(stubbed):
    result = asyncio.run(
        workflow.create_lifestyle_content(topic="тема", image_count=5)
    )
    assert len(result["images"]) == 5


@pytest.mark.parametrize("count", [0, -1, MAX_LIFESTYLE_IMAGES + 1])
def test_an_out_of_range_count_creates_nothing(stubbed, count):
    with pytest.raises(ValueError, match="image_count must be"):
        asyncio.run(
            workflow.create_lifestyle_content(topic="тема", image_count=count)
        )
    # Rejected before anything is generated: no project folder, no API calls.
    assert [p for p in stubbed.iterdir() if p.is_dir()] == []


def test_frames_are_named_by_sku_index_and_role(stubbed):
    result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))
    names = [p.rsplit("/", 1)[-1] for p in result["images"]]
    assert names == [
        "ND-PAWS-01-1-hero.jpg",
        "ND-PAWS-01-2-in_use.jpg",
        "ND-PAWS-01-3-with_dog.jpg",
    ]


def test_every_named_sku_gets_its_own_set(stubbed, monkeypatch):
    """`image_count` is per product: three SKUs at 3 each is nine frames."""
    monkeypatch.setattr(
        workflow,
        "get_products",
        lambda skus: (
            [
                Product(sku=f"SKU-{i}", name=f"P{i}", image_url="https://x/i.png")
                for i in range(1, 4)
            ],
            [],
        ),
    )
    result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))
    assert len(result["sets"]) == 3
    assert [s["sku"] for s in result["sets"]] == ["SKU-1", "SKU-2", "SKU-3"]
    assert len(result["images"]) == 9
    # Frames from different products must not collide on filename.
    assert len({p.rsplit("/", 1)[-1] for p in result["images"]}) == 9


def test_a_brief_with_no_sku_still_produces_a_set(stubbed, monkeypatch):
    monkeypatch.setattr(workflow, "get_products", lambda skus: ([], []))
    monkeypatch.setattr(workflow, "download_product_image", lambda p, d: None)
    result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))
    assert len(result["sets"]) == 1
    assert result["sets"][0]["sku"] is None
    assert len(result["images"]) == 3


def test_the_packshot_is_passed_to_every_frame(stubbed, monkeypatch):
    """A lifestyle frame without the real packshot invents the packaging."""
    seen = []

    async def recording(prompt, out_path, model=None, references=None,
                        aspect_ratio=None):
        from pathlib import Path

        seen.append((references, aspect_ratio))
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    monkeypatch.setattr(llm, "generate_image", recording)
    asyncio.run(workflow.create_lifestyle_content(topic="тема"))

    assert len(seen) == 3
    assert all(refs for refs, _ in seen)
    assert all(aspect == "4:5" for _, aspect in seen)


def test_the_set_falls_back_to_local_photos_without_a_url(stubbed, monkeypatch):
    """A sixth of the catalogue has no image URL, so this is an ordinary path."""
    local = stubbed / "local.png"
    local.write_bytes(b"png")
    monkeypatch.setattr(workflow, "download_product_image", lambda p, d: None)
    monkeypatch.setattr(workflow, "local_product_photos", lambda *a, **k: [local])

    result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))
    assert result["sets"][0]["packshot"] == str(local)


def test_a_rejected_frame_is_retried_with_the_defect_named(stubbed, monkeypatch):
    """Section 13 asks for a targeted correction, not a fresh scene."""
    prompts = []
    attempts = {"n": 0}

    async def recording(prompt, out_path, model=None, references=None,
                        aspect_ratio=None):
        from pathlib import Path

        if "scene 1" in prompt:
            prompts.append(prompt)
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    async def picky(image, shot, cast=""):
        if shot.index == 1:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return SlideVerdict(
                    index=1, passed=False, issues=["label text is garbled"]
                )
        return SlideVerdict(index=shot.index, passed=True)

    monkeypatch.setattr(llm, "generate_image", recording)
    monkeypatch.setattr(llm, "verify_lifestyle_frame", picky)
    asyncio.run(workflow.create_lifestyle_content(topic="тема"))

    assert len(prompts) == 2
    assert "label text is garbled" in prompts[1]
    assert "Keep everything" in prompts[1]


def test_a_frame_that_never_passes_is_kept_and_flagged(stubbed, monkeypatch):
    async def always_fail(image, shot, cast=""):
        return SlideVerdict(index=shot.index, passed=False, issues=["bad anatomy"])

    monkeypatch.setattr(llm, "verify_lifestyle_frame", always_fail)
    result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))

    assert len(result["images"]) == 3
    assert all(not v["passed"] for v in result["verdicts"])
    assert result["failed_images"] == []


def test_verification_can_be_skipped(stubbed, monkeypatch):
    async def boom(image, shot, cast=""):
        raise AssertionError("verifier must not run when verify=False")

    monkeypatch.setattr(llm, "verify_lifestyle_frame", boom)
    result = asyncio.run(
        workflow.create_lifestyle_content(topic="тема", verify=False)
    )
    assert result["verdicts"] == []


def test_the_shot_list_is_saved_beside_the_frames(stubbed):
    result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))
    saved = json.loads(
        (stubbed / result["output_dir"].rsplit("/", 1)[-1] / "shots.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["format"] == "lifestyle"
    assert len(saved["sets"][0]["shots"]["shots"]) == 3


def test_the_lifestyle_format_carries_no_safe_band():
    """Copy is applied later in design, so there is nothing to keep clear of."""
    assert LIFESTYLE_FORMAT.aspect_ratio == "4:5"
    assert (LIFESTYLE_FORMAT.width, LIFESTYLE_FORMAT.height) == (1080, 1350)
    assert LIFESTYLE_FORMAT.safe_top == 0
    assert LIFESTYLE_FORMAT.safe_bottom == LIFESTYLE_FORMAT.height


class TestMissingPackshot:
    """A product with no real photo is skipped, not faked."""

    @staticmethod
    def _products(monkeypatch, *skus_with_url):
        def fake(skus):
            return (
                [
                    Product(
                        sku=sku,
                        name=sku,
                        image_url="https://x/i.png" if has_url else "",
                    )
                    for sku, has_url in skus_with_url
                ],
                [],
            )

        monkeypatch.setattr(workflow, "get_products", fake)

    def test_a_product_without_an_image_is_skipped(self, stubbed, monkeypatch):
        self._products(monkeypatch, ("HAS-1", True), ("NONE-1", False))
        monkeypatch.setattr(
            workflow,
            "download_product_image",
            lambda p, d: (stubbed / "packshot.png") if p.image_url else None,
        )
        result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))

        assert [s["sku"] for s in result["sets"]] == ["HAS-1"]
        assert [s["sku"] for s in result["skipped"]] == ["NONE-1"]
        assert len(result["images"]) == 3

    def test_the_reason_names_the_empty_catalogue_column(self, stubbed, monkeypatch):
        self._products(monkeypatch, ("HAS-1", True), ("NONE-1", False))
        monkeypatch.setattr(
            workflow,
            "download_product_image",
            lambda p, d: (stubbed / "packshot.png") if p.image_url else None,
        )
        result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))
        assert "no photo URL" in result["skipped"][0]["reason"]

    def test_a_failed_download_is_also_a_skip(self, stubbed, monkeypatch):
        self._products(monkeypatch, ("HAS-1", True), ("DEAD-1", True))
        monkeypatch.setattr(
            workflow,
            "download_product_image",
            lambda p, d: (stubbed / "packshot.png") if p.sku == "HAS-1" else None,
        )
        result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))
        assert [s["sku"] for s in result["skipped"]] == ["DEAD-1"]
        assert "could not be downloaded" in result["skipped"][0]["reason"]

    def test_every_product_missing_an_image_is_an_error(self, stubbed, monkeypatch):
        self._products(monkeypatch, ("NONE-1", False), ("NONE-2", False))
        monkeypatch.setattr(workflow, "download_product_image", lambda p, d: None)
        monkeypatch.setattr(workflow, "local_product_photos", lambda *a, **k: [])
        with pytest.raises(RuntimeError, match="no product image could be obtained"):
            asyncio.run(workflow.create_lifestyle_content(topic="тема"))

    def test_a_loose_input_photo_serves_a_single_product(self, stubbed, monkeypatch):
        """One SKU: the photo in content/input/ is unambiguously that product."""
        local = stubbed / "local.png"
        local.write_bytes(b"png")
        self._products(monkeypatch, ("ONLY-1", False))
        monkeypatch.setattr(workflow, "download_product_image", lambda p, d: None)
        monkeypatch.setattr(workflow, "local_product_photos", lambda *a, **k: [local])

        result = asyncio.run(workflow.create_lifestyle_content(topic="тема"))
        assert result["sets"][0]["packshot"] == str(local)
        assert result["skipped"] == []

    def test_a_loose_photo_is_not_spread_across_several_products(
        self, stubbed, monkeypatch
    ):
        """It cannot be attributed, and guessing puts the wrong label on a frame."""
        local = stubbed / "local.png"
        local.write_bytes(b"png")
        self._products(monkeypatch, ("NONE-1", False), ("NONE-2", False))
        monkeypatch.setattr(workflow, "download_product_image", lambda p, d: None)
        monkeypatch.setattr(workflow, "local_product_photos", lambda *a, **k: [local])

        with pytest.raises(RuntimeError, match="no product image could be obtained"):
            asyncio.run(workflow.create_lifestyle_content(topic="тема"))
