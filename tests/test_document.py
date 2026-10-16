import pytest

from rupa.document import InputError, parse

SAMPLE = """---
title: Sample
author: Vajra Sarpa
---

## First section

Hello **world**.

```python
print("hi")
```
"""


def test_frontmatter_becomes_meta():
    doc = parse(SAMPLE)
    assert doc.meta == {"title": "Sample", "author": "Vajra Sarpa"}
    assert doc.title == "Sample"


def test_headings_are_collected_with_anchors():
    doc = parse(SAMPLE)
    assert [(h.level, h.text) for h in doc.headings] == [(2, "First section")]
    assert doc.headings[0].anchor == "first-section"


def test_code_is_highlighted():
    doc = parse(SAMPLE)
    assert '<pre class="hl">' in doc.body_html
    assert "<span" in doc.body_html


def test_title_falls_back_to_first_heading():
    assert parse("# From heading\n\ntext").title == "From heading"


def test_empty_input_is_rejected():
    with pytest.raises(InputError, match="empty"):
        parse("   \n")


def test_unknown_frontmatter_key_is_rejected():
    with pytest.raises(InputError, match="unknown frontmatter"):
        parse("---\ncolour: red\n---\n\ntext")


def test_raw_html_is_escaped():
    doc = parse("<script>alert(1)</script>\n")
    assert "<script>" not in doc.body_html
    assert "&lt;script&gt;" in doc.body_html


def test_non_mapping_frontmatter_is_rejected():
    with pytest.raises(InputError, match="mapping"):
        parse("---\n- a\n- b\n---\n\ntext")


def test_leading_h1_matching_the_title_is_dropped_from_the_body():
    doc = parse("---\ntitle: Report\n---\n\n# Report\n\ntext\n")
    assert "<h1" not in doc.body_html


def test_leading_h1_that_is_not_the_title_stays():
    doc = parse("---\ntitle: Report\n---\n\n# Background\n\ntext\n")
    assert '<h1 id="background">Background</h1>' in doc.body_html


def test_heading_text_has_no_markdown_syntax():
    doc = parse("# The **Big** `Plan`\n\ntext\n")
    assert doc.title == "The Big Plan"
    assert "<h1" not in doc.body_html  # it is the title, so the cover shows it


def test_unknown_keys_of_mixed_types_are_rejected_cleanly():
    with pytest.raises(InputError, match="unknown frontmatter"):
        parse("---\n1: x\nfoo: y\n---\n\ntext")


@pytest.mark.parametrize(
    "src", ["https://e.com/a.png", "//e.com/a.png", "/etc/a.png", "C:/a.png"]
)
def test_non_relative_images_are_rejected(src):
    with pytest.raises(InputError, match="relative path"):
        parse(f"![a]({src})\n")


def test_relative_and_data_images_are_allowed():
    doc = parse("![a](img/fig.png) ![b](data:image/png;base64,AAAA)\n")
    assert 'src="img/fig.png"' in doc.body_html


@pytest.mark.parametrize("value", ["two", 0, -1, 1.5, True])
def test_pages_must_be_positive_int(value):
    with pytest.raises(InputError, match="pages"):
        parse(f"---\npages: {value}\n---\n\n# A\n")


def test_pages_is_allowed():
    assert parse("---\npages: 2\n---\n\n# A\n").meta["pages"] == 2
