"""Vega-Lite charts: refused when they could reach out, drawn in every format."""

import base64
import io
import json
import re
import sys
import zipfile

import pytest

from rupa import charts
from rupa.cli import EXIT_OK, EXIT_RENDER, main
from rupa.document import InputError, parse

BAR = {
    "description": "Revenue by month",
    "data": {"values": [{"m": "Jan", "r": 3}, {"m": "Feb", "r": 5}]},
    "mark": "bar",
    "encoding": {
        "x": {"field": "m", "type": "nominal"},
        "y": {"field": "r", "type": "quantitative"},
    },
}


def block(spec) -> str:
    body = spec if isinstance(spec, str) else json.dumps(spec)
    return f"---\ntitle: C\ntoc: false\n---\n\n## A\n\n```vega-lite\n{body}\n```\n"


def render(tmp_path, monkeypatch, capsys, text, out="out.html", *extra):
    (tmp_path / "doc.md").write_text(text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code = main(["doc.md", "-o", out, *extra])
    stdout, stderr = capsys.readouterr()
    return code, tmp_path / out, stdout, stderr


def svgs(html: str) -> list[str]:
    return [
        base64.b64decode(b).decode()
        for b in re.findall(r'src="data:image/svg\+xml;base64,([^"]+)"', html)
    ]


# --- parse: the block itself -------------------------------------------------


def test_block_becomes_a_chart_placeholder():
    doc = parse(block({**BAR, "title": "Sales <b>"}))
    assert doc.charts and doc.charts[0]["mark"] == "bar"
    assert '<img src="rupa-chart:0" alt="Revenue by month">' in doc.body_html
    assert "language-vega-lite" not in doc.body_html
    other = parse("```json\n{}\n```\n")
    assert not other.charts and "<pre" in other.body_html


@pytest.mark.parametrize(
    "spec, why",
    [
        ({"mark": "image", "encoding": {"url": {"value": "http://x/a.png"}}}, "url"),
        ({"mark": {"type": "image", "url": "a.png"}}, "url"),
        ({"mark": "point", "encoding": {"href": {"field": "u"}}}, "href"),
        ({"mark": {"type": "point", "href": "https://x"}}, "href"),
        ({"data": {"url": "https://x/a.csv"}}, "relative path"),
        ({"data": {"url": "file:///etc/passwd"}}, "relative path"),
        ({"data": {"url": "/etc/hosts.csv"}}, "relative path"),
        ({"data": {"url": "notes.txt"}}, ".csv, .tsv or .json"),
        ({"usermeta": {"url": "x"}}, "url"),
        ({"data": {"values": [{}] * 5001}}, "at most 5,000"),
        (
            {"data": {"values": "a\n" + "1\n" * 5001, "format": {"type": "csv"}}},
            "5,000",
        ),
        ({"datasets": {"d": [{}] * 5001}}, "5,000"),
        ({"data": {"sequence": {"start": 0, "stop": 1e9}}}, "5,000"),
        (
            {"transform": [{"lookup": "k", "from": {"data": {"url": "http://x"}}}]},
            "relative",
        ),
        ("[1, 2]", "JSON object"),
        ("{bad", "not valid JSON"),
    ],
)
def test_block_refusals_are_bad_input(spec, why):
    with pytest.raises(InputError, match=re.escape(why)):
        parse(block(spec))


def test_markdown_cannot_forge_a_chart_placeholder():
    with pytest.raises(InputError):
        parse("![x](rupa-chart:0)\n")


def test_too_many_charts():
    with pytest.raises(InputError, match="more than 50 charts"):
        parse("\n".join(block(BAR) for _ in range(51)))


def test_alt_text():
    assert charts.alt_text({"title": {"text": "T"}}) == "T"
    assert charts.alt_text({"title": ["A", "B"]}) == "A B"
    assert charts.alt_text({}) == "Chart"


# --- render: HTML, PDF, DOCX -------------------------------------------------


def test_html_embeds_an_svg_chart(tmp_path, monkeypatch, capsys):
    code, out, _, err = render(tmp_path, monkeypatch, capsys, block(BAR))
    assert code == EXIT_OK, err
    html = out.read_text()
    assert "rupa-chart:" not in html
    (svg,) = svgs(html)
    assert "<svg" in svg and "Jan" in svg
    assert "href" not in svg and not re.search(r"url\((?!#)", svg)


def test_local_csv_is_inlined(tmp_path, monkeypatch, capsys):
    (tmp_path / "sales.csv").write_text("m,r\nMarchMonth,7\n")
    spec = {**BAR, "data": {"url": "sales.csv"}}
    code, out, _, err = render(tmp_path, monkeypatch, capsys, block(spec))
    assert code == EXIT_OK, err
    assert "MarchMonth" in svgs(out.read_text())[0]


def test_local_json_with_property(tmp_path, monkeypatch, capsys):
    (tmp_path / "d.json").write_text(json.dumps({"rows": [{"m": "Qtr", "r": 1}]}))
    spec = {**BAR, "data": {"url": "d.json", "format": {"property": "rows"}}}
    code, out, _, err = render(tmp_path, monkeypatch, capsys, block(spec))
    assert code == EXIT_OK, err
    assert "Qtr" in svgs(out.read_text())[0]


@pytest.mark.parametrize(
    "url, setup, msg",
    [
        ("../outside.csv", "outside", "outside"),
        (".hidden.csv", "hidden", "hidden"),
        ("missing.csv", None, "missing"),
        ("big.csv", "big", "5,000"),
    ],
)
def test_data_file_refusals_fail_the_render(
    tmp_path, monkeypatch, capsys, url, setup, msg
):
    work = tmp_path / "work"
    work.mkdir()
    if setup == "outside":
        (tmp_path / "outside.csv").write_text("m,r\nA,1\n")
    elif setup == "hidden":
        (work / ".hidden.csv").write_text("m,r\nA,1\n")
    elif setup == "big":
        (work / "big.csv").write_text("m,r\n" + "A,1\n" * 5001)
    code, out, _, err = render(
        work, monkeypatch, capsys, block({**BAR, "data": {"url": url}})
    )
    assert code == EXIT_RENDER and msg in err
    assert not out.exists()


def test_chart_file_from_altair(tmp_path, monkeypatch, capsys):
    spec = {"$schema": "https://vega.github.io/schema/vega-lite/v5.20.1.json", **BAR}
    (tmp_path / "rev.vl.json").write_text(json.dumps(spec))
    text = "# T\n\n![Revenue](rev.vl.json)\n"
    code, out, _, err = render(tmp_path, monkeypatch, capsys, text)
    assert code == EXIT_OK, err
    assert len(svgs(out.read_text())) == 1


def test_chart_file_is_checked_like_a_block(tmp_path, monkeypatch, capsys):
    bad = {**BAR, "encoding": {**BAR["encoding"], "href": {"value": "https://x"}}}
    (tmp_path / "bad.vl.json").write_text(json.dumps(bad))
    code, _, _, err = render(
        tmp_path, monkeypatch, capsys, "# T\n\n![x](bad.vl.json)\n"
    )
    assert code == EXIT_RENDER and "href" in err


def test_chart_file_outside_folder(tmp_path, monkeypatch, capsys):
    (tmp_path / "rev.vl.json").write_text(json.dumps(BAR))
    work = tmp_path / "work"
    work.mkdir()
    code, _, _, err = render(work, monkeypatch, capsys, "# T\n\n![x](../rev.vl.json)\n")
    assert code == EXIT_RENDER and "outside" in err


def test_bad_spec_fails_with_one_line(tmp_path, monkeypatch, capsys):
    spec = {"mark": "nope", "data": {"values": [{"a": 1}]}}
    code, _, _, err = render(tmp_path, monkeypatch, capsys, block(spec))
    assert code == EXIT_RENDER and "chart could not be drawn" in err
    assert err.count("\n") == 1


def test_svg_output_check(tmp_path, monkeypatch, capsys):
    """Whatever the spec check misses, a link in the SVG fails the render."""
    vlc = charts._converter()

    class Leaky:
        def __getattr__(self, name):
            return getattr(vlc, name)

        @staticmethod
        def vegalite_to_svg(spec, **kw):
            return '<svg><image href="http://tracker.example/p.png"/></svg>'

    monkeypatch.setattr(charts, "_vlc", Leaky())
    code, _, _, err = render(tmp_path, monkeypatch, capsys, block(BAR))
    assert code == EXIT_RENDER and "outside resource" in err


def test_internal_svg_references_are_fine():
    svg = '<svg><g clip-path="url(#clip1)"/></svg>'
    assert not charts._SVG_URL.search(svg) and not charts._SVG_HREF.search(svg)
    assert charts._SVG_URL.search("<rect style=\"fill:url('http://x')\"/>")


def test_vl_convert_never_fetches(tmp_path, monkeypatch, capsys):
    seen = {}
    vlc = charts._converter()

    class Spy:
        def __getattr__(self, name):
            return getattr(vlc, name)

        @staticmethod
        def vegalite_to_svg(spec, **kw):
            seen.update(kw)
            return vlc.vegalite_to_svg(spec, **kw)

    monkeypatch.setattr(charts, "_vlc", Spy())
    code, *_ = render(tmp_path, monkeypatch, capsys, block(BAR))
    assert code == EXIT_OK and seen["allowed_base_urls"] == []


def test_missing_extra_says_how_to_install(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(charts, "_vlc", None)
    monkeypatch.setitem(sys.modules, "vl_convert", None)
    code, _, _, err = render(tmp_path, monkeypatch, capsys, block(BAR))
    assert code == EXIT_RENDER and "rupa[charts]" in err


def test_pdf_chart_passes_verify_with_black_text(tmp_path, monkeypatch, capsys):
    import pdfplumber

    code, out, _, err = render(tmp_path, monkeypatch, capsys, block(BAR), "out.pdf")
    assert code == EXIT_OK, err
    with pdfplumber.open(out) as pdf:
        colours = {c["non_stroking_color"] for c in pdf.pages[0].chars}
        text = pdf.pages[0].extract_text()
    assert ("Jan" in text or "naJ" in text) and colours <= {
        (0,),
        (0, 0, 0),
        (0.0, 0.0, 0.0),
    }
    assert main(["verify", str(out)]) == EXIT_OK


def test_docx_chart_is_a_png(tmp_path, monkeypatch, capsys):
    (tmp_path / "rev.vl.json").write_text(json.dumps(BAR))
    text = block(BAR) + "\n![Rev](rev.vl.json)\n"
    code, out, _, err = render(tmp_path, monkeypatch, capsys, text, "out.docx")
    assert code == EXIT_OK, err
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        body = z.read("word/document.xml").decode()
        png = z.read("word/media/image1.png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert [n for n in names if n.startswith("word/media/")] == [
        "word/media/image1.png"
    ]
    assert body.count("<w:drawing>") == 2 and 'descr="Revenue by month"' in body
    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        assert img.width >= 2 * charts.COLUMN_PX * 0.9  # drawn at 2x


# --- config and sizing --------------------------------------------------------


@pytest.mark.parametrize(
    "theme, target, ink",
    [
        ("default", "html", "#000000"),
        ("default", "pdf", "#000000"),
        ("cyan", "html", "#e6edf6"),
        ("cyan", "pdf", "#000000"),
        ("cyan-dark", "pdf", "#e6edf6"),
        ("cyan-dark", "docx", "#000000"),
    ],
)
def test_theme_palette(theme, target, ink):
    from rupa.render import THEME_TEXT_COLORS

    config = charts.chart_config(theme, target)
    assert config["title"]["color"] == ink
    if target == "pdf":  # verify's text-colour check must still pass
        allowed = THEME_TEXT_COLORS[theme]
        assert config["axis"]["labelColor"] in allowed
        assert config["legend"]["titleColor"] in allowed


def test_html_fonts_fall_back():
    assert "sans-serif" in charts.chart_config("cyan", "html")["font"]
    assert charts.chart_config("cyan", "pdf")["font"] == "Hanken Grotesk"


def test_sizing():
    sized = charts._sized(BAR)
    assert sized["width"] == charts.COLUMN_PX and sized["height"] == 240
    assert charts._sized({**BAR, "width": 200}) == {**BAR, "width": 200}
    assert "width" not in charts._sized({"hconcat": [BAR, BAR]})


def test_schema_version_is_honoured():
    available = ["5.20", "5.21", "6.1", "6.4"]
    v5 = {"$schema": "https://vega.github.io/schema/vega-lite/v5.20.1.json"}
    assert charts._vl_version(v5, available) == "5.21"
    assert charts._vl_version({}, available) is None


def test_fill_data_leaves_the_spec_alone(tmp_path):
    (tmp_path / "s.csv").write_text("m,r\nA,1\n")
    spec = {"data": {"url": "s.csv"}, "mark": "bar"}
    filled = charts.fill_data(spec, tmp_path)
    assert spec["data"] == {"url": "s.csv"}  # parsed spec unchanged
    assert filled["data"] == {"values": "m,r\nA,1\n", "format": {"type": "csv"}}
