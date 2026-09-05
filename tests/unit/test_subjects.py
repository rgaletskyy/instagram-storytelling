"""Subjects come from photographs, not from words.

The prompt carries the scene. Who and what is in it comes from real reference
images, because a subject described in words is a subject the model reinvents --
a different dog, a different owner, a fictional label.
"""

import asyncio
from pathlib import Path

import pytest

from instagram_marketing_agent import llm, workflow
from instagram_marketing_agent.config import REFERENCE_LIMIT
from instagram_marketing_agent.models import MediaDescription, SlideSpec

pytestmark = pytest.mark.unit


def _still(path, **flags):
    return MediaDescription(
        path=Path(path), kind="image", description="d", **flags
    )


class TestSelection:
    def test_each_subject_draws_its_own_photo(self):
        refs = workflow.SubjectReferences(
            product=[Path("p.jpg")], dog=[Path("d.jpg")], person=[Path("h.jpg")]
        )
        assert refs.for_slide(True, True, True) == [
            Path("p.jpg"),
            Path("d.jpg"),
            Path("h.jpg"),
        ]

    def test_only_the_subjects_present_are_attached(self):
        refs = workflow.SubjectReferences(
            product=[Path("p.jpg")], dog=[Path("d.jpg")], person=[Path("h.jpg")]
        )
        assert refs.for_slide(False, True, False) == [Path("d.jpg")]
        assert refs.for_slide(True, False, False) == [Path("p.jpg")]

    def test_one_photo_serving_two_subjects_is_attached_once(self):
        both = Path("dog_with_owner.jpg")
        refs = workflow.SubjectReferences(dog=[both], person=[both])
        assert refs.for_slide(False, True, True) == [both]

    def test_the_number_of_references_is_capped(self):
        refs = workflow.SubjectReferences(
            product=[Path(f"p{i}.jpg") for i in range(5)],
            dog=[Path(f"d{i}.jpg") for i in range(5)],
            person=[Path(f"h{i}.jpg") for i in range(5)],
        )
        assert len(refs.for_slide(True, True, True)) <= REFERENCE_LIMIT

    def test_nothing_is_attached_when_no_subject_is_in_frame(self):
        refs = workflow.SubjectReferences(dog=[Path("d.jpg")])
        assert refs.for_slide(False, False, False) == []


class TestGathering:
    def test_stills_supply_the_subjects_they_show(self):
        described = [
            _still("packshot.jpg", shows_product=True),
            _still("dog.jpg", shows_dog=True),
            _still("owner.jpg", shows_person=True),
        ]
        refs = asyncio.run(workflow.subject_references(described))
        assert refs.product == [Path("packshot.jpg")]
        assert refs.dog == [Path("dog.jpg")]
        assert refs.person == [Path("owner.jpg")]

    def test_video_frames_fill_a_missing_subject(self, monkeypatch, tmp_path):
        """Frames show the real dog and owner and are already on disk."""
        frames = []
        for i in range(2):
            frame = tmp_path / f"frame_{i}.jpg"
            frame.write_bytes(b"jpeg")
            frames.append(frame)

        async def looks(path):
            return llm._ImageDescription(
                description="d", shows_product=False, shows_dog=True,
                shows_person=path.name == "frame_1.jpg",
            )

        monkeypatch.setattr(llm, "inspect_image", looks)
        described = [
            MediaDescription(
                path=tmp_path / "clip.mov",
                kind="video",
                description="d",
                frames=frames,
            )
        ]
        refs = asyncio.run(workflow.subject_references(described))
        assert frames[0] in refs.dog
        assert frames[1] in refs.person

    def test_frames_are_not_inspected_when_stills_already_cover_it(
        self, monkeypatch, tmp_path
    ):
        """Inspecting a frame is an API call; skip it when nothing is missing."""
        called = []

        async def looks(path):
            called.append(path)
            return llm._ImageDescription(description="d", shows_product=False)

        monkeypatch.setattr(llm, "inspect_image", looks)
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"jpeg")
        described = [
            _still("dog.jpg", shows_dog=True),
            _still("owner.jpg", shows_person=True),
            MediaDescription(
                path=tmp_path / "c.mov", kind="video", description="d",
                frames=[frame],
            ),
        ]
        asyncio.run(workflow.subject_references(described))
        assert called == []

    def test_a_failed_frame_inspection_is_skipped(self, monkeypatch, tmp_path):
        async def refuse(path):
            raise RuntimeError("429")

        monkeypatch.setattr(llm, "inspect_image", refuse)
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"jpeg")
        described = [
            MediaDescription(
                path=tmp_path / "c.mov", kind="video", description="d",
                frames=[frame],
            )
        ]
        refs = asyncio.run(workflow.subject_references(described))
        assert refs.dog == [] and refs.person == []


