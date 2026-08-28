"""Command line entry point -- the programmatic path, no MCP involved."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .config import (
    DEFAULT_LIFESTYLE_IMAGES,
    DEFAULT_SLIDES,
    FORMATS,
    STORY_FORMAT,
)
from .ffmpeg import FFmpegMissingError
from .workflow import create_campaign, create_lifestyle_content


def _run_lifestyle(args) -> int:
    """Lifestyle images: no script, no layout, just frames."""
    try:
        result = asyncio.run(
            create_lifestyle_content(
                topic=args.topic,
                image_count=args.lifestyle,
                verify=not args.no_verify,
            )
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"saved to {result['output_dir']}  [lifestyle]")
    print(f"images: {len(result['images'])}/{len(result['shots']['shots'])}")
    if result["packshot"] is None:
        print("warning: no product photo found; the packaging may be invented")
    if result["missing_skus"]:
        print(f"SKUs not in the catalogue: {', '.join(result['missing_skus'])}")
    for v in result["verdicts"]:
        if not v["passed"]:
            print(f"frame {v['index']} flagged: {'; '.join(v['issues'])}")
    for index, error in result["failed_images"]:
        print(f"frame {index} failed: {error}", file=sys.stderr)
    return 0


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
        "--lifestyle",
        nargs="?",
        type=int,
        const=DEFAULT_LIFESTYLE_IMAGES,
        default=None,
        metavar="N",
        help=f"generate N lifestyle product images instead of a campaign "
        f"(default {DEFAULT_LIFESTYLE_IMAGES})",
    )
    parser.add_argument(
        "--format",
        choices=sorted(FORMATS),
        default=STORY_FORMAT.name,
        help="story = 1080x1920 (9:16), post = 1080x1080 (1:1)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the design verification pass on each rendered slide",
    )
    args = parser.parse_args()

    if args.lifestyle is not None:
        return _run_lifestyle(args)

    try:
        campaign = asyncio.run(
            create_campaign(
                topic=args.topic,
                slide_count=args.slides,
                verify=not args.no_verify,
                fmt=FORMATS[args.format],
            )
        )
    except FFmpegMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"saved to {campaign.output_dir}  [{campaign.format_name}]")
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
