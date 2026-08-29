"""One person across a set.

Slides and frames are generated independently, so without a shared description
each image invents its own owner -- different hands, sleeves and skin on every
slide of the same story.
"""

import asyncio

import pytest

from instagram_marketing_agent import llm, slide_html, workflow
from instagram_marketing_agent.models import (
    CampaignScript,
    LifestyleShot,
    SlideSpec,
    SlideVerdict,
)

pytestmark = pytest.mark.unit

CAST = "a woman in her 30s, fair skin, short unpainted nails, plain grey sleeve"


class TestCastInPrompts:
    def test_the_clause_names_the_one_person(self):
        clause = llm._cast_clause(CAST)
        assert CAST in clause
        assert "no second person" in clause.lower()

    def test_no_cast_adds_nothing(self):
        assert llm._cast_clause("") == ""
        assert llm._cast_clause("   ") == ""

    def test_the_script_prompt_demands_a_single_person(self):
        assert "Exactly ONE person" in llm.CAST_RULE
        assert "never a different owner" in llm.CAST_RULE.lower()


class TestCastInVerification:
    def test_the_reviewer_is_told_who_the_person_is(self):
        assert CAST in llm._cast_check(CAST)

    def test_a_contradicting_person_is_a_failure(self):
        failures = llm._cast_failures(CAST)
        assert "contradicts the description" in failures
        assert "more than one person" in failures

    def test_a_second_person_fails_even_with_no_cast_defined(self):
        """Consistency needs a cast; 'only one person' does not."""
        assert "more than one person" in llm._cast_failures("")


class TestCastReachesGeneration:
    @staticmethod
    def _stub(monkeypatch, tmp_path, cast=CAST, human=(2, 4)):
        prompts: dict[int, str] = {}
        seen_cast: list[str] = []

        monkeypatch.setattr(workflow, "OUTPUT_DIR", tmp_path)

        async def fake_script(**_kwargs):
            return CampaignScript(
                topic="тема",
                slides=[
                    SlideSpec(
                        index=i,
                        role=r,
                        image_prompt=f"scene {i}",
                        overlay_text=f"copy {i}",
                        has_human=i in human,
                    )
                    for i, r in enumerate(
                        ["hook", "tension", "solution", "proof", "cta"], 1
                    )
                ],
                cast=cast,
            )

        async def fake_image(prompt, out_path, model=None, references=None,
                             aspect_ratio=None):
            from pathlib import Path

            index = int(Path(out_path).parent.name.rsplit("_", 1)[1])
            prompts[index] = prompt
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"jpeg")
            return path

        async def fake_html(slide, background, issues=None, fmt=None):
            return "<html></html>"

        async def fake_shot(html, out_path, base_dir, fmt=None):
            from pathlib import Path

            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"slide")
            return path

        async def fake_verify(image, slide, fmt=None, cast=""):
            seen_cast.append(cast)
            return SlideVerdict(index=slide.index, passed=True)

        async def fake_inputs(_dir=None, artifacts_dir=None):
            return []

        monkeypatch.setattr(llm, "generate_script", fake_script)
        monkeypatch.setattr(llm, "generate_image", fake_image)
        monkeypatch.setattr(llm, "generate_slide_html", fake_html)
        monkeypatch.setattr(slide_html, "screenshot", fake_shot)
        monkeypatch.setattr(llm, "verify_slide", fake_verify)
        monkeypatch.setattr(workflow, "describe_inputs", fake_inputs)
        monkeypatch.setattr(workflow, "get_products", lambda skus: ([], []))
        return prompts, seen_cast

    def test_slides_with_a_human_carry_the_cast(self, monkeypatch, tmp_path):
        prompts, _ = self._stub(monkeypatch, tmp_path)
        asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
        for index in (2, 4):
            assert CAST in prompts[index], f"slide {index} lost the cast"

    def test_slides_without_a_human_do_not(self, monkeypatch, tmp_path):
        prompts, _ = self._stub(monkeypatch, tmp_path)
        asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
        for index in (1, 3, 5):
            assert CAST not in prompts[index]

    def test_every_human_slide_gets_the_same_person(self, monkeypatch, tmp_path):
        prompts, _ = self._stub(monkeypatch, tmp_path, human=(1, 2, 3, 4, 5))
        asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
        described = {p.split("The single person in this image is:")[1] for p in
                     prompts.values()}
        assert len(described) == 1, "slides describe different people"

    def test_the_verifier_receives_the_cast(self, monkeypatch, tmp_path):
        _, seen = self._stub(monkeypatch, tmp_path)
        asyncio.run(workflow.create_story_campaign(topic="тема", slide_count=5))
        assert seen and all(c == CAST for c in seen)


class TestLifestyleCast:
    def test_a_frame_with_a_human_carries_the_cast(self, monkeypatch, tmp_path):
        prompts: list[str] = []

        async def fake_image(prompt, out_path, model=None, references=None,
                             aspect_ratio=None):
            from pathlib import Path

            prompts.append(prompt)
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"jpeg")
            return path

        monkeypatch.setattr(llm, "generate_image", fake_image)
        monkeypatch.setattr(slide_html, "normalize", lambda p, fmt: p)
        shot = LifestyleShot(
            index=1, role="in_hand", prompt="hands holding it", has_human=True
        )
        asyncio.run(
            workflow._build_frame(shot, tmp_path, [], verify=False, cast=CAST)
        )
        assert CAST in prompts[0]

    def test_a_frame_without_a_human_does_not(self, monkeypatch, tmp_path):
        prompts: list[str] = []

        async def fake_image(prompt, out_path, model=None, references=None,
                             aspect_ratio=None):
            from pathlib import Path

            prompts.append(prompt)
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"jpeg")
            return path

        monkeypatch.setattr(llm, "generate_image", fake_image)
        monkeypatch.setattr(slide_html, "normalize", lambda p, fmt: p)
        shot = LifestyleShot(
            index=1, role="hero", prompt="on a shelf", has_human=False
        )
        asyncio.run(
            workflow._build_frame(shot, tmp_path, [], verify=False, cast=CAST)
        )
        assert CAST not in prompts[0]
