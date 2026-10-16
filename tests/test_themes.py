"""Themes: each renders, records itself in the PDF, and verify follows it."""

from importlib import resources

import pytest

from rupa.cli import EXIT_OK, main
from rupa.document import parse
from rupa.render import THEME_BASE, THEME_TEXT_COLORS, THEMES, to_html, to_pdf
from rupa.verify import (
    DEFAULT_WANTS,
    Line,
    PageInfo,
    load_wants,
    pdf_theme,
    verify,
)

SAMPLE = (resources.files("rupa") / "references" / "sample.md").read_text(
    encoding="utf-8"
)


def render(tmp_path, theme, md=SAMPLE):
    data, _ = to_pdf(parse(md), theme)
    pdf = tmp_path / f"{theme}.pdf"
    pdf.write_bytes(data)
    return pdf


def test_every_theme_has_css_and_text_colours():
    themes = resources.files("rupa") / "themes"
    for theme in THEMES:
        assert (themes / f"{THEME_BASE.get(theme, theme)}.css").is_file()
        assert THEME_TEXT_COLORS[theme]


@pytest.mark.parametrize("theme", THEMES)
def test_pdf_records_its_theme(tmp_path, theme):
    assert pdf_theme(render(tmp_path, theme)) == theme


def test_html_records_its_theme():
    assert 'content="rupa-theme:cyan"' in to_html(parse("# Hi\n"), "cyan")


def test_verify_follows_the_theme_in_the_pdf(tmp_path):
    pdf = render(tmp_path, "cyan-dark")
    report = verify(pdf, DEFAULT_WANTS, tmp_path / "v")  # no theme given
    assert report.ok, report.summary()
    # Held to black text instead, the dark theme's light ink fails.
    black = {**DEFAULT_WANTS, "text_color": "#000000"}
    forced = verify(pdf, black, tmp_path / "v2")
    assert [c.id for c in forced.checks if not c.ok] == ["text-color"]


def test_verify_cli_needs_no_theme_flag(tmp_path, capsys):
    pdf = render(tmp_path, "cyan-dark")
    assert main(["verify", str(pdf)]) == EXIT_OK
    assert "8/8 checks pass" in capsys.readouterr().out


def test_light_cyan_pdf_text_is_black(tmp_path):
    report = verify(render(tmp_path, "cyan"), load_wants(None), tmp_path / "v")
    assert next(c for c in report.checks if c.id == "text-color").ok


def test_a_label_above_a_part_title_still_starts_a_part():
    label = Line(60, 67, 58, 100, 7, True, False, "PART 1")
    title = Line(75, 95, 58, 300, 20, False, True, "Part One")
    assert PageInfo(1, 612, 792, lines=[label, title]).starts_part


def _toc_shown(md):
    from rupa.document import parse
    from rupa.render import to_html

    return '<nav class="toc">' in to_html(parse(md))


def test_toc_off_by_default_for_short_documents():
    assert not _toc_shown("---\ntitle: T\n---\n\n## A\n\nx\n\n## B\n\ny\n")


def test_toc_on_by_default_from_three_sections():
    assert _toc_shown("---\ntitle: T\n---\n\n## A\n\nx\n\n## B\n\ny\n\n## C\n\nz\n")


def test_toc_frontmatter_overrides_default():
    assert _toc_shown("---\ntitle: T\ntoc: true\n---\n\n## A\n\nx\n")
    assert not _toc_shown(
        "---\ntitle: T\ntoc: false\n---\n\n## A\n\nx\n\n## B\n\ny\n\n## C\n\nz\n"
    )


def test_short_pdf_is_one_page(tmp_path):
    from rupa.document import parse
    from rupa.render import to_pdf

    _, pages = to_pdf(
        parse("---\ntitle: T\n---\n\n## ok\n\nBody.\n"), "default", tmp_path
    )
    assert pages == 1
