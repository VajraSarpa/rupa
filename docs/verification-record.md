# Appendix: Verification record

This is the record of verifying this document with the loop it describes. Each pass ran `rupa verify` with the default wants, then a visual review of the sheets against the rubric. The verdicts are Claude's, written one line per sheet as the skill asks.

## Pass 1: the first delivered version

The first version ran to 31 pages, before the verification sections existed.

**Code checks:** `verify: 7/8 checks pass (FAIL near-empty p11,30); 5 sheets`

| Sheet | Verdict |
|---|---|
| p1 cover | PASS |
| p7 table | PASS |
| p11 prose | FAIL page balance: one table row (Sustainability) alone on a page before Part 3 |
| p21 code | FAIL overflow: CSS lines broken mid-word, `1px s` / `olid` |
| p30 prose | FAIL page balance: the last four items of a list alone on a page before the closing part |

Two of the three failures were also flagged by the code checks. The third, the mid-word break, was visible only in the image: the text stayed inside the margins, so `overflow` passed.

**Fixes.** The lone row was a content fix: Cost optimization and Sustainability became one row. The list tail resolved once the new sections moved the page breaks. The mid-word break could only be fixed in the theme, so the loop would have reported it rather than patched it. It was fixed by hand in `print.css` (plain `pre-wrap`), and the long lines in the source files were shortened.

## Pass 2: after adding verification

**Code checks:** `verify: 8/8 checks pass; 4 sheets`

All four rendered pages passed. The review failed the reference instead: the code reference showed the top of a code block that continued onto a sixth page, so the comparison was against half a page. An edit to the sample document had added blank lines. The sample was trimmed, and `rupa refs` now refuses a sample whose page for any type spills over. Two tests cover that.

## Final pass

**Code checks:** `@@final-line@@`

| Sheet | Verdict |
|---|---|
@@final-rows@@

Cost of this pass: @@sheet-count@@ sheets at about 2,000 input tokens each, against roughly @@full-cost@@ tokens to look at all @@page-count@@ pages at full resolution.
