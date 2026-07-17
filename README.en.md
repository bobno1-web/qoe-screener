# QoE Normalizer — Operating-Profit Quality Screening

Enter one company and the tool surfaces an **EBITDA bridge** plus **one-off adjustment
candidates** buried inside operating profit. You toggle adjustments on; **a human decides**
whether each is truly one-off. The tool only surfaces candidates exhaustively (recall first) —
it never asserts "this one is non-recurring."

Built for M&A due diligence: a fast read on how "high-quality" a target's operating profit is —
repeatable core earnings, or a number inflated/depressed by one-offs and accounting treatment.

> **Local only.** The server runs on this PC (127.0.0.1) and is never hosted. Due-diligence
> data never leaving the PC is the whole premise of this tool.

---

## 1. What it does

Four stages. The web app **only calls** this validated pipeline — it never reimplements the
recalculation formula or gates.

1. **Collect financials (screen)** — pulls multi-year operating income and operating cash flow
   from OpenDART and computes, by arithmetic, whether profit is backed by cash. No LLM.
2. **Surface candidates (surface)** — Claude reads the audit report and consolidated notes and
   surfaces gray-zone candidates (one-offs buried in COGS/SG&A, impairments/disposals below the
   line, etc.) **with citations**. The same input is run **3 times** to check run-to-run stability.
   A **second, above-the-line-only sweep** is added: it focuses only on the notes that compose
   operating expenses (expense-by-nature, COGS, SG&A, plus inventory / receivables-impairment /
   provisions detail), **selected structurally — not by account-name keywords** (a section's total
   must reconcile arithmetically to the COGS/SG&A income-statement lines, or the section must carry
   standard XBRL component concept codes such as inventory-writedown, credit-loss, provision-movement).
   This catches the subtle items (bad-debt expense, provision transfers) a single full-notes pass
   skims past; results are unioned with the first sweep. If nothing can be selected structurally,
   the company skips the second sweep (no guessing).
3. **Extract D&A** — deterministically pulls the EBITDA add-back (depreciation + amortization +
   right-of-use asset depreciation) from the notes, each number carrying its note source.
4. **Build the view (normalize)** — combines the above into a single HTML screen. Only
   above-the-line, adjustable candidates move EBITDA via toggles; reference items don't.

### One integrated page — ① Earnings quality → ② Adjusted EBITDA (scroll)

The tool has two axes: **(1) can the reported operating profit be trusted** (verified from
financials) and **(2) what's left after stripping one-offs** (notes discovery + adjustment).
Stripping one-offs is meaningless if the profit itself can't be trusted, so verification comes first.

The two axes are one story, so they live on **one vertically-stacked page** — ① Earnings quality at
the top, scroll down to ② Adjusted EBITDA. A **sticky top nav** (company · stock code · base year +
[① Earnings quality][② Adjusted EBITDA]) tames the longer page so an auditor moving between the two
axes never reloads or loses scroll position.

