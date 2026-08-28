"""ffmpeg is video-only now; slides render in a browser."""

import pytest

from instagram_story_agent import ffmpeg

pytestmark = pytest.mark.unit


def test_missing_binary_is_reported_with_the_override_to_set(monkeypatch):
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _: None)
    monkeypatch.setattr(ffmpeg, "FFMPEG_BIN", "definitely-not-here")
    with pytest.raises(ffmpeg.FFmpegMissingError, match="STORY_FFMPEG"):
        ffmpeg.require_ffmpeg()


def test_missing_binary_message_explains_it_is_only_for_video(monkeypatch):
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _: None)
    monkeypatch.setattr(ffmpeg, "FFMPEG_BIN", "definitely-not-here")
    with pytest.raises(ffmpeg.FFmpegMissingError, match="video"):
        ffmpeg.require_ffmpeg()


def test_no_text_drawing_remains_in_the_ffmpeg_layer():
    """Slides are laid out in HTML; drawtext must not creep back in."""
    for gone in ("render_slide", "build_filter", "wrap_text"):
        assert not hasattr(ffmpeg, gone)
