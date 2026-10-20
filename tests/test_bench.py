"""Bench v2 plumbing, run against bench/fake/claude: no tokens are spent."""

import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rupa.document import parse
from rupa.render import to_pdf

ROOT = Path(__file__).parent.parent
BENCH = ROOT / "bench"
needs_pdftotext = pytest.mark.skipif(
    not shutil.which("pdftotext"), reason="no pdftotext"
)


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(BENCH))
    spec.loader.exec_module(module)
    return module


def bench(tmp_path: Path, runs: int = 1, **env) -> subprocess.CompletedProcess:
    full = {
        **os.environ,
        "PATH": f"{BENCH / 'fake'}:{os.environ['PATH']}",
        "RESULTS_ROOT": str(tmp_path),
        "FREEZE_TAG": "off",
        "SEED": "test",
        **env,
    }
    return subprocess.run(
        ["bash", str(BENCH / "bench.sh"), str(runs)],
        env=full,
        capture_output=True,
        text=True,
        check=False,
    )


def only_folder(tmp_path: Path) -> Path:
    (folder,) = [p for p in tmp_path.iterdir() if (p / "manifest.json").exists()]
    return folder


def test_bench_interleaves_arms_and_keeps_each_run(tmp_path):
    done = bench(tmp_path, runs=3, TASK="guide")
    assert done.returncode == 0, done.stderr
    folder = only_folder(tmp_path)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["arms"] == ["baseline", "baseline-hinted", "rupa-verify"]
    assert manifest["isolation"] == "--setting-sources project --strict-mcp-config"
    order = [
        json.loads(line)
        for line in (folder / "manifest.jsonl").read_text().splitlines()
    ]
    assert len(order) == 9
    by_run = [[e["arm"] for e in order if e["run"] == i] for i in (1, 2, 3)]
    assert all(sorted(r) == sorted(manifest["arms"]) for r in by_run)
    assert len({tuple(r) for r in by_run}) > 1  # the order is shuffled per run
    for arm in manifest["arms"]:
        for i in (1, 2, 3):
            assert (folder / f"{arm}-{i}.pdf").is_file()
            assert (folder / f"{arm}-{i}.work").is_dir()
            assert json.loads((folder / f"{arm}-{i}.json").read_text())["num_turns"] > 0
    for arm in manifest["arms"]:
        args = (folder / f"{arm}-1.work" / ".fake-args").read_text().splitlines()
        assert "--strict-mcp-config" in args
        assert args[args.index("--setting-sources") + 1] == "project"
        assert args[args.index("--model") + 1] == "claude-opus-5-5"
        assert ("--plugin-dir" in args) == arm.startswith("rupa")
    hinted = (folder / "baseline-hinted-1.work" / "CLAUDE.md").read_text()
    assert "google-chrome" in hinted
    assert not (folder / "baseline-1.work" / "CLAUDE.md").exists()


def test_failed_runs_count_against_their_arm(tmp_path):
    done = bench(tmp_path, runs=2, TASK="report", FAKE_FAIL="baseline-hinted")
    assert done.returncode == 0, done.stderr
    export = load("export")
    rows = export.v2_runs(tmp_path)
    summary = {s["arm"]: s for s in export.v2_summary(rows)}
    assert summary["baseline-hinted"]["successes"] == 0
    assert summary["baseline-hinted"]["cost_per_success"] == ""
    assert summary["baseline"]["successes"] == 2
    # Contamination: the fake baseline loads no Rupa skill.
    assert not any(r["contaminated"] for r in rows)


def test_session_task_resumes_and_keeps_every_output(tmp_path):
    done = bench(tmp_path, TASK="revise", ARMS="baseline rupa-verify")
    assert done.returncode == 0, done.stderr
    folder = only_folder(tmp_path)
    for arm in ("baseline", "rupa-verify"):
        assert (folder / f"{arm}-1.s1.pdf").is_file()
        assert (folder / f"{arm}-1.s2.pdf").is_file()
        result = json.loads((folder / f"{arm}-1.json").read_text())
        assert len(result["steps"]) == 2
        assert result["num_turns"] == sum(s["num_turns"] for s in result["steps"])
        # The second step resumed the first step's session.
        assert result["steps"][1]["session_id"] == result["steps"][0]["session_id"]


def test_export_v2_writes_csvs(tmp_path):
    bench(tmp_path / "results", TASK="report")
    export = load("export")
    export.main_v2([str(tmp_path / "results"), str(tmp_path / "data")])
    with (tmp_path / "data" / "runs.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert {r["arm"] for r in rows} == {"baseline", "baseline-hinted", "rupa-verify"}


def test_bench_refuses_unknown_arm(tmp_path):
    done = bench(tmp_path, ARMS="baseline nope")
    assert done.returncode == 2
    assert "unknown arm nope" in done.stderr


@pytest.mark.skipif(
    subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "v0.1.0"],
        capture_output=True,
        check=False,
    ).returncode,
    reason="no v0.1.0 tag in this checkout",
)
def test_bench_refuses_when_rupa_differs_from_the_freeze_tag(tmp_path):
    done = bench(tmp_path, FREEZE_TAG="v0.1.0")
    assert done.returncode == 2
    assert "differ from v0.1.0" in done.stderr