- **① Earnings quality** (from financials, deterministic): the 6 metrics below, computed by
  arithmetic only (no LLM), each carrying its statement-line source view.
  1. **OI vs operating cash flow** — is profit backed by cash (accrual = OI − OCF).
  2. **Accrual ratio** — accrual ÷ total assets and ÷ revenue, size-independent.
  3. **Receivables turnover** — AR ÷ revenue, collection days. Booking sales before collecting?
  4. **Inventory turnover** — inventory ÷ COGS, days on hand. Stock that may later impair?
  5. **EBITDA vs OCF** — our computed EBITDA vs actual operating cash (base year).
  6. **Operating-margin trend** — OI ÷ revenue. A sudden move is something to check.
  - **What it does NOT judge:** no thresholds, colors, or grades (normal ranges differ by industry —
    manufacturing carries inventory, services don't). The tool never labels a value safe/risky or
    good/bad and uses no verdict colors (sparklines are monochrome — shape only). Numbers and trends,
    honestly; a human judges. No peer/industry benchmark either — **a single company's own trend.**
- **② Adjusted EBITDA**: the result of stages 3–4; toggle one-offs buried in operating profit.

> The integrated report embeds both screens (self-contained), so you open a single file. The
> individual pages (`quality_`·`screen_`) also remain and can be opened directly.

### Why surface is fixed at 3 runs (no user option to lower it)

Run comparison is not cosmetic — it is the **premise of the defenses**: the display-position
stability gate (drop an item from adjustments if its above/unknown position flips across runs),
the reproducibility badge, and recall (union across runs) all stand on the 3 repeats. Lowering
it to 1 would silently kill those defenses while the user keeps trusting the result. So there is
no option to reduce the repeat count.

---

## 2. How to run

```
1. pip install -r requirements.txt     (first time only — the .bat/.sh below does this for you)
2. Double-click  start_qoe.bat  (Windows)   /   ./start_qoe.sh  (mac/Linux)
3. Your browser opens http://127.0.0.1:5000 automatically
4. Enter the 2 API keys (issuers below)  →  enter a company name or 6-digit stock code
5. Before running, the screen shows the **estimated cost and time** — if the same filing was already
   analyzed, **reuse the saved result (free, instant)**; otherwise click [Analyze fresh]
6. Watch progress: financials → notes discovery (x3) → D&A → build view; then the integrated report
```

- Keep the console window **open**; closing it stops the server. Stop with Ctrl+C or by closing it.
- Banks / insurers / securities firms are **out of scope** (different income-statement structure).
- **Result reuse (free).** If the same company and same filing (business-report receipt number) was
  already analyzed, the saved result is fully reused (0 Claude calls = free, instant). A newly filed
  business report triggers automatic re-analysis. Reuse re-runs only the deterministic build step, so
  accuracy is unaffected.

### Where to get the API keys

| Key | Purpose | Cost | Issuer |
|---|---|---|---|
| **OpenDART API key** | Filings, financials, notes | Free | <https://opendart.fss.or.kr/> |
| **Anthropic API key** | Note candidate discovery (Claude) | Paid, small | <https://console.anthropic.com/> |

Keys are **entered in the browser**. They live only in this PC's server-process **memory**,
briefly, and vanish when the server stops. They are **never written to files, logs, or outputs**,
and being local they never leave the PC. (For CLI use you may instead copy `.env.example` to
`.env` and fill in values — `.env` is already excluded by `.gitignore`.)

---

## 3. Expected run time

Measured by cold-running all six companies. Discovery now runs **two sweeps (full + above-the-line),
3× each** — surface time is the sum of both.

| Company | Sector | Discovery (1st+2nd, x3) | Rest | **Total** |
|---|---|--:|--:|--:|
| SK Hynix (000660) | semiconductors | 438s | ~3s | **~7.4 min** |
| Samsung Elec. (005930) | electronics | 415s | ~3s | **~7.0 min** |
| Lotte Chemical (011170) | chemicals | 441s | ~3s | **~7.4 min** |
| Korean Air (003490) | airline | 378s | ~3s | **~6.4 min** |
| NAVER (035420) | platform | 488s | ~3s | **~8.2 min** |
| Emart (139480) | retail | 471s | ~3s | **~7.9 min** |

- **Almost all of it is discovery (stage 2)** — the 1st (full notes) and 2nd (operating-expense notes)
  sweeps, three calls each.
- **The above-the-line 2nd sweep adds ~2–3 min per company** (previously ~5 min with one sweep → now
  ~6.5–8 min). The 2nd-sweep excerpt is small (~7–35K ch, opex notes only), but it is time traded for
  higher above-the-line recall.
- **Notes size does not track time** — run time is driven by discovery/reasoning output, not input length.
- **Financials, D&A, and view build take seconds** (DART responses are cached locally).
- **One-time cold-start cost:** on the very first run the corp-code master (~30 MB) is downloaded once.
- None of the six exceeded 10 minutes (max ~8.2 min for NAVER).

### Cost — about $5 per company, re-analysis free

Discovery calls Claude (Opus) 6 times (1st ×3 + 2nd ×3). One fresh analysis costs **about $4–$6 per
company** (scaling with notes length), taking **~6–9 min**. Before running, the `/preview` screen shows
that company's estimated cost and time (a measurement-anchored estimate — actual billing is Anthropic
usage), and if a saved analysis exists it flags **free on reuse**.

