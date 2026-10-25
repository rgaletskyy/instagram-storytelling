"""generate_image and ImageGenerator, with the search API, the downloads and Gemini faked."""

import base64
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from PIL import Image as PILImage

from tools import generate_image as tool
from tools import image_generation_service
from tools.image_generation_service import (
    ImageGenerationError,
    ImageGenerator,
    Reference,
    direct_url,
)

SERVER = Path(__file__).resolve().parents[1] / "src" / "mcp-server.py"


def _server():
    spec = importlib.util.spec_from_file_location("mcp_server", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.mcp


def _png(size=(3000, 2000), mode="RGBA") -> bytes:
    out = io.BytesIO()
    PILImage.new(mode, size, (10, 20, 30, 0) if mode == "RGBA" else (10, 20, 30)).save(
        out, format="PNG"
    )
    return out.getvalue()


GENERATED = _png((40, 50), "RGB")


class FakeGemini:
    """Stands in for genai.Client; records the request and answers with GENERATED."""

    def __init__(self, image=GENERATED):
        self.requests = []
        self.image = image
        self.aio = SimpleNamespace(interactions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self.image is None:
            return SimpleNamespace(output_image=None, output_text="blocked by safety")
        return SimpleNamespace(
            output_image=SimpleNamespace(
                data=base64.b64encode(self.image).decode(), mime_type="image/png"
            )
        )


def _downloads(files: dict[str, httpx.Response]):
    """A transport answering each download URL from `files`, 404 otherwise."""

    def handler(request):
        return files.get(str(request.url), httpx.Response(404))

    return httpx.MockTransport(handler)


def _image(data=None, content_type="image/png"):
    return httpx.Response(200, content=data or _png(), headers={"content-type": content_type})


# --- ImageGenerator ---------------------------------------------------------


def test_drive_share_links_become_download_links():
    assert direct_url("https://drive.google.com/file/d/1-60DP34zLB3lP1/view?usp=drivesdk") == (
        "https://drive.usercontent.google.com/download?id=1-60DP34zLB3lP1&export=download"
    )
    assert direct_url("https://drive.google.com/open?id=abcdefghijkl") == (
        "https://drive.usercontent.google.com/download?id=abcdefghijkl&export=download"
    )
    assert direct_url("https://example.com/a.png") == "https://example.com/a.png"


async def test_a_download_is_shrunk_to_an_rgb_jpeg():
    generator = ImageGenerator(http_transport=_downloads({"https://x.test/a.png": _image()}))
    reference = await generator.download("https://x.test/a.png")
    picture = PILImage.open(io.BytesIO(reference.data))
    assert (picture.format, picture.mode) == ("JPEG", "RGB")
    assert max(picture.size) == image_generation_service.REFERENCE_MAX_SIDE


@pytest.mark.parametrize(
    ("url", "files", "message"),
    [
        ("http://x.test/a.png", {}, "only https"),
        ("https://x.test/a.png", {}, r"download failed \(404\)"),
        (
            "https://x.test/a.png",
            {"https://x.test/a.png": _image(b"<html>", "text/html")},
            "not an image",
        ),
        ("https://x.test/a.png", {"https://x.test/a.png": _image(b"junk")}, "not a readable image"),
    ],
)
async def test_unusable_downloads_are_refused(url, files, message):
    generator = ImageGenerator(http_transport=_downloads(files))
    with pytest.raises(ImageGenerationError, match=message):
        await generator.download(url)


async def test_generation_attaches_references_and_the_fidelity_rule():
    gemini = FakeGemini()
    image = await ImageGenerator(client=gemini).generate(
        "a dog in a bath", [Reference(url="u", data=b"jpeg")], "9:16"
    )
    assert image.data == GENERATED and image.mime_type == "image/png"
    request = gemini.requests[0]
    text, attached = request["input"]
    assert text["text"].startswith("a dog in a bath\n\n")
    assert "REAL subjects" in text["text"]
    assert attached == {
        "type": "image",
        "data": base64.b64encode(b"jpeg").decode(),
        "mime_type": "image/jpeg",
    }
    assert request["response_format"]["aspect_ratio"] == "9:16"


async def test_generation_without_references_sends_the_prompt_alone():
    gemini = FakeGemini()
    await ImageGenerator(client=gemini).generate("a dog", [], "1:1")
    assert gemini.requests[0]["input"] == "a dog"


async def test_no_image_from_gemini_is_an_error():
    with pytest.raises(ImageGenerationError, match="blocked by safety"):
        await ImageGenerator(client=FakeGemini(image=None)).generate("a dog")


async def test_a_missing_api_key_is_an_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ImageGenerationError, match="GEMINI_API_KEY"):
        await ImageGenerator().generate("a dog")


# --- the tool ---------------------------------------------------------------

DRIVE = "https://drive.google.com/file/d/{}/view?usp=drivesdk"
DOWNLOAD = "https://drive.usercontent.google.com/download?id={}&export=download"


@pytest.fixture
def world(monkeypatch):
    """Fakes the search API (by query), the downloads and Gemini."""
    state = {"searches": [], "gemini": FakeGemini(), "files": {}, "results": {}}

    async def post(path, body):
        assert path == "/searchcontent"
        state["searches"].append(body)
        return state["results"].get(body["query"], {})

    monkeypatch.setattr(tool.search_api, "post", post)
    monkeypatch.setattr(
        tool,
        "_generator",
        ImageGenerator(client=state["gemini"], http_transport=_downloads(state["files"])),
    )
    return state


async def _call(arguments):
    async with Client(_server()) as client:
        return await client.call_tool("generate_image", arguments, raise_on_error=True)


async def test_the_tool_is_listed_with_the_spec_parameters():
    async with Client(_server()) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert set(tools["generate_image"].input_schema["properties"]) == {
        "subject", "products", "contentType", "composition", "cameraLevel", "aspectRatio", "sampleUrls",
    }  # fmt: skip
    assert tools["generate_image"].input_schema["required"] == ["subject"]


async def test_a_sku_is_resolved_to_its_photos_and_the_image_returned(world):
    world["results"] = {
        "BTQ-1": {"products": [{"sku": "BTQ-1", "name": "Sensitive Skin Shampoo"}]},
        "Sensitive Skin Shampoo": {
            "content": [
                {"fileName": "shampoo.jpg", "product": "Sensitive Skin Shampoo", "driveUrl": DRIVE.format("aaaaaaaaaaaa")},
                {"fileName": "shampoo.mp4", "product": "Sensitive Skin Shampoo", "driveUrl": DRIVE.format("bbbbbbbbbbbb")},
                {"fileName": "other.jpg", "product": "Avocado Spray", "driveUrl": DRIVE.format("cccccccccccc")},
            ]
        },
    }  # fmt: skip
    world["files"][DOWNLOAD.format("aaaaaaaaaaaa")] = _image()

    result = await _call(
        {
            "subject": "a dog in a bath",
            "products": ["BTQ-1"],
            "contentType": "Lifestyle",
            "aspectRatio": "9:16",
        }
    )

    assert world["searches"][0] == {"query": "BTQ-1", "productSku": "BTQ-1", "type": "продуктове"}
    assert world["searches"][1] == {"query": "Sensitive Skin Shampoo", "type": "продуктове"}
    image = result.content[0]
    assert image.type == "image" and base64.b64decode(image.data) == GENERATED
    request = world["gemini"].requests[0]
    assert len(request["input"]) == 2  # the prompt and the one matching photo
    assert "Sensitive Skin Shampoo" in request["input"][0]["text"]
    assert "lifestyle" in request["input"][0]["text"]
    assert "'BTQ-1' is Sensitive Skin Shampoo." in result.content[1].text


async def test_a_product_without_photos_is_drawn_from_its_name(world):
    result = await _call({"subject": "a dog", "products": ["Avocado Spray"]})
    assert world["searches"] == [
        {"query": "Avocado Spray", "productSku": "Avocado Spray", "type": "продуктове"}
    ]
    assert world["gemini"].requests[0]["input"].startswith("a dog")
    assert "No photo of 'Avocado Spray'" in result.content[1].text


async def test_samples_are_attached(world):
    world["files"]["https://x.test/dog.png"] = _image()
    result = await _call({"subject": "a dog", "sampleUrls": ["https://x.test/dog.png"]})
    request = world["gemini"].requests[0]
    assert len(request["input"]) == 2
    assert request["response_format"]["aspect_ratio"] == "4:5"
    assert len(result.content) == 1


async def test_a_sample_that_cannot_be_downloaded_fails_the_call(world):
    with pytest.raises(ToolError, match="download failed"):
        await _call({"subject": "a dog", "sampleUrls": ["https://x.test/missing.png"]})
    assert world["gemini"].requests == []


async def test_an_empty_subject_is_refused(world):
    with pytest.raises(ToolError, match="subject"):
        await _call({"subject": "  "})
