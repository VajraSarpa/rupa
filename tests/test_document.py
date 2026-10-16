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