- **Prompt caching cuts input tokens by ~52%** (run 1 writes the cache, runs 2–3 read it — outputs
  unchanged). SK Hynix cold measurement: 6.9 min, input −51.7%.
- **Re-analyzing the same filing is $0** — the saved result is reused (see How to run).
- The model is **fixed to Opus** (cheaper models measurably lower discovery, recall, and tag stability,
  which does not fit a recall-first tool).

---

## 4. Example results (real outputs pre-computed, no key needed)

All public disclosure data. Open the **integrated report** in a browser without any key — one file
scrolls from ① Earnings quality (top) to ② Adjusted EBITDA (below), with a sticky nav. (While the
server runs, also served at `/demo/report_<stock-code>.html`.)

**Sector coverage (8): semiconductors · electronics · chemicals · airline · platform · retail ·
medical devices · semiconductor parts. Six large caps + two small/mid caps** — where small size makes
the note narrative thin, table structure still lifts above-the-line one-offs.

| Company | Sector | Size | Integrated report | What it shows |
|---|---|--|---|---|
| SK Hynix | semiconductors | large | **[report](out/results/report_000660.html)** | ① Margin 48.6%, inventory 135.6 d. ② Base EBITDA 61,095,958M. The 2nd sweep lifts inventory-writedown reversal (661,733) above the line; bad-debt / warranty-provision surface as reference. |
| Samsung Elec. | electronics | large | **[report](out/results/report_005930.html)** | ① Inventory 95 d, margin 13.1%. ② Base EBITDA 90,527,643M. The 2nd sweep newly surfaces bad-debt expense (144,508) and warranty provisions (reference — no verbatim placement evidence). IS/CIS split (§5). |
| Lotte Chemical | chemicals | large | **[report](out/results/report_011170.html)** | ① Operating loss → margin −5.1% (shown as-is). ② From a −943,116M loss the **EBITDA bridge is exact** (289,615). The 2nd sweep lifts inventory writedown & provision transfer above the line (evidence confirmed). |
| Korean Air | airline | large | **[report](out/results/report_003490.html)** | ① Receivable days 21.2, margin 4.4%. ② Base EBITDA 3,968,753M (incl. aircraft-lease depreciation); regular intangible amortization **blocked as D&A double-count**. Inventory-writedown reversal (8,485) is lifted above the line via the IAS 2 concept code even without an explicit "COGS" mention. |
| NAVER | platform | large | **[report](out/results/report_035420.html)** | ① Margin 18.3%, **inventory days N/A** (a platform — no cost of sales). ② Base EBITDA 2,953,437M. The 2nd sweep lifts stock-grant expense above the line. |
| Emart | retail | large | **[report](out/results/report_139480.html)** | ① Fast inventory (38.4 d), margin 1.1%. ② Base EBITDA 1,811,817M. Three variants of the same bad-debt expense are mutually excluded by the **same-amount lock** (no double-count). IS/CIS split (§5). |
| i-SENS | medical devices | small/mid | **[report](out/results/report_099190.html)** | ① Margin 2.5%, inventory 142.9 d. ② Base EBITDA 25.1 bn. **Table structure lifts inventory writedown (878,525) and bad-debt reversal (2,383,869) above the line** — even without verbatim evidence (stitched citation), they reconcile arithmetically to the COGS/SG&A tables. |
| KoMiCo | semiconductor parts | small/mid | **[report](out/results/report_183300.html)** | ① **EBITDA − OCF +124.1 bn** (EBITDA 162.3 bn ≫ OCF 38.2 bn — a primary earnings-quality signal), margin 18.4%. ② Inventory-writedown reversal (666,343) flipped position across runs, but **table structure confirms COGS placement** (table structure outranks the stability gate). Trade-receivable bad debt stays unknown (no table arithmetic). |

