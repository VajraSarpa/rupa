import json

import pytest

from rupa.cli import EXIT_CHECKS, EXIT_INPUT, EXIT_OK, main
from rupa.document import parse
from rupa.render import to_pdf
from rupa.verify import (
    DEFAULT_WANTS,
    Line,
    PageInfo,
    WantsError,
    _to_rgb,
    load_wants,
    run_checks,
    sample_pages,
    verify,
)

LETTER = (612.0, 792.0)


def body_line(top, size=10.5, bold=False, mono=False, x0=60.0, x1=500.0):
    return Line(top, top + size, x0, x1, size, mono, bold, "text")


def page(n, fill_to=700.0, lines=None, **kw):
    lines = lines if lines is not None else [body_line(70), body_line(fill_to - 10.5)]
    p = PageInfo(number=n, width=LETTER[0], height=LETTER[1], lines=lines, **kw)
    p.content_bottom = max((ln.bottom for ln in lines), default=0.0)
    return p


def failing(results):
    return {r.id: r.pages for r in results if not r.ok}


# ---- wants file


def test_defaults_without_a_file():
    assert load_wants(None) == DEFAULT_WANTS


def test_wants_file_overrides_and_merges_vision(tmp_path):
    f = tmp_path / "wants.yaml"
    f.write_text("max_pages: 3\nvision:\n  max_sheets: 2\n")
    wants = load_wants(str(f))
    assert wants["max_pages"] == 3
    assert wants["vision"]["max_sheets"] == 2
    assert wants["vision"]["sample"] == "per-type"  # untouched default survives


@pytest.mark.parametrize(
    "body, message",
    [
        ("colour: red\n", "unknown wants keys"),
        ("checks: [nope]\n", "unknown checks"),
        ("page_size: a5\n", "page_size"),
        ("vision:\n  model: big\n", "unknown vision keys"),
        ('text_color: "#GGG"\n', "text_color"),
        ('text_color: "#GGGGGG"\n', "text_color"),
        ('max_pages: "10"\n', "max_pages"),
        ("checks: null\n", "checks must be a list"),
        ("sparse_fill: 2\n", "sparse_fill"),
        ("theme: ../../etc\n", "theme must be one of"),
        ("vision: 5\n", "vision must be a YAML mapping"),
        ("vision:\n  resolution: 5000\n", "vision.resolution"),
    ],
)
def test_bad_wants_are_rejected(tmp_path, body, message):
    f = tmp_path / "wants.yaml"
    f.write_text(body)
    with pytest.raises(WantsError, match=message):
        load_wants(str(f))


# ---- colors


def test_color_normalization_handles_gray_rgb_and_cmyk():
    assert _to_rgb((0,)) == (0, 0, 0)
    assert _to_rgb((0.0, 0.0, 0.0)) == (0, 0, 0)
    assert _to_rgb((0, 0, 0, 1)) == (0, 0, 0)
    assert _to_rgb(None) is None


# ---- deterministic checks on synthetic pages


def test_clean_document_passes_everything():
    pages = [page(1), page(2), page(3)]
    assert failing(run_checks(pages, load_wants(None))) == {}


def test_off_color_text_fails():
    pages = [page(1), page(2, off_colors=12)]
    assert failing(run_checks(pages, load_wants(None))) == {"text-color": [2]}


def test_wrong_page_size_fails():
    pages = [page(1)]
    pages[0].width, pages[0].height = 595.0, 842.0  # A4
    assert "page-size" in failing(run_checks(pages, load_wants(None)))


def test_near_empty_page_fails_but_last_page_is_exempt():
    pages = [page(1), page(2, fill_to=120), page(3), page(4, fill_to=120)]
    assert failing(run_checks(pages, load_wants(None))) == {"near-empty": [2]}


def test_sparse_page_is_allowed_before_a_part_break():
    part = [body_line(70, size=20, bold=True), body_line(700)]
    pages = [page(1), page(2, fill_to=300), page(3, lines=part), page(4)]
    assert failing(run_checks(pages, load_wants(None))) == {}


def test_sparse_page_without_a_part_break_fails():
    pages = [page(1), page(2, fill_to=300), page(3), page(4)]
    assert failing(run_checks(pages, load_wants(None))) == {"sparse": [2]}


def test_stranded_heading_fails():
    lines = [body_line(70), body_line(690, size=15, bold=True)]
    pages = [page(1), page(2, lines=lines), page(3)]
    assert failing(run_checks(pages, load_wants(None))) == {"heading-at-bottom": [2]}


def test_title_only_document_is_not_a_stranded_heading():
    pages = [page(1, lines=[body_line(70, size=26, bold=True)])]
    assert failing(run_checks(pages, load_wants(None))) == {}


def test_heading_ending_the_last_page_is_not_stranded():
    lines = [body_line(70), body_line(690, size=15, bold=True)]
    pages = [page(1), page(2), page(3, lines=lines)]
    assert failing(run_checks(pages, load_wants(None))) == {}


def test_heading_only_section_after_toc_passes_verify(tmp_path):
    data, _ = to_pdf(parse("---\ntitle: CI\n---\n\n## ok\n"))
    pdf = tmp_path / "ci.pdf"
    pdf.write_bytes(data)
    assert verify(pdf, load_wants(None), tmp_path / "v").ok


