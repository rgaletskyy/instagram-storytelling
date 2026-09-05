"""Argument handling at the command line."""

import pytest

from instagram_marketing_agent import cli
from instagram_marketing_agent.config import INPUT_DIR, STORY_FORMAT
from instagram_marketing_agent.models import ContentFinding, ContentReview

pytestmark = pytest.mark.unit


@pytest.fixture
def review_calls(monkeypatch):
    """Capture what the CLI asks the reviewer for, without calling a model."""
    calls = []

    async def fake_verify(directory, format=None):
        calls.append((directory, format))
        return [
            ContentReview(
                file="1.jpg",
                format="story",
                findings=[
                    ContentFinding(
                        kind="issue", detail="copy sits under the reply field", rule="1.2"
                    ),
                    ContentFinding(kind="suggestion", detail="lead with the outcome"),
                ],
            ),
            ContentReview(file="(the set as a whole)"),
        ]

    monkeypatch.setattr(cli, "verify_content", fake_verify)
    return calls


def test_verify_content_defaults_to_the_input_folder(monkeypatch, review_calls, capsys):
    monkeypatch.setattr("sys.argv", ["prog", "--verify-content"])

    assert cli.main() == 0

    directory, fmt = review_calls[0]
    assert directory == INPUT_DIR
    # Nothing forced: each image's artboard is read off the picture.
    assert fmt is None
    out = capsys.readouterr().out
    assert "copy sits under the reply field  (1.2)" in out
    assert "nothing to change" in out
    assert "1 issues, 1 suggestions" in out


def test_verify_content_takes_a_folder_and_a_format(monkeypatch, review_calls, tmp_path):
    monkeypatch.setattr(
        "sys.argv", ["prog", "--verify-content", str(tmp_path), "--format", "post"]
    )

    assert cli.main() == 0
    assert review_calls[0] == (tmp_path, "post")


def test_a_folder_that_is_not_there_is_an_error(monkeypatch, capsys):
    async def missing(directory, format=None):
        raise FileNotFoundError(f"input folder not found: {directory}")

    monkeypatch.setattr(cli, "verify_content", missing)
    monkeypatch.setattr("sys.argv", ["prog", "--verify-content", "/nope"])

    assert cli.main() == 1
    assert "input folder not found" in capsys.readouterr().err


def test_generating_still_defaults_to_a_story(monkeypatch):
    """--format lost its default so review could auto-detect; a campaign kept it."""
    seen = {}

    async def fake_campaign(topic, slide_count, verify, fmt):
        seen["fmt"] = fmt
        raise ValueError("stop here -- the format is all this checks")

    monkeypatch.setattr(cli, "create_campaign", fake_campaign)
    monkeypatch.setattr("sys.argv", ["prog", "--slides", "5"])

    assert cli.main() == 1
    assert seen["fmt"] is STORY_FORMAT
