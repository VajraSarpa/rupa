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


def test_strikethrough_task_lists_and_footnotes_render():
    doc = parse("- [x] done\n- [ ] todo\n\n~~old~~ new.[^1]\n\n[^1]: A <b>note</b>.\n")
    html = doc.body_html
    assert "<s>old</s>" in html
    assert html.count('type="checkbox"') == 2 and 'checked="checked"' in html
    assert 'class="footnotes"' in html and "[^1]" not in html
    assert "&lt;b&gt;note&lt;/b&gt;" in html  # raw HTML stays escaped in a footnote


@pytest.mark.parametrize(
    "front",
    ["date: 2026-02-30", "title: " + "[" * 3000],
    ids=["impossible-date", "deep-nesting"],
)
def test_frontmatter_that_crashes_yaml_is_bad_input(front):
    # ValueError (impossible date) and RecursionError (deep nesting) used to
    # escape as tracebacks with exit 1.
    with pytest.raises(InputError, match="bad frontmatter"):
        parse(f"---\n{front}\n---\n\nBody.\n")


SVG_URI = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPSc0JyBoZWlnaHQ9JzQnLz4="
)


def test_svg_data_images_become_images():
    # markdown-it's own link check drops SVG data URIs, which used to leave
    # the Markdown source showing in the page.
    doc = parse(f"![logo]({SVG_URI})\n")
    assert "<img" in doc.body_html and "![logo]" not in doc.body_html


@pytest.mark.parametrize("mime", ["image/bmp", "image/x-icon", "image/svg"])
def test_other_data_image_types_are_bad_input(mime):
    with pytest.raises(InputError, match="data:image"):
        parse(f"![a](data:{mime};base64,AAAA)\n")
