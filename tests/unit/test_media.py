"""Preparing real phone media for the vision API."""

import io

import pytest
from PIL import Image

from instagram_marketing_agent.config import IMAGE_SUFFIXES
from instagram_marketing_agent.llm import _MAX_IMAGE_BYTES, _api_ready, _sniff

pytestmark = pytest.mark.unit


def _jpeg(size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, "JPEG")
    return buffer.getvalue()


def _png(size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "blue").save(buffer, "PNG")
    return buffer.getvalue()


def test_iphone_formats_are_accepted_as_input():
    assert {".heic", ".heif"} <= IMAGE_SUFFIXES


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"GIF89a", "image/gif"),
        (b"RIFF____WEBPVP8 ", "image/webp"),
        (b"not an image", ""),
    ],
)
def test_media_type_is_read_from_the_bytes(raw, expected):
    assert _sniff(raw) == expected


def test_a_jpeg_named_png_is_sent_as_jpeg(tmp_path):
    """Phone exports lie about their format; the API rejects a mismatch."""
    liar = tmp_path / "IMG_0001.PNG"
    liar.write_bytes(_jpeg())
    _data, media_type = _api_ready(liar)
    assert media_type == "image/jpeg"


def test_an_honest_png_is_passed_through_untouched(tmp_path):
    honest = tmp_path / "real.png"
    raw = _png()
    honest.write_bytes(raw)
    data, media_type = _api_ready(honest)
    assert media_type == "image/png"
    assert data == raw


def test_an_oversized_image_is_shrunk(tmp_path):
    big = tmp_path / "big.jpg"
    # Noise resists compression, so this lands over the API's per-image cap.
    import os

    Image.frombytes("RGB", (4000, 4000), os.urandom(4000 * 4000 * 3)).save(
        big, "JPEG", quality=100
    )
    assert big.stat().st_size > _MAX_IMAGE_BYTES

    data, media_type = _api_ready(big)
    assert media_type == "image/jpeg"
    assert len(data) < _MAX_IMAGE_BYTES
    with Image.open(io.BytesIO(data)) as im:
        assert max(im.size) <= 2000