class TestPromptContract:
    def test_the_fidelity_rule_covers_all_three_subjects(self):
        rule = llm.SUBJECT_FIDELITY_RULE
        assert "same individual animal" in rule
        assert "same individual" in rule
        assert "label artwork" in rule

    def test_the_script_prompt_forbids_describing_the_subjects(self):
        import inspect

        source = inspect.getsource(llm.generate_script)
        assert "SCENE ONLY" in source
        assert "no breed, coat colour, eye colour" in source

    def test_a_dog_slide_attaches_the_dog_photo(self, monkeypatch, tmp_path):
        attached = []

        async def fake_image(prompt, out_path, model=None, references=None,
                             aspect_ratio=None):
            attached.append(references)
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"jpeg")
            return path

        async def fake_html(slide, background, issues=None, fmt=None):
            return "<html></html>"

        async def fake_shot(html, out_path, base_dir, fmt=None):
            Path(out_path).write_bytes(b"slide")
            return Path(out_path)

        from instagram_marketing_agent import slide_html

        monkeypatch.setattr(llm, "generate_image", fake_image)
        monkeypatch.setattr(llm, "generate_slide_html", fake_html)
        monkeypatch.setattr(slide_html, "screenshot", fake_shot)

        subjects = workflow.SubjectReferences(dog=[Path("dog.jpg")])
        slide = SlideSpec(
            index=1, role="hook", image_prompt="a bench in a garden",
            overlay_text="copy", has_dog=True,
        )
        asyncio.run(
            workflow._build_slide(
                slide, tmp_path, "model", subjects=subjects
            )
        )
        assert attached[0] == [Path("dog.jpg")]


class TestPackshotsOverrideFrames:
    """A catalogue packshot is authoritative for the packaging.

    It is shot straight with the label sharp and complete; a video frame catches
    a bottle at an angle, half out of focus or partly out of shot.
    """

    def test_a_packshot_outranks_a_still(self):
        described = [_still("input_bottle.jpg", shows_product=True)]
        refs = asyncio.run(
            workflow.subject_references(described, packshots=[Path("sku.png")])
        )
        assert refs.product[0] == Path("sku.png")

    def test_a_frame_is_never_used_as_a_product_when_a_packshot_exists(
        self, monkeypatch, tmp_path
    ):
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"jpeg")

        async def looks(path):
            return llm._ImageDescription(
                description="d", shows_product=True, shows_dog=True
            )

        monkeypatch.setattr(llm, "inspect_image", looks)
        described = [
            MediaDescription(
                path=tmp_path / "c.mov", kind="video", description="d",
                frames=[frame],
            )
        ]
        refs = asyncio.run(
            workflow.subject_references(described, packshots=[Path("sku.png")])
        )
        assert refs.product == [Path("sku.png")]
        # The frame is still good enough to stand in for the dog.
        assert frame in refs.dog

    def test_a_frame_supplies_the_product_when_no_packshot_exists(
        self, monkeypatch, tmp_path
    ):
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"jpeg")

        async def looks(path):
            return llm._ImageDescription(description="d", shows_product=True)

        monkeypatch.setattr(llm, "inspect_image", looks)
        described = [
            MediaDescription(
                path=tmp_path / "c.mov", kind="video", description="d",
                frames=[frame],
            )
        ]
        refs = asyncio.run(workflow.subject_references(described, packshots=[]))
        assert refs.product == [frame]

    def test_every_named_sku_supplies_a_packshot(self, monkeypatch, tmp_path):
        from instagram_marketing_agent.models import Product

        products = [
            Product(sku=f"SKU-{i}", name=f"P{i}", image_url="https://x/i.png")
            for i in range(3)
        ]
        monkeypatch.setattr(
            workflow,
            "download_product_image",
            lambda p, d: Path(f"{p.sku}.png"),
        )
        shots = workflow.catalogue_packshots(products, tmp_path)
        assert shots == [Path("SKU-0.png"), Path("SKU-1.png"), Path("SKU-2.png")]

    def test_a_sku_with_no_photo_is_skipped_not_faked(self, monkeypatch, tmp_path):
        from instagram_marketing_agent.models import Product

        products = [
            Product(sku="HAS", name="p", image_url="https://x/i.png"),
            Product(sku="NONE", name="p", image_url=""),
        ]
        monkeypatch.setattr(
            workflow,
            "download_product_image",
            lambda p, d: Path("has.png") if p.image_url else None,
        )
        assert workflow.catalogue_packshots(products, tmp_path) == [Path("has.png")]


class TestMultipleProducts:
    def test_a_scene_with_three_bottles_gets_three_packshots(self):
        refs = workflow.SubjectReferences(
            product=[Path(f"p{i}.png") for i in range(3)], dog=[Path("d.jpg")]
        )
        attached = refs.for_slide(True, True, False)
        assert attached[:3] == [Path("p0.png"), Path("p1.png"), Path("p2.png")]
        assert Path("d.jpg") in attached

    def test_the_model_is_told_they_are_different_products(self):
        rule = llm.SUBJECT_FIDELITY_RULE
        assert "DIFFERENT" in rule
        assert "Do not copy one label onto all of them" in rule


def test_packshots_are_kept_beside_the_video_frames(monkeypatch, tmp_path):
    """Provenance: what a slide's packaging was copied from stays readable."""
    import inspect

    source = inspect.getsource(workflow.create_campaign)
    assert '"source" / "packshots"' in source
