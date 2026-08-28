"""SKU extraction and catalogue parsing -- the parsing flagged as bug-prone."""

import pytest

from instagram_story_agent.config import TOPIC_FILE
from instagram_story_agent.products import extract_skus, get_products, strip_html

pytestmark = pytest.mark.unit


def test_extracts_sku_from_the_real_brief():
    skus = extract_skus(TOPIC_FILE.read_text(encoding="utf-8"))
    assert "BO-FIU150" in skus


def test_extracts_sku_from_parenthesised_text():
    assert extract_skus("новий продукт Face It up (BO-FIU150)") == ["BO-FIU150"]


def test_does_not_duplicate_repeated_skus():
    assert extract_skus("BO-FIU150 and again BO-FIU150") == ["BO-FIU150"]


def test_plain_uppercase_words_are_not_skus():
    assert extract_skus("THE DOG IS CLEAN") == []


def test_unmatched_candidates_are_reported_not_raised():
    found, missing = get_products(["NOPE-1"])
    assert found == []
    assert missing == ["NOPE-1"]


def test_lookup_is_case_insensitive_and_trimmed():
    found, missing = get_products(["  bo-fiu150 "])
    assert missing == []
    assert found[0].sku == "BO-FIU150"


def test_catalogue_row_is_fully_populated():
    found, _ = get_products(["BO-FIU150"])
    product = found[0]
    assert product.name
    assert product.price
    assert product.product_url.startswith("http")


def test_description_is_plain_text():
    found, _ = get_products(["BO-FIU150"])
    description = found[0].description
    assert description
    for fragment in ("&lt;", "&gt;", "&nbsp;", "<p>", "<strong>", "<br"):
        assert fragment not in description


def test_strip_html_unescapes_and_removes_tags():
    assert strip_html("&lt;p&gt;&lt;strong&gt;Hi&lt;/strong&gt;&amp;nbsp;there&lt;/p&gt;") == (
        "Hi there"
    )


def test_strip_html_handles_none():
    assert strip_html(None) == ""


def test_empty_sku_list_short_circuits():
    assert get_products([]) == ([], [])
