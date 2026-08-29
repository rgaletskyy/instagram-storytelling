"""ffmpeg is video-only now; slides render in a browser."""

import asyncio
from pathlib import Path

import pytest

from instagram_marketing_agent import ffmpeg
from instagram_marketing_agent.config import MAX_VIDEO_FRAMES, MIN_VIDEO_FRAMES

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

    @pytest.mark.parametrize("asked", [1, 3, 25, 100])
    def test_a_count_outside_the_range_is_clamped(self, monkeypatch, tmp_path, asked):
        """Follows the configured bounds rather than a hardcoded number."""
        self._capture(monkeypatch)
        monkeypatch.setattr(ffmpeg, "duration", lambda v: 60.0)
        frames = asyncio.run(
            ffmpeg.extract_frames(tmp_path / "v.mov", tmp_path / "out", asked)
        )
        assert MIN_VIDEO_FRAMES <= len(frames) <= MAX_VIDEO_FRAMES
        assert len(frames) == min(max(asked, MIN_VIDEO_FRAMES), MAX_VIDEO_FRAMES)

    def test_a_count_inside_the_range_is_honoured(self, monkeypatch, tmp_path):
        self._capture(monkeypatch)
        monkeypatch.setattr(ffmpeg, "duration", lambda v: 60.0)
        asked = MIN_VIDEO_FRAMES + 1
        frames = asyncio.run(
            ffmpeg.extract_frames(tmp_path / "v.mov", tmp_path / "out", asked)
        )
        assert len(frames) == asked

    def test_the_bounds_are_coherent(self):
        assert 1 <= MIN_VIDEO_FRAMES <= MAX_VIDEO_FRAMES <= 10

    def test_the_rate_is_derived_from_the_clip_length(self, monkeypatch, tmp_path):
        """A fixed rate samples only the opening seconds of a long clip."""
        calls = self._capture(monkeypatch)
        monkeypatch.setattr(ffmpeg, "duration", lambda v: 100.0)
        asyncio.run(
            ffmpeg.extract_frames(tmp_path / "v.mov", tmp_path / "out", MAX_VIDEO_FRAMES)
        )

        args = calls[0]
        rate = float(args[args.index("-vf") + 1].removeprefix("fps="))
        # The rate spreads the frames over the whole 100 seconds.
        assert rate == pytest.approx(MAX_VIDEO_FRAMES / 100.0)

    def test_a_longer_clip_gets_a_slower_rate(self, monkeypatch, tmp_path):
        rates = []
        calls = self._capture(monkeypatch)
        for seconds in (30.0, 300.0):
            calls.clear()
            monkeypatch.setattr(ffmpeg, "duration", lambda v, s=seconds: s)
            asyncio.run(
                ffmpeg.extract_frames(
                    tmp_path / "v.mov", tmp_path / f"o{seconds}", MAX_VIDEO_FRAMES
                )
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
        asyncio.run(
            ffmpeg.extract_frames(tmp_path / "v.mov", tmp_path / "out", MAX_VIDEO_FRAMES)
        )
        args = calls[0]
        assert args[args.index("-vf") + 1] == "thumbnail"

    def test_duration_is_zero_when_ffprobe_is_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ffmpeg.shutil, "which", lambda _: None)
        monkeypatch.setattr(ffmpeg, "FFPROBE_BIN", "definitely-not-here")
        assert ffmpeg.duration(tmp_path / "v.mov") == 0.0
