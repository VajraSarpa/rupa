"""A table that breaks across pages must not strand one or two rows.

The sweep moves the page break through every row position by adding one
lead-in paragraph per step, so a fragment shows up wherever the break lands.
"""

import io
import re

import pdfplumber
import pytest

from rupa.document import parse
from rupa.render import to_pdf

ROWS = 9
MIN_ROWS = 2


def doc(lead_ins: int) -> str:
    filler = "\n\n".join(f"Lead-in paragraph {i}." for i in range(lead_ins))
    rows = "\n".join(f"| R{i:02d} | Event number {i} happened |" for i in range(ROWS))
    return f"# Postmortem\n\n{filler}\n\n| Time | Event |\n|---|---|\n{rows}\n"


def rows_per_page(markdown: str, theme: str = "default") -> list[int]:
    data, _ = to_pdf(parse(markdown), theme)
    counts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            text = pg.extract_text() or ""
            counts.append(len(re.findall(r"^R\d\d ", text, re.MULTILINE)))
    return counts


def test_sweep_reaches_a_page_break_inside_the_table():
    # Guards the sweep itself: it must actually split the table somewhere.
    split = [
        c
        for n in range(0, 40, 2)
        if len(c := [x for x in rows_per_page(doc(n)) if x]) > 1
    ]
    assert split, "no lead-in length put the table across a page break"


@pytest.mark.parametrize("theme", ["default", "cyan"])
def test_table_fragments_hold_at_least_two_rows(theme):
    for n in range(40):
        counts = [c for c in rows_per_page(doc(n), theme) if c]
        assert sum(counts) == ROWS
        if len(counts) > 1:
            assert min(counts) >= MIN_ROWS, (
                f"{theme}: {n} lead-in paragraphs left a fragment: {counts}"
            )
