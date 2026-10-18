"""rupa CLI.

  rupa [INPUT] -o OUT            render Markdown to HTML or PDF
  rupa verify PDF [--wants F]    check a rendered PDF, write review sheets
  rupa refs [--theme T]          rebuild a theme's reference pages

A Markdown file named verify or refs is read as the subcommand; write
./verify to render it.

Contract:
  stdin  -> Markdown with optional YAML frontmatter
  file   -> the rendered output (format from -o extension or --to)
  stdout -> ONE status line (or one JSON object with --json). Never the document.
  exit   -> 0 ok, 2 usage, 3 bad input, 4 render failure,
            5 verify checks failed, or a PDF still over its page budget

Every run that exits non-zero or crashes is appended to a JSONL log,
~/.rupa/log.jsonl by default. RUPA_LOG=<path> moves it; RUPA_LOG=off stops it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from . import __version__
from .document import InputError, parse
from .render import (
    PROSE_WORDS_PER_LINE,
    THEMES,
    RenderError,
    fit_pdf,
    to_html,
    to_pdf,
)

EXIT_OK, EXIT_USAGE, EXIT_INPUT, EXIT_RENDER, EXIT_CHECKS = 0, 2, 3, 4, 5
FORMATS = ("html", "pdf")


def _render_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rupa",
        description="Render Markdown to HTML or PDF.",
        epilog="To render a file named verify or refs, write ./verify or ./refs.",
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
    p.add_argument(
        "--pages",
        type=int,
        help="PDF page budget; tighten type to fit (default: frontmatter 'pages')",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="with --to, replace an existing output that isn't .html or .pdf",
    )
    p.add_argument("--json", action="store_true", help="print a JSON status object")
    p.add_argument("--version", action="version", version=f"rupa {__version__}")
    return p


def _err(args, msg: str) -> None:
    msg = " ".join(msg.split())  # the contract is one line on stderr
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
    # --to lets -o name any file, so only an .html or .pdf is replaced unasked.
    if out.exists() and out.suffix.lower() not in (".html", ".pdf") and not args.force:
        _err(args, f"{out} exists and isn't .html or .pdf; use --force to replace it")
        return EXIT_USAGE

    try:
        # Bytes, decoded here: without a UTF-8 locale, text-mode stdin would
        # let bad bytes through as surrogates that fail later in the render.
        raw = (
            sys.stdin.buffer.read()
            if args.input == "-"
            else Path(args.input).read_bytes()
        )
        text = raw.decode("utf-8")
        doc = parse(text)
    except (InputError, OSError, UnicodeDecodeError) as exc:
        _err(args, str(exc))
        return EXIT_INPUT

    if args.pages is not None and args.pages < 1:
        _err(args, "--pages must be 1 or more")
        return EXIT_USAGE
    theme = args.theme or doc.meta.get("theme", "default")
    budget = args.pages or doc.meta.get("pages")
    try:
        pages, fit = None, None
        base = Path(args.input).parent if args.input != "-" else Path.cwd()
        if fmt == "html":
            data = to_html(doc, theme, base_dir=base).encode("utf-8")
        else:
            fit = fit_pdf(doc, theme, base_dir=base, budget=budget)
            data, pages = fit.data, fit.pages
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    except (RenderError, OSError) as exc:
        _err(args, str(exc))
        return EXIT_RENDER

    over = bool(fit and fit.cut_lines)
    if args.json:
        status = {
            "ok": not over,
            "path": str(out),
            "format": fmt,
            "pages": pages,
            "bytes": len(data),
        }
        if fit and budget:
            status.update(budget=budget, fit=fit.steps, cut_lines=fit.cut_lines)
        print(json.dumps(status))
    else:
        extra = f", {pages} page{'s' if pages != 1 else ''}" if pages else ""
        if fit and fit.steps and not over:
            extra += f", fit to {budget} with {' + '.join(fit.steps)}"
        line = f"rupa: wrote {out} ({fmt}{extra}, {len(data):,} bytes)"
        if over:
            line += (
                f"; over the {budget}-page budget at the tightest type:"
                f" cut about {fit.cut_lines} lines (a line of prose is about"
                f" {PROSE_WORDS_PER_LINE} words; a code line or table row is"
                " one line) and render again"
            )
        print(line)
    return EXIT_CHECKS if over else EXIT_OK


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
        return EXIT_INPUT
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
    except OSError as exc:  # --out is a file, or <pdf>.verify already is one
        _err(args, f"cannot write to {out}: {exc.strerror or exc}")
        return EXIT_INPUT
    if args.json:
        print(Path(report.manifest).read_text())
    else:
        print(report.summary())
    return EXIT_OK if report.ok else EXIT_CHECKS_FAILED


def _in_checkout(pkg: Path) -> bool:
    """True when the package is src/rupa in a repo, not an installed copy."""
    return pkg.parent.name == "src" and (pkg.parent.parent / "pyproject.toml").is_file()


def refs_main(argv: list[str]) -> int:
    from .verify import build_references

    p = argparse.ArgumentParser(
        prog="rupa refs", description="Rebuild a theme's reference pages."
    )
    p.add_argument("--theme", default="default")
    p.add_argument(
        "--out",
        help="output directory (default, in a source checkout only:"
        " src/rupa/references/<theme>/)",
    )
    args = p.parse_args(argv)
    pkg = Path(str(resources.files("rupa")))
    if not args.out and not _in_checkout(pkg):
        # The default would overwrite the reference pages of an installed copy.
        _err(args, "this rupa is installed, not a source checkout; give --out")
        return EXIT_USAGE
    sample = (resources.files("rupa") / "references" / "sample.md").read_text(
        encoding="utf-8"
    )
    try:
        data, _ = to_pdf(parse(sample), args.theme)
    except RenderError as exc:
        _err(args, str(exc))
        return EXIT_RENDER
    out = Path(args.out) if args.out else pkg / "references" / args.theme
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "sample.pdf"
        pdf.write_bytes(data)
        try:
            picked = build_references(pdf, out)
        except ValueError as exc:
            _err(args, str(exc))
            return EXIT_RENDER
        except OSError as exc:
            _err(args, f"cannot write to {out}: {exc.strerror or exc}")
            return EXIT_INPUT
    kinds = ", ".join(f"{k}=p{n}" for k, n in sorted(picked.items()))
    print(f"rupa: wrote references for '{args.theme}' to {out} ({kinds})")
    return EXIT_OK


class _Tee:
    """Pass writes through to a stream and keep a copy for the log."""

    def __init__(self, stream):
        self.stream, self.text = stream, []

    def write(self, s):
        self.text.append(s)
        return self.stream.write(s)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def _log_path() -> Path | None:
    value = os.environ.get("RUPA_LOG", "")
    if value.lower() in ("off", "0", "false", "no"):
        return None
    return Path(value) if value else Path.home() / ".rupa" / "log.jsonl"


# Each field is clipped, and a log past LOG_MAX_BYTES is moved to <log>.1
# (replacing the last one), so the log stays small and never grows unbounded.
LOG_FIELD_CHARS = 2000
LOG_MAX_BYTES = 1_000_000


def _tail(text: str, limit: int = LOG_FIELD_CHARS) -> str:
    # The end of a traceback or stderr is the part that names the error.
    text = text.strip()
    return text if len(text) <= limit else "..." + text[-(limit - 3) :]


def _log(argv, code, out: _Tee, err: _Tee, crash: str | None = None) -> None:
    path = _log_path()
    if path is None:
        return
    entry = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": __version__,
        "cwd": str(Path.cwd()),
        "argv": [_tail(a, 200) for a in argv],
        "exit": code,
        "stdout": _tail("".join(out.text)),
        "stderr": _tail("".join(err.text)),
    }
    if crash:
        entry["traceback"] = _tail(crash)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > LOG_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))
        # Entries quote error messages, which can quote the document: owner only.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            os.chmod(path, 0o600)  # a log made by an older rupa may be 0644
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # logging must never change what the CLI does


def _dispatch(argv: list[str]) -> int:
    if argv and argv[0] == "verify":
        return verify_main(argv[1:])
    if argv and argv[0] == "refs":
        return refs_main(argv[1:])
    return render_main(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out, err = _Tee(sys.stdout), _Tee(sys.stderr)
    sys.stdout, sys.stderr = out, err
    code, crash = EXIT_OK, None
    try:
        code = _dispatch(argv)
        return code
    except SystemExit as exc:  # argparse usage errors, --help, --version
        code = exc.code if isinstance(exc.code, int) else int(exc.code is not None)
        raise
    except Exception:
        code, crash = 1, traceback.format_exc()
        raise
    finally:
        sys.stdout, sys.stderr = out.stream, err.stream
        if code:
            _log(argv, code, out, err, crash)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