def test_title_only_render_passes_verify(tmp_path):
    data, _ = to_pdf(parse("# Hello\n"))
    pdf = tmp_path / "hello.pdf"
    pdf.write_bytes(data)
    report = verify(pdf, load_wants(None), tmp_path / "v")
    assert report.ok, report.summary()
    assert "1 sheet for visual review" in report.summary()


def test_bold_code_at_bottom_is_not_a_heading():
    lines = [body_line(70), body_line(690, size=12, bold=True, mono=True)]
    pages = [page(1), page(2, lines=lines), page(3)]
    assert failing(run_checks(pages, load_wants(None))) == {}


def test_text_past_the_margin_fails():
    lines = [body_line(70), body_line(690, x1=600)]
    pages = [page(1), page(2, lines=lines), page(3)]
    assert failing(run_checks(pages, load_wants(None))) == {"overflow": [2]}


def test_disabled_checks_are_skipped():
    wants = load_wants(None)
    wants["checks"] = ["text-color"]
    pages = [page(1), page(2, fill_to=120), page(3)]
    results = run_checks(pages, wants)
    assert [r.id for r in results] == ["text-color"]


# ---- sampling


def test_sampling_takes_flagged_pages_then_one_per_kind():
    pages = [page(1, kind="cover")] + [page(n, kind="prose") for n in range(2, 9)]
    pages.append(page(9, kind="code"))
    wants = load_wants(None)
    pages[3].off_colors = 1  # page 4 flagged
    picked = [p.number for p in sample_pages(pages, run_checks(pages, wants), wants)]
    assert picked[0] == 4  # flagged first
    assert 1 in picked and 9 in picked  # cover and code represented
    assert sum(pages[n - 1].kind == "prose" for n in picked) == 1  # prose covered once


def test_sampling_flagged_takes_only_flagged_pages():
    pages = [page(1, kind="cover")] + [page(n, kind="prose") for n in range(2, 6)]
    wants = load_wants(None)
    wants["vision"]["sample"] = "flagged"
    assert sample_pages(pages, run_checks(pages, wants), wants) == []
    pages[2].off_colors = 1  # page 3 flagged
    picked = [p.number for p in sample_pages(pages, run_checks(pages, wants), wants)]
    assert picked == [3]


def test_sampling_none_returns_nothing():
    wants = load_wants(None)
    wants["vision"]["sample"] = "none"
    assert sample_pages([page(1)], [], wants) == []


# ---- end to end on a real render

DOC = """---
title: Verify me
---

## Section

Some body text that renders black.

| a | b |
|---|---|
| 1 | 2 |
"""


@pytest.fixture
def real_pdf(tmp_path):
    data, _ = to_pdf(parse(DOC))
    path = tmp_path / "doc.pdf"
    path.write_bytes(data)
    return path


def test_real_render_passes_and_writes_sheets(real_pdf, tmp_path):
    report = verify(real_pdf, load_wants(None), tmp_path / "v")
    assert report.ok, report.summary()
    assert report.sheets and all(
        (tmp_path / "v" / s["path"].split("/")[-1]).exists() for s in report.sheets
    )
    manifest = json.loads((tmp_path / "v" / "verify.json").read_text())
    assert manifest["ok"] is True and manifest["rubric"]


def test_cli_verify_exit_codes(real_pdf, tmp_path, capsys):
    assert main(["verify", str(real_pdf), "--out", str(tmp_path / "a")]) == EXIT_OK
    assert capsys.readouterr().out.startswith("verify: ")

    strict = tmp_path / "wants.yaml"
    strict.write_text("max_pages: 1\n")  # cover + TOC page break makes 2 pages
    code = main(
        ["verify", str(real_pdf), "--wants", str(strict), "--out", str(tmp_path / "b")]
    )
    assert code == EXIT_CHECKS
    assert "FAIL max-pages" in capsys.readouterr().out

    bad = tmp_path / "bad.yaml"
    bad.write_text("nope: 1\n")
    code = main(["verify", str(real_pdf), "--wants", str(bad)])
    assert code == EXIT_INPUT


def test_example_wants_file_matches_defaults():
    from pathlib import Path

    example = Path(__file__).parent.parent / "wants.example.yaml"
    assert load_wants(str(example)) == DEFAULT_WANTS


def test_reference_sample_gives_one_whole_page_per_kind(tmp_path):
    from importlib import resources

    from rupa.verify import build_references

    sample = (resources.files("rupa") / "references" / "sample.md").read_text()
    data, _ = to_pdf(parse(sample))
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(data)
    picked = build_references(pdf, tmp_path / "refs")
    assert set(picked) == {"cover", "prose", "table", "code"}
    assert all((tmp_path / "refs" / f"{k}.png").exists() for k in picked)


def test_references_refuse_a_spilling_sample(tmp_path):
    from rupa.verify import build_references

    code = "\n".join(f"x_{i} = {i}" for i in range(200))
    md = f"## Prose\n\nText.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\n{code}\n```\n"
    data, _ = to_pdf(parse(md))
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(data)
    with pytest.raises(ValueError):
        build_references(pdf, tmp_path / "refs")
