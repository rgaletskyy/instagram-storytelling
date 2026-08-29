"""ffmpeg is video-only now; slides render in a browser."""

import asyncio
from pathlib import Path

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


class TestFrameSampling:
    """Frames must be capped and spread across the whole clip."""

    @staticmethod
    def _capture(monkeypatch):
        """Record the ffmpeg arguments without running it."""
        calls = []

        async def fake_run(*args):
            calls.append(args)
            # Pretend ffmpeg wrote the frames it was asked for.
            out = Path(args[-1]).parent
            requested = int(args[args.index("-frames:v") + 1])
            for i in range(1, requested + 1):
                (out / f"frame_{i:02d}.jpg").write_bytes(b"jpeg")

        monkeypatch.setattr(ffmpeg, "_run", fake_run)
        return calls

    @pytest.mark.parametrize(
        "asked,expected",
        [(1, 5), (5, 5), (7, 7), (10, 10), (25, 10), (100, 10)],
    )
    def test_the_count_is_clamped_to_five_through_ten(
        self, monkeypatch, tmp_path, asked, expected
    ):
        self._capture(monkeypatch)
        monkeypatch.setattr(ffmpeg, "duration", lambda v: 60.0)
        frames = asyncio.run(
            ffmpeg.extract_frames(tmp_path / "v.mov", tmp_path / "out", asked)
        )
        assert len(frames) == expected

    def test_the_rate_is_derived_from_the_clip_length(self, monkeypatch, tmp_path):
        """A fixed rate samples only the opening seconds of a long clip."""
        calls = self._capture(monkeypatch)
        monkeypatch.setattr(ffmpeg, "duration", lambda v: 100.0)
        asyncio.run(ffmpeg.extract_frames(tmp_path / "v.mov", tmp_path / "out", 10))

        args = calls[0]
        rate = float(args[args.index("-vf") + 1].removeprefix("fps="))
        # 10 frames over 100 seconds is one every 10s, covering the whole clip.
        assert rate == pytest.approx(0.1)

    def test_a_longer_clip_gets_a_slower_rate(self, monkeypatch, tmp_path):
        rates = []
        calls = self._capture(monkeypatch)
        for seconds in (30.0, 300.0):
            calls.clear()
            monkeypatch.setattr(ffmpeg, "duration", lambda v, s=seconds: s)
            asyncio.run(
                ffmpeg.extract_frames(tmp_path / "v.mov", tmp_path / f"o{seconds}", 10)
            )
            args = calls[0]
            rates.append(float(args[args.index("-vf") + 1].removeprefix("fps=")))
        # Same frame count either way, so the longer clip samples more slowly.
        assert rates[0] > rates[1]

    def test_an_unknown_duration_falls_back_to_scene_changes(
        self, monkeypatch, tmp_path
    ):
        calls = self._capture(monkeypatch)
        monkeypatch.setattr(ffmpeg, "duration", lambda v: 0.0)
        asyncio.run(ffmpeg.extract_frames(tmp_path / "v.mov", tmp_path / "out", 10))
        args = calls[0]
        assert args[args.index("-vf") + 1] == "thumbnail"

    def test_duration_is_zero_when_ffprobe_is_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ffmpeg.shutil, "which", lambda _: None)
        monkeypatch.setattr(ffmpeg, "FFPROBE_BIN", "definitely-not-here")
        assert ffmpeg.duration(tmp_path / "v.mov") == 0.0
