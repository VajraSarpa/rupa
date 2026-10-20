"""A figure must not leave half a page empty above it.

A heading, its lead-in and the figure's image are kept together, so when the
block is too tall for what is left of a page it moves whole. Capping the
image's height lets it fit in the gap more often.
"""

import pytest
from PIL import Image

from rupa.document import parse
from rupa.render import THEMES, to_pdf
from rupa.verify import load_wants, read_pages, run_checks

BODY_PT = 792 - (0.85 + 0.9) * 72  # a letter page's body height
IMAGE_CAP_PT = 3 * 72  # print.css: img max-height

FIGURE = """\
### Chart

Figure 1 shows the mean period against the length of the pendulum, with a fit
through the origin. The second line of this paragraph keeps going so that it
wraps over two lines.

![Mean period against length](chart.png)

*Figure 1: Mean period against length.*
"""


def lead_in(paragraphs: int) -> str:
    text = "Lead-in paragraph with some words to fill a line. " * 3
    return "\n\n".join(f"{text}{i}" for i in range(paragraphs))


def render(tmp_path, markdown: str, theme: str = "default"):
    Image.new("RGB", (900, 600), (30, 110, 140)).save(tmp_path / "chart.png")
    data, _ = to_pdf(parse(markdown), theme, base_dir=tmp_path)
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(data)
    return read_pages(pdf)


def check(pages, cid):
    return next((r for r in run_checks(pages, load_wants(None)) if r.id == cid), None)


# 20 lead-in paragraphs end the page before the figure 45% full (a 366pt gap).
# The block (heading, two lines, a 331pt image) needs about 430pt with its
# margins, so on an uncapped image it moves whole to the next page and leaves
# that 45%. With the image capped at 216pt it needs about 315pt and fits.
LEAD_IN_PARAGRAPHS = 20


def test_the_lead_in_alone_leaves_a_gap_the_figure_could_fill(tmp_path):
    # Guards the setup: without the figure the second page is 30-70% full.
    pages = render(tmp_path, f"# Lab report\n\n{lead_in(LEAD_IN_PARAGRAPHS)}\n")
    assert len(pages) == 2
    assert 0.3 < pages[1].fill < 0.7, pages[1].fill


def test_figure_fits_the_gap_instead_of_moving_to_the_next_page(tmp_path):
    md = f"# Lab report\n\n{lead_in(LEAD_IN_PARAGRAPHS)}\n\n{FIGURE}"
    pages = render(tmp_path, md)
    gap = check(pages, "figure-gap")
    assert gap is not None, "figure-gap check is missing"
    assert gap.ok, gap.detail
    # The figure shares the page with its lead-in rather than opening the next.
    assert pages[1].images, [(p.number, round(p.fill, 2)) for p in pages]
    assert len(pages) == 2, "the caption must not be stranded on a page of its own"


@pytest.mark.parametrize("theme", THEMES)
def test_images_are_capped_in_height_in_every_theme(tmp_path, theme):
    md = f"# Lab report\n\n{FIGURE}"
    pages = render(tmp_path, md, theme)
    images = [im for p in pages for im in p.images]
    assert len(images) == 1
    x0, top, x1, bottom = images[0]
    assert bottom - top <= IMAGE_CAP_PT + 1
    assert bottom - top < 0.33 * BODY_PT
    assert (x1 - x0) / (bottom - top) == pytest.approx(1.5, rel=0.02)  # 900x600 kept