def test_result_sums_session_steps():
    result = load("result")
    steps = [
        {
            "num_turns": 3,
            "total_cost_usd": 0.1,
            "duration_ms": 1000,
            "usage": {"output_tokens": 5},
        },
        {
            "num_turns": 4,
            "total_cost_usd": 0.2,
            "duration_ms": 2000,
            "usage": {"output_tokens": 7},
        },
    ]
    out = result.combined(steps, 2, 0)
    assert out["num_turns"] == 7
    assert out["usage"]["output_tokens"] == 12
    assert "error" not in out
    assert "error" in result.combined(steps[:1], 2, 1)
    assert result.combined([], 1, 124) == {"error": "no result event", "exit": 124}


DOC = """---
title: Quality check sample
---

## Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
"""
DOC += "".join(
    f'    {{"Sid": "S{n}", "Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}},\n'
    for n in range(60)
)
DOC += """    {"Sid": "Last", "Effect": "Deny", "Action": "*", "Resource": "*"}
  ]
}
```

## Checklist

1. Inventory the accounts.
2. Enable the service.
3. Assign permission sets.
4. Remove the old users.
"""


@needs_pdftotext
def test_quality_reads_a_json_block_across_a_page_break(tmp_path):
    quality = load("quality")
    data, _ = to_pdf(parse(DOC))
    pdf = tmp_path / "q.pdf"
    pdf.write_bytes(data)
    checks = quality.check(
        pdf,
        {
            "pages": 1,
            "json_min_lines": 60,
            "numbered_min": 4,
            "phrases": ["Inventory the accounts", "not in it"],
        },
    )
    assert checks["json"]["ok"] is True, checks["json"]
    assert checks["numbered"]["ok"] is True
    assert checks["pages"]["ok"] is False  # the policy runs past one page
    assert checks["phrases"]["ok"] is False
    assert "not in it" in checks["phrases"]["detail"]
    assert checks["in_bounds"]["ok"] and checks["min_font"]["ok"]


@needs_pdftotext
def test_quality_json_not_found_is_unknown_not_failed(tmp_path):
    quality = load("quality")
    data, _ = to_pdf(parse("## No code here\n\nJust prose.\n"))
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(data)
    checks = quality.check(pdf, {"json_min_lines": 25, "numbered_min": 3})
    assert checks["json"]["ok"] is None
    assert checks["numbered"]["ok"] is None


def test_quality_html_flags_remote_resources(tmp_path):
    quality = load("quality")
    page = tmp_path / "x.html"
    page.write_text(
        '<link rel="stylesheet" href="https://cdn.example.com/a.css">'
        "<h1>TLS 1.3</h1><ol><li>a</li><li>b</li></ol>"
    )
    checks = quality.check(
        page, {"format": "html", "phrases": ["tls 1.3"], "numbered_min": 2}
    )
    assert checks["html_self_contained"]["ok"] is False
    assert checks["phrases"]["ok"] and checks["numbered"]["ok"]
    assert quality.check(tmp_path / "missing.html", {}) == {
        "exists": {"ok": False, "detail": "no output"}
    }


@needs_pdftotext
@pytest.mark.parametrize("width_pt, inside", [(675, False), (400, True)])
def test_quality_in_bounds_counts_images(tmp_path, width_pt, inside):
    # Bench v2's lab reports placed a 900x600 chart 675pt wide from a 58pt
    # margin on a 612pt page; in_bounds read only text and passed them.
    import weasyprint
    from PIL import Image

    quality = load("quality")
    Image.new("RGB", (900, 600), (30, 110, 140)).save(tmp_path / "chart.png")
    html = (
        "<style>@page { size: letter; margin: 58pt }</style>"
        f'<p>Figure 1</p><img src="chart.png" style="width: {width_pt}pt">'
    )
    pdf = tmp_path / "wide.pdf"
    weasyprint.HTML(string=html, base_url=str(tmp_path)).write_pdf(pdf)
    checks = quality.check(pdf, {})
    assert checks["in_bounds"]["ok"] is inside, checks["in_bounds"]
    assert (
        checks["in_bounds"]["detail"] == f"0 chars, {0 if inside else 1} images outside"
    )


def test_human_candidates_filter_by_seed(tmp_path):
    human = load("human")
    for name, seed in (("old-cv", "main"), ("new-cv", "v013")):
        folder = tmp_path / name
        for stem in ("rupa-verify-1", "baseline-1", "baseline-hinted-1"):
            (folder / "pages" / stem).mkdir(parents=True)
        (folder / "steps").mkdir()
        (folder / "steps" / "1.txt").write_text("request")
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "model": human.MODEL,
                    "task": "cv",
                    "steps": 1,
                    "runs": 1,
                    "seed": seed,
                }
            )
        )
    assert {c["folder"] for c in human.candidates(tmp_path)} == {"old-cv", "new-cv"}
    assert {c["folder"] for c in human.candidates(tmp_path, seed="v013")} == {"new-cv"}
