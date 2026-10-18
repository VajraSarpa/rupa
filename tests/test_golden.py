"""Golden render: the sample document must still match each theme's reference pages.

A theme CSS change that moves the layout fails here until `rupa refs` is re-run
and the new PNGs are committed. The tolerance absorbs antialiasing differences
between Pango builds (CI runs Ubuntu's), not layout shifts. With
RUPA_GOLDEN_FAILURES set, a failing theme's PDF and pages are copied there.
"""

import os
import shutil
from importlib import resources
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from rupa.document import parse
from rupa.render import THEMES, to_pdf
from rupa.verify import DEFAULT_WANTS, build_references, reference_path, verify

KINDS = ("cover", "prose", "table", "code")
MAX_CHANGED = 0.005  # fraction of pixels allowed to differ by more than 1/4 grey


def changed_fraction(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a.convert("L"), b.convert("L"))
    changed = diff.point(lambda v: 255 if v > 64 else 0).histogram()[255]
    return changed / (a.width * a.height)


@pytest.fixture(scope="module", params=THEMES)
def sample_render(request, tmp_path_factory):
    theme = request.param
    sample = (resources.files("rupa") / "references" / "sample.md").read_text(
        encoding="utf-8"
    )
    data, _ = to_pdf(parse(sample), theme)
    tmp = tmp_path_factory.mktemp(f"golden-{theme}")
    pdf = tmp / "sample.pdf"
    pdf.write_bytes(data)
    return theme, pdf, tmp


def test_sample_passes_verify(sample_render):
    theme, pdf, tmp = sample_render
    report = verify(pdf, DEFAULT_WANTS, tmp / "verify", theme=theme)
    assert report.ok, report.summary()


def test_sample_matches_reference_pages(sample_render):
    theme, pdf, tmp = sample_render
    build_references(pdf, tmp / "refs")
    for kind in KINDS:
        ref = reference_path(theme, kind)
        assert ref is not None, (
            f"{theme} has no {kind}.png; run `rupa refs --theme {theme}`"
        )
        with resources.as_file(ref) as path:
            want = Image.open(path)
            got = Image.open(tmp / "refs" / f"{kind}.png")
            assert got.size == want.size, f"{theme}/{kind}: page size changed"
            frac = changed_fraction(want, got)
        if frac > MAX_CHANGED and os.environ.get("RUPA_GOLDEN_FAILURES"):
            keep = Path(os.environ["RUPA_GOLDEN_FAILURES"]) / theme
            shutil.copytree(tmp, keep, dirs_exist_ok=True)
        assert frac <= MAX_CHANGED, (
            f"{theme}/{kind}.png differs in {frac:.2%} of pixels; if the change "
            f"is intended, run `rupa refs --theme {theme}` and commit the PNGs"
        )
