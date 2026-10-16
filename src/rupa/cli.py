"""rupa CLI.

  rupa [INPUT] -o OUT            render Markdown to HTML or PDF
  rupa verify PDF [--wants F]    check a rendered PDF, write review sheets
  rupa refs [--theme T]          rebuild a theme's reference pages

Contract:
  stdin  -> Markdown with optional YAML frontmatter
  file   -> the rendered output (format from -o extension or --to)
  stdout -> ONE status line (or one JSON object with --json). Never the document.
  exit   -> 0 ok, 2 usage, 3 bad input, 4 render failure, 5 verify checks failed
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from importlib import resources
from pathlib import Path

from . import __version__
from .document import InputError, parse
from .render import THEMES, RenderError, to_html, to_pdf

EXIT_OK, EXIT_USAGE, EXIT_INPUT, EXIT_RENDER, EXIT_CHECKS = 0, 2, 3, 4, 5
FORMATS = ("html", "pdf")


def _render_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rupa", description="Render Markdown to HTML or PDF."
    )
    p.add_argument(
        "input", nargs="?", default="-", help="Markdown file, or - for stdin (default)"
    )
    p.add_argument("-o", "--output", required=True, help="output path, e.g. out.pdf")
    p.add_argument(
        "--to", choices=FORMATS, help="force format instead of using the extension"
    )
    p.add_argument(
        "--theme", default=None, help="theme name (default: frontmatter or 'default')"
    )
    p.add_argument("--json", action="store_true", help="print a JSON status object")
    p.add_argument("--version", action="version", version=f"rupa {__version__}")
    return p


def _err(args, msg: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print(f"rupa: error: {msg}", file=sys.stderr)


def render_main(argv: list[str]) -> int:
    args = _render_parser().parse_args(argv)
    out = Path(args.output)
    fmt = args.to or out.suffix.lstrip(".").lower()
    if fmt not in FORMATS:
        _err(args, f"cannot infer format from '{out.name}'; use --to")
        return EXIT_USAGE

    try:
        text = (
            sys.stdin.read()
            if args.input == "-"
            else Path(args.input).read_text(encoding="utf-8")
        )
        doc = parse(text)
    except (InputError, OSError, UnicodeDecodeError) as exc:
        _err(args, str(exc))
        return EXIT_INPUT

    theme = args.theme or doc.meta.get("theme", "default")
    try:
        pages = None
        if fmt == "html":
            data = to_html(doc, theme).encode("utf-8")
        else:
            base = Path(args.input).parent if args.input != "-" else Path.cwd()
            data, pages = to_pdf(doc, theme, base_dir=base)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    except (RenderError, OSError) as exc:
        _err(args, str(exc))
        return EXIT_RENDER

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "path": str(out),
                    "format": fmt,
                    "pages": pages,
                    "bytes": len(data),
                }
            )
        )
    else:
        extra = f", {pages} page{'s' if pages != 1 else ''}" if pages else ""
        print(f"rupa: wrote {out} ({fmt}{extra}, {len(data):,} bytes)")
    return EXIT_OK


def verify_main(argv: list[str]) -> int:
    from .verify import (
        EXIT_CHECKS_FAILED,
        SAMPLE_MODES,
        PdfError,
        WantsError,
        load_wants,
        verify,
    )

    p = argparse.ArgumentParser(prog="rupa verify", description="Check a rendered PDF.")
    p.add_argument("pdf")
    p.add_argument("--wants", help="wants.yaml (default: built-in rules)")
    p.add_argument(
        "--theme",
        choices=THEMES,
        help="theme whose reference pages to compare against",
    )
    p.add_argument(
        "--out", help="directory for sheets and verify.json (default: <pdf>.verify/)"
    )
    p.add_argument(
        "--sample",
        choices=SAMPLE_MODES,
        help="which pages get review sheets (overrides the wants file)",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    pdf = Path(args.pdf)
    if not pdf.is_file():
        _err(args, f"no such file: {pdf}")
        return EXIT_USAGE
    try:
        wants = load_wants(args.wants)
    except WantsError as exc:
        _err(args, str(exc))
        return EXIT_INPUT
    if args.sample:
        wants["vision"]["sample"] = args.sample
    out = Path(args.out) if args.out else pdf.with_suffix(".verify")
    try:
        report = verify(pdf, wants, out, theme=args.theme)
    except PdfError as exc:
        _err(args, str(exc))
        return EXIT_INPUT
    if args.json:
        print(Path(report.manifest).read_text())
    else:
        print(report.summary())
    return EXIT_OK if report.ok else EXIT_CHECKS_FAILED


def refs_main(argv: list[str]) -> int:
    from .verify import build_references

    p = argparse.ArgumentParser(
        prog="rupa refs", description="Rebuild a theme's reference pages."
    )
    p.add_argument("--theme", default="default")
    p.add_argument(
        "--out", help="output directory (default: the package's references/<theme>/)"
    )
    args = p.parse_args(argv)
    sample = (resources.files("rupa") / "references" / "sample.md").read_text(
        encoding="utf-8"
    )
    try:
        data, _ = to_pdf(parse(sample), args.theme)
    except RenderError as exc:
        _err(args, str(exc))
        return EXIT_RENDER
    out = (
        Path(args.out)
        if args.out
        else Path(str(resources.files("rupa") / "references" / args.theme))
    )
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "sample.pdf"
        pdf.write_bytes(data)
        try:
            picked = build_references(pdf, out)
        except ValueError as exc:
            _err(args, str(exc))
            return EXIT_RENDER
    kinds = ", ".join(f"{k}=p{n}" for k, n in sorted(picked.items()))
    print(f"rupa: wrote references for '{args.theme}' to {out} ({kinds})")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "verify":
        return verify_main(argv[1:])
    if argv and argv[0] == "refs":
        return refs_main(argv[1:])
    return render_main(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
