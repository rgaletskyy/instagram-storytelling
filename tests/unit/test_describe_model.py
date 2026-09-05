"""Which model describes an input photo, and what DeepSeek's reply has to hold."""

import importlib
import io

import pytest
from PIL import Image

from instagram_marketing_agent import config, deepseek, llm
from instagram_marketing_agent.config import CLAUDE_DESCRIBE_MODEL

pytestmark = pytest.mark.unit

DEEPSEEK_VISION = "deepseek-v4-flash-vision-exp"


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "packshot.jpg"
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(buffer, "JPEG")
    path.write_bytes(buffer.getvalue())
    return path


def test_the_description_model_comes_from_the_environment(monkeypatch):
    """Set it before a run and the description pass moves, with no code change.

    Only this direction is testable in-process: the fallback to
    CLAUDE_DESCRIBE_MODEL needs a repo with no DESCRIBE_MODEL in .env, and
    reloading the module reads the real one.
    """
    monkeypatch.setenv("DESCRIBE_MODEL", DEEPSEEK_VISION)
    # The constant is resolved at import, so the module has to be read again.
    reloaded = importlib.reload(config)
    assert reloaded.DESCRIBE_MODEL == DEEPSEEK_VISION
    assert reloaded.CLAUDE_DESCRIBE_MODEL == CLAUDE_DESCRIBE_MODEL


def teardown_module():
    """Leave the process holding the real .env value, not a test's."""
    importlib.reload(config)


async def test_a_deepseek_id_routes_to_deepseek(monkeypatch, photo):
    sent = {}

    async def fake(model, image, media_type, prompt, max_tokens=4000):
        sent.update(model=model, media_type=media_type, prompt=prompt)
        return {
            "description": "a red bottle on a table",
            "shows_product": True,
            "shows_person": False,
        }

    monkeypatch.setattr(llm, "DESCRIBE_MODEL", DEEPSEEK_VISION)
    monkeypatch.setattr(deepseek, "describe_json", fake)

    described = await llm.inspect_image(photo)

    assert sent["model"] == DEEPSEEK_VISION
    assert sent["media_type"] == "image/jpeg"
    # JSON mode only engages when the prompt says "json".
    assert "json" in sent["prompt"]
    assert described.description == "a red bottle on a table"
    assert described.shows_product is True
    assert described.shows_dog is False


async def test_a_reply_with_no_description_fails_the_run(monkeypatch, photo):
    """Rather than a blank description with every reference flag dropped."""

    async def fake(model, image, media_type, prompt, max_tokens=4000):
        return {"shows_product": True}

    monkeypatch.setattr(llm, "DESCRIBE_MODEL", DEEPSEEK_VISION)
    monkeypatch.setattr(deepseek, "describe_json", fake)

    with pytest.raises(RuntimeError, match="no description"):
        await llm.inspect_image(photo)


@pytest.mark.parametrize(
    "reply",
    [
        '{"description": "a dog"}',
        '```json\n{"description": "a dog"}\n```',
        'Here you go:\n{"description": "a dog"}\n',
    ],
)
def test_the_json_object_is_unwrapped(reply):
    assert deepseek._json_object(reply, DEEPSEEK_VISION) == {"description": "a dog"}


@pytest.mark.parametrize("reply", ["", "I cannot see an image."])
def test_a_reply_that_is_not_json_says_which_model_sent_it(reply):
    with pytest.raises(RuntimeError, match=DEEPSEEK_VISION):
        deepseek._json_object(reply, DEEPSEEK_VISION)


def test_a_missing_key_names_the_setting_that_asked_for_it(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(deepseek, "load_dotenv", lambda: None)
    with pytest.raises(RuntimeError, match="DESCRIBE_MODEL"):
        deepseek.api_key()
