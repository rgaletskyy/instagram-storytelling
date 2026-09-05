"""Command line entry point -- the programmatic path, no MCP involved."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import (
    DEFAULT_LIFESTYLE_IMAGES,
    DEFAULT_SLIDES,
    FORMATS,
    INPUT_DIR,
    STORY_FORMAT,
)
from .ffmpeg import FFmpegMissingError
from .workflow import create_campaign, create_lifestyle_content, verify_content


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
    planned = result["images_per_product"] * len(result["sets"])
    print(f"images: {len(result['images'])}/{planned}")
    for one in result["sets"]:
        label = one["sku"] or "no SKU"
        print(f"  {label}: {len(one['images'])} images")
        if one["packshot"] is None:
            print("    warning: no product photo; the packaging may be invented")
    if result["missing_skus"]:
        print(f"SKUs not in the catalogue: {', '.join(result['missing_skus'])}")
    for v in result["verdicts"]:
        if not v["passed"]:
            print(f"frame {v['index']} flagged: {'; '.join(v['issues'])}")
    for index, error in result["failed_images"]:
        print(f"frame {index} failed: {error}", file=sys.stderr)
    return 0


def _run_verify(args) -> int:
    """Review finished content somebody else made, instead of generating any."""
    try:
        reviews = asyncio.run(
            verify_content(Path(args.verify_content), args.format)
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    issues = suggestions = 0
    for review in reviews:
        print(f"\n{review.file}" + (f"  [{review.format}]" if review.format else ""))
        if review.error:
            print(f"  not reviewed: {review.error}")
        elif not review.findings:
            print("  nothing to change")
        for finding in review.findings:
            rule = f"  ({finding.rule})" if finding.rule else ""
            print(f"  {finding.kind}: {finding.detail}{rule}")
            if finding.kind == "issue":
                issues += 1
            else:
                suggestions += 1
    print(f"\n{issues} issues, {suggestions} suggestions across {len(reviews)} reviews")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="instagram-marketing-agent",
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
        help=f"generate N lifestyle images per product in the brief, instead "
        f"of a campaign (default {DEFAULT_LIFESTYLE_IMAGES})",
    )
    parser.add_argument(
        "--verify-content",
        nargs="?",
        const=str(INPUT_DIR),
        default=None,
        metavar="DIR",
        help=f"review the finished slides or posts in DIR against the brand "
        f"rules and print what to fix, instead of generating anything "
        f"(default {INPUT_DIR})",
    )
    parser.add_argument(
        "--format",
        choices=sorted(FORMATS),
        # No default: --verify-content reads the artboard off each image, and a
        # default here would silently force every one of them to story.
        default=None,
        help="story = 1080x1920 (9:16), post = 1080x1080 (1:1). Generating "
        f"defaults to {STORY_FORMAT.name}; reviewing reads it off each image",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the review of the finished slides",
    )
    args = parser.parse_args()

    if args.verify_content is not None:
        return _run_verify(args)

    if args.lifestyle is not None:
        return _run_lifestyle(args)

    try:
        campaign = asyncio.run(
            create_campaign(
                topic=args.topic,
                slide_count=args.slides,
                verify=not args.no_verify,
                fmt=FORMATS[args.format or STORY_FORMAT.name],
            )
        )
    except FFmpegMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"saved to {campaign.output_dir}  [{campaign.format_name}]")
    print(f"slides: {len(campaign.slide_paths)}/{len(campaign.script.slides)}")
    if campaign.missing_skus:
        print(f"SKUs not in the catalogue: {', '.join(campaign.missing_skus)}")
    for review in campaign.reviews:
        issues = [f.detail for f in review.findings if f.kind == "issue"]
        if issues:
            print(f"{review.file} flagged: {'; '.join(issues)}")
    if campaign.fixed_slides:
        fixed = ", ".join(str(i) for i in campaign.fixed_slides)
        print(f"laid out again to fix those: slide {fixed}")
    for index, error in campaign.failed_slides:
        print(f"slide {index} failed: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
