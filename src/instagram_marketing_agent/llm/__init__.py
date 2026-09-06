"""Model calls: Claude for understanding and writing, Gemini for imagery.

One import surface over the modules beside it, so callers keep saying
`llm.generate_script(...)` and a test keeps patching `llm.review_content`
wherever the call actually lives.

The underscored names are re-exported deliberately: they are internal to the
package but reached from workflow.py, image_index.py and the tests, and the
redundant `as` spelling is what marks a re-export rather than an oversight.
"""

from __future__ import annotations

from ..config import GEMINI_IMAGE_MODEL as GEMINI_IMAGE_MODEL
from .base import _MAX_IMAGE_BYTES as _MAX_IMAGE_BYTES
from .base import CAST_RULE, anthropic_client, gemini_client
from .base import _api_ready as _api_ready
from .base import _cast_check as _cast_check
from .base import _cast_clause as _cast_clause
from .base import _cast_failures as _cast_failures
from .base import _image_block as _image_block
from .base import _sniff as _sniff
from .describe import _ImageDescription as _ImageDescription
from .describe import describe_image, inspect_image, transcribe_audio
from .imagery import PRODUCT_FIDELITY_RULE, SUBJECT_FIDELITY_RULE, generate_image
from .lifestyle import generate_shot_list, verify_lifestyle_frame
from .script import fit_to_count, generate_script, revise_slide_spec
from .slides import _layout_rules as _layout_rules
from .slides import (
    format_for_image,
    generate_slide_html,
    review_content,
    review_content_sequence,
)

__all__ = [
    "CAST_RULE",
    "GEMINI_IMAGE_MODEL",
    "PRODUCT_FIDELITY_RULE",
    "SUBJECT_FIDELITY_RULE",
    "anthropic_client",
    "describe_image",
    "fit_to_count",
    "format_for_image",
    "gemini_client",
    "generate_image",
    "generate_script",
    "generate_shot_list",
    "generate_slide_html",
    "inspect_image",
    "review_content",
    "review_content_sequence",
    "revise_slide_spec",
    "transcribe_audio",
    "verify_lifestyle_frame",
]