### Eight companies at a glance — earnings quality (base year 2025)

Deterministic from financials, with **no thresholds/colors/grades**. The tool places the numbers
side by side; it does not rank companies or assert causation. Large caps in trillions (tn),
small/mid caps in hundred-millions (₩0.1bn) due to the size gap.

| Company | Sector | Size | OP margin | AR collection days | Inventory days | Accrual (OI − OCF) | EBITDA − OCF |
|---|---|--|--:|--:|--:|--:|--:|
| SK Hynix | semiconductors | large | 48.6% | 68.4 d | 135.6 d | −6.2 tn | +7.7 tn |
| Samsung Elec. | electronics | large | 13.1% | 55.9 d | 95.0 d | −41.7 tn | +5.2 tn |
| Lotte Chemical | chemicals | large | **−5.1%** | 36.8 d | 58.3 d | −1.4 tn | −0.2 tn |
| Korean Air | airline | large | 4.4% | 21.2 d | 24.5 d | −3.0 tn | −0.1 tn |
| NAVER | platform | large | 18.3% | 51.2 d | **N/A** | −0.9 tn | −0.1 tn |
| Emart | retail | large | 1.1% | 18.6 d | 38.4 d | −1.0 tn | +0.5 tn |
| i-SENS | medical devices | small/mid | 2.5% | 77.9 d | 142.9 d | −3.9 bn | +5.0 bn |
| KoMiCo | semiconductor parts | small/mid | 18.4% | 50.8 d | 62.3 d | +7.7 bn | **+124.1 bn** |

*(Lotte's base-year operating loss → negative margin; NAVER, a platform, has no cost of sales, so
inventory days is "N/A" — not fabricated. KoMiCo's EBITDA far exceeds operating cash, so the EBITDA−OCF
gap is large — a primary earnings-quality signal. Individual pages live under [out/results/](out/results/).)*

### Source cross-check (independent verification)

For **2 of the 8 demo companies (the small/mid caps — i-SENS and KoMiCo), a separate agent independently
cross-checked** — reading only the DART source — whether items the tool tagged "above the line" (inside
operating income) are really there. Result: every item the tool placed above the line was genuinely inside
operating income (COGS, SG&A, salaries, benefits) — **zero baseless "false above-the-line."** The tool's
errors were all in the safe direction (over-conservative: unclear items pushed below-line → unknown), never
the dangerous one (below/unknown mis-tagged as above-line, which would corrupt EBITDA). The **small-cap
over-conservatism** this surfaced (an inventory writedown clearly booked to COGS in the table but demoted
because its citation was stitched, breaking the verbatim match) was then rescued by **table-structure
evidence** — by structure only (table arithmetic, inventory-writedown concept code), never account-name
keywords, keeping false above-the-line at zero. (A 2-company sample, not a blanket guarantee.)

*(Need the individual pages? `quality_`·`screen_` files remain in [out/results/](out/results/).)*

---

## 5. Design principles

- **No hardcoding, no keyword heuristics.** Candidates are not matched by account-name lists; the
  note narrative is read and reasoned about as "non-recurring." The same "subsidy" is normal if
  annual, a candidate if a one-off COVID grant — account names can't tell them apart. (Comparing
  against accounting-standard structure / XBRL standard concept IDs is universal structure, not a
  keyword, and is the exception.)
- **Recall first — the tool surfaces, a human judges.** The tool never asserts one-off status;
  when in doubt it surfaces. Lower precision from a wider net is expected, handled by the slider
  and the human.
