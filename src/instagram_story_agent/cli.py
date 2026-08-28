"""Command line entry point -- the programmatic path, no MCP involved."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .config import DEFAULT_SLIDES
from .ffmpeg import FFmpegMissingError
from .workflow import create_story_campaign


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="instagram-story-agent",
        description="Build an Instagram story campaign from content/input/.",
    )
    parser.add_argument(
        "--slides", type=int, default=DEFAULT_SLIDES, help="number of slides (3-7)"
    )
    parser.add_argument(
        "--topic", default=None, help="override content/input/topic.md"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the design verification pass on each rendered slide",
    )
    args = parser.parse_args()

    try:
        campaign = asyncio.run(
            create_story_campaign(
                topic=args.topic,
                slide_count=args.slides,
                verify=not args.no_verify,
            )
        )
    except FFmpegMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"saved to {campaign.output_dir}")
    print(f"slides: {len(campaign.slide_paths)}/{len(campaign.script.slides)}")
    if campaign.missing_skus:
        print(f"SKUs not in the catalogue: {', '.join(campaign.missing_skus)}")
    for verdict in campaign.verdicts:
        if not verdict.passed:
            print(f"slide {verdict.index} flagged: {'; '.join(verdict.issues)}")
    for index, error in campaign.failed_slides:
        print(f"slide {index} failed: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
