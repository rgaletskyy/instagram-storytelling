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
    """One frame every N seconds is the only way frames come out of a clip."""

    @staticmethod
    def _capture(monkeypatch, frames=3):
        """Record the ffmpeg arguments without running it."""
        calls = []

        async def fake_run(*args):
            calls.append(args)
            out = Path(args[-1]).parent
            for i in range(1, frames + 1):
                (out / f"frame_{i:03d}.jpg").write_bytes(b"jpeg")

        monkeypatch.setattr(ffmpeg, "_run", fake_run)
        return calls

    def test_only_one_way_to_pull_frames_remains(self):
        """The fixed-count sampler is gone; callers divide a duration instead."""
        assert not hasattr(ffmpeg, "extract_frames")
        assert hasattr(ffmpeg, "extract_frames_every")

    @pytest.mark.parametrize("every,rate", [(5.0, "1/5"), (8.0, "1/8"), (0.5, "1/0.5")])
    def test_the_interval_becomes_the_frame_rate(self, monkeypatch, tmp_path, every, rate):
        calls = self._capture(monkeypatch)
        asyncio.run(ffmpeg.extract_frames_every(tmp_path / "v.mov", tmp_path / "o", every))

        args = calls[0]
        assert args[args.index("-vf") + 1] == f"fps={rate}"

    def test_frames_come_back_named_and_in_order(self, monkeypatch, tmp_path):
        """regenerate_slide finds a saved campaign's footage by this naming."""
        self._capture(monkeypatch, frames=4)
        frames = asyncio.run(
            ffmpeg.extract_frames_every(tmp_path / "v.mov", tmp_path / "o", 5.0)
        )
        assert [f.name for f in frames] == [
            "frame_001.jpg", "frame_002.jpg", "frame_003.jpg", "frame_004.jpg",
        ]

    @pytest.mark.parametrize("every", [0.0, -1.0])
    def test_an_interval_of_nothing_is_refused(self, monkeypatch, tmp_path, every):
        """fps=1/0 is not a filter; it is a hang or a division by zero."""
        self._capture(monkeypatch)
        with pytest.raises(ValueError, match="must be positive"):
            asyncio.run(
                ffmpeg.extract_frames_every(tmp_path / "v.mov", tmp_path / "o", every)
            )

    def test_the_bounds_are_coherent(self):
        assert 1 <= MIN_VIDEO_FRAMES <= MAX_VIDEO_FRAMES <= 10

    def test_duration_is_zero_when_ffprobe_is_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ffmpeg.shutil, "which", lambda _: None)
        monkeypatch.setattr(ffmpeg, "FFPROBE_BIN", "definitely-not-here")
        assert ffmpeg.duration(tmp_path / "v.mov") == 0.0