- **No thresholds, colors, or grades.** Normal ranges differ by industry, so a line drawn by the
  tool would be wrong (manufacturing carries inventory, services don't). Earnings-quality metrics
  are never labeled risky/safe and use no verdict colors (sparklines are monochrome — shape only).
  Numbers and trends, shown honestly; the auditor judges. No peer comparison — a company's own trend.
- **Every number carries its source.** Each candidate cites the note and passage; income-statement
  lines are shown by reconstructing the statement from XBRL and highlighting the pulled row. No
  candidate is surfaced without a citation.
- **Layered double-count defense.** ① Table arithmetic confirms a total = its components and locks
  them (residual shown as a computed value); ② near-equal pairs scattered across different notes,
  unprovable by arithmetic, are estimate-locked (unlinkable); ③ candidates overlapping D&A already
  added back are stripped of adjustability by concept code.
- **If position is unknown, don't adjust (conservative).** Since EBITDA = OI + D&A adds back what
  was already subtracted, only items shown above the line are adjustable. If "above" isn't certain,
  it's left unknown and excluded (a 3-layer gate: prompt → XBRL/stability → code evidence). The primary
  evidence is the placement stated **verbatim in the citation**; but where a small-cap's citation is
  stitched and the verbatim match breaks, **table structure** (the amount reconciles arithmetically to
  the COGS/SG&A table, or sits in an inventory-writedown concept code) also confirms above-the-line —
  by structure only, never account-name keywords, and when table structure confirms it outranks
  run-to-run flip (the stability gate), same class as the XBRL determinism. Missed opportunities can be
  restored by a human via a **manual switch** after checking the source.

---

## 6. Limitations (full: [docs/limitations.md](docs/limitations.md))

- **Financials are out of scope** — banks/insurers/securities have a different income structure,
  so "OI + D&A" does not hold.
- **Small caps that file no consolidated statements cannot be processed** — the tool assumes CFS.
  A small company with no subsidiaries filing only separate statements returns an empty consolidated
  query and the tool honestly stops at the screen stage (it does not pass off 0 as success).
- **Operating-lease (lease-out) depreciation may be missed** — where leasing is the core business
  and such depreciation is booked separately in other operating P&L, it can fall out of the D&A
  add-back and understate EBITDA (measured: Shinhan ~5.5%).
- **IS/CIS-split filers lose one layer of XBRL position determinism** (Samsung, Emart) — companies
  placing operating income on the income statement rather than the comprehensive-income statement
  turn that one layer off, but the remaining defenses (prompt, stability, evidence gate) and the
  EBITDA computation still work.
- **Revenue-recognition quality and accounting estimates are out of scope** — "can I trust this
  number" (mileage breakage, depreciation start date) is not an "amount to remove." The primary
  earnings-quality signal is provided by section ①'s **accruals and turnover** (OI vs OCF,
  receivables/inventory turnover).
- **The tier-2 proximity "nature" condition has weak discriminating power** — the real defense is
  the single 99.5% proximity threshold; coincidentally close but unrelated items can be
  mis-locked (the user reverts with "unlink"). Totals and components that differ in amount but overlap
  conceptually are handled by this axis (exact-equal-amount double-counting is fully closed separately).
- **No peer/industry comparison** — earnings-quality metrics look only at a single company's own
  time series; the tool draws no industry-average or competitor line (judging the normal range is
  the human's job).

These limitations are **not auto-corrected**. The tool exposes raw values, paths, and sources;
correction and final judgment are for the human who reads the source.

> **Honestly.** This is a **first-pass screen**, not a complete checklist. There is no guarantee the
> tool surfaced everything (designed recall-first, but not an exhaustive guarantee). Recall is measured
> against an AI-drafted, deliberately-wide golden set, so **true recall (against every one-off in the
> source) is unknown**; only two small caps were hand-checked against the DART source. The final call
> must be made by an auditor who reads the source.

---

## License / data

- All example results are computed from **public disclosure data** (OpenDART).
- This tool only **surfaces** adjustment candidates; it does not make accounting or investment
  decisions for you.
