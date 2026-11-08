# WEBSITE_SESSION_NOTES — the landing page workstream

> **READ THIS FIRST, EVERY SESSION.** Then `git log --oneline -15`, `git status`,
> and [`WEBSITE_BUILD_SPEC.md`](WEBSITE_BUILD_SPEC.md). Notes drift; the repo is
> the truth.
>
> **Update this file and commit it before stopping or before context runs low.**
> A cold session must be able to resume from this file plus the repo, with zero
> input from the owner.

Scope: `site/` only. This workstream does **not** touch `decision/`, `tools/`,
`tests/`, `README.md`, or the root `SESSION_NOTES.md`.

---

## Status

**Last updated: 2026-11-08.**

| Piece | State |
| --- | --- |
| `WEBSITE_BUILD_SPEC.md` | **written** — direction settled (see spec §2) |
| `WEBSITE_SESSION_NOTES.md` | this file |
| `verify_claims.py` | **written** — regenerates every page number from the engine |
| `tools/probe.mjs` | **written** — zero-dependency CDP DOM-measurement probe |
| Act I — The Anti-Hero Hand | **built, probed, committed** (`1f4c24b`) |
| Act II — The Cost Of Not Guessing | **built, probed, committed** (`1f4c24b`) |
| Act III — The Ladder | **built, probed, committed** (`77f544e`) |
| Act IV — 1 In 156 | **built, probed — not yet committed** |
| Act V — The Verdict | **not started** |
| Coda — The Repo | **not started** |
| Left-hand act rail (spec §3) | **not started** — polish, do last |

**Next action:** commit Act IV, then build **Act V — The Verdict**, then the
Coda, then the act rail. Every figure Act V needs is already in
`verify_claims.py::check_simulation` and in "Simulation re-run" below.

---

## State of the repo when this workstream started

- A prior session (2026-11-08, earlier) had already written **Act I** into
  `site/index.html` — 734 lines, untracked, **with no spec and no notes**. That
  session's reasoning survives only in the file's own CSS comments. The build
  spec and these notes were written retroactively to capture it, and Act I is
  kept rather than rewritten: it is good work and it establishes the art
  direction the rest of the page extends.
- Everything else in `site/` is new in this workstream.

---

## Verified numbers — and where each came from

**Rule: nothing goes on the page that `verify_claims.py` cannot regenerate.**

```bash
python site/verify_claims.py            # fast: river, table, simulation summary
python site/verify_claims.py --flop     # + the trap reproduction and 5 flop decides (~60 s)
python site/verify_claims.py --sim DIR  # + summarise _simout/ output
```

It asserts, not just prints — a drifted number fails the run.

### The anti-hero hand — `river.decide(2c3d, As Ks Qs Js Ts)`

- `dealer_combos = 990`, `wins = 0`, `pushes = 990`, equity **0.0000%**
- `ev_bet = +0.0000`, `ev_fold = −2.0000`, margin `+2.0000`, `action = BET`
- `player_hand = Royal Flush` — the board plays, so the player's cards are
  irrelevant. Confirmed: `Ah Kh`, `7h 2s`, `9c 9d`, `Ac Ad` all return the
  identical decision object on that board.

### The Act III ladder — the seven rungs, in page order

Every row asserted by `check_ladder()`, including the bar geometry.

| Hand | Board | Verdict | EV bet | EV fold | Margin | `--l` / `--w` |
| --- | --- | --- | --- | --- | --- | --- |
| 7♣ 2♦ | K♠ Q♥ J♦ 8♠ 3♣ | **FOLD** | −2.2899 | −2.0000 | −0.2899 | 17.75 / 7.25 |
| A♥ K♥ | Q♥ J♥ 2♣ 7♦ 9♠ | BET | −1.5343 | −2.0000 | +0.4657 | 25 / 11.64 |
| A♣ K♦ | Q♠ J♥ 8♦ 4♣ 2♥ | BET | −1.4859 | −2.0000 | +0.5141 | 25 / 12.85 |
| 9♥ 9♦ | K♠ Q♥ J♦ 4♣ 2♠ | BET | −0.4495 | −2.0000 | +1.5505 | 25 / 38.76 |
| 2♣ 3♦ | A♠ K♠ Q♠ J♠ T♠ | BET | +0.0000 | −2.0000 | +2.0000 | 25 / 50 |
| 7♥ 7♦ | 7♠ 7♣ 2♦ 9♥ 4♣ | BET | +12.0000 | −2.0000 | +14.0000 | 25 / 75 (break) |
| A♠ 2♦ | K♠ Q♠ J♠ T♠ 9♣ | BET | +502.0000 | −2.0000 | +504.0000 | 25 / 75 (break) |

The bar scale is fixed at −1…+3 units across 0–100%, so zero sits at 25% and one
unit is 25% of the width. **The verifier recomputes `--l`/`--w` from each row's
own margin and asserts they match** — a hand-edited percentage cannot drift.

### The flop trap — now regenerated, not remembered

`reproduce_the_trap()` in `verify_claims.py` re-runs the buggy enumeration
(`combinations(deck, 4)`, then `draw[:2]` to the dealer) so the page's headline
claim is machine-checked:

- true push rate for `7c 2d` on `Ks Qh Jd`: **14.5169%** (page: 14.5%)
- the trap's push rate: **55.24%** (page: 55%) — **3.8× too high**
- space visited: `C(47,4)/C(47,2)/990 = 1/6.00` (page: "a sixth")

### The 169-class table — read from `tools/preflop_table.json`

- `meta.seed = 20261101`, `trials = 2_000_000`, `boards = 6_000`, generated
  `2026-11-01T05:30:37Z`.
- **BET 83 / CHECK 86**, confirming the root notes.
- **2♣3♦ is the WORST of all 169 classes by win rate** — 29.2253%. See the
  correction below.
- 7♠2♦ (as 7♥2♠ on the page): wins **31.7169%**, `check_value −0.9599`.
- Best: AA 84.96%, KK 82.08%, QQ 79.63%.

### Act IV/V numbers — from the simulation

| Figure | Value | Source |
| --- | --- | --- |
| realised sd / hand | **4.2 units** (4.2166 headline, 4.2110 deep) | re-run, confirmed |
| edge | **−0.0270 ± 0.0076** units/hand | root notes, 35,000 hands |
| signal : noise | 4.2 / 0.027 = **155.6 → "1 in 156"** | arithmetic |
| realised, 10,000 hands | **−0.1449** units/hand | re-run, confirmed exactly |
| realised, pooled 20,000 | **+0.0036** units/hand | root notes |
| published optimum | **−2.185%** of the ante; engine **0.68σ** away | root notes |
| ruin table, 10,000 hands | 97 / 81 / 57 / 17 / 2 % for 40 / 200 / 400 / 800 / 1,200 antes | root notes |

---

## Corrections made to inherited copy

1. **"the second-worst of all 169 starting hands"** (Act I). By the engine's own
   table 2♣3♦ is the **worst by win rate** (29.2253%) — 7♠2♦, which poker players
   conventionally call the worst hand, wins *more* often (31.7169%). It is
   second-worst only by `check_value` (−0.9287 vs 7♠2♦'s −0.9599). The copy now
   states the win-rate fact. **This turned into one of the best beats on the
   page** — two defensible answers to "the worst hand", and the engine only
   cares about one of them.
2. **The "six classes inside the noise" count.** README says six; the notes'
   tier-2 *rule* is `|margin| < 3×SE`, which actually selects **20**. Six is
   right for `|margin| < 1×SE`. Both are defensible; the page quotes no count.
3. **The Act II trap aside said "14%"** for the true push rate. `decision/flop.py`
   and `tests/test_flop.py` both say **14.5%**, and the guard test names the hand
   (`7c 2d` on `Ks Qh Jd`). The page now says 14.5% and the verifier recomputes
   it from `enumerate_flop_outcomes`.
4. **The Act III folk-wisdom aside named the wrong hands.** It showed 7♠2♦ and
   3♠2♦; the table's representatives are `2s 7h` and `2s 3h`, and 3♠2♦ is not
   the hand the page opened with. It now uses **7♥2♠** and **2♣3♦** — the
   anti-hero — so the aside closes the loop back to Act I instead of introducing
   a third hand. The figures (29.2% / 31.7% / −0.96 / −0.93) were already right.
5. **The aside eyebrow** read "The hand the engine cannot tell from a loss",
   which describes nothing in its body. Now **"The conventional answer"**,
   parallel to Act II's "The faster wrong answer".
6. **`.trap` → `.aside`** throughout. The block is no longer only a trap (Act III
   uses it for the folk-wisdom note). The CSS had been renamed but the HTML had
   not, which left both asides unstyled for one build — worth remembering as a
   failure mode of a partial rename.

---

## Decisions taken (do not re-litigate)

1. **Direction: C as spine, D as act four, B as texture, E dropped, A as act
   two.** Full reasoning in the build spec §2. The load-bearing argument is that
   the anti-hero hand already *is* the honest pitch, so "The Overheated Sell"
   would replace a true hook with a false one.
2. **Keep the prior session's Act I** rather than rewriting it. Its art
   direction — graphite/bone, Instrument Serif + Archivo + JetBrains Mono,
   hairlines, the deck as the only chroma — is the direction the whole page now
   extends.
3. **Semantic type split: serif = the page, mono = the engine.** Any number the
   engine produced is set in mono. Act numerals and the page's own voice are
   serif.
4. **Two accents with meaning:** `--ice` (#cfe2dc) is the engine,
   `--card-red` (#c2312c) is the deck. Everything else is monochrome. Losses are
   never red.
5. **Motion is a language:** deal, accumulate, rule, trace, stop. No universal
   fade-up-on-scroll. Each act's motion is its own argument.
6. **The unfixed `format_report` bug stays on the page** (build spec §7). It is
   already public in the README; omitting it would contradict the page's thesis.
   Flagged to the owner as reversible in one edit.
7. **Act IV's rail is drawn, not asserted.** 156 hairlines in the markup with
   exactly one lit, so the 1-in-156 ratio can be counted rather than believed.
   The count is load-bearing: if the number moves, the markup must move with it.
8. **Act IV's ruin meters use one hue.** The bar length already encodes the
   value and the percentage is printed at the end of every row, so colour has
   nothing left to encode. A ramp here would double-encode.
9. **Deviation from the `dataviz` skill, deliberate:** the skill's anti-patterns
   say a hero figure should use the same sans as everything else and never a
   serif. This page's type system assigns figures to Instrument Serif by
   design, and Acts II–IV already do it (`.ledger__count`, `.rung__action`,
   `.aside__stat dd`, `.figure-tile__value`). Consistency inside the page wins;
   noted here so it is a decision and not an accident.

---

## Open questions / loose ends

- **Build spec §7** — the `format_report` disclosure. Owner informed; build
  proceeds with it in. One edit to reverse.
- **Flop timing differs from the repo.** The repo records ~8.3 s for the exact
  flop decision; this machine measures **10.19 s**. The buggy version measures
  **3.4 s** against the docstring's 2.7 s — the same ~1.25× factor, so the ratio
  (~3×) is stable and the absolute numbers are machine-dependent. The page
  quotes the repo's own figures ("2.7 seconds", "about nine") and this
  discrepancy is flagged to the owner rather than silently normalised.
- **Hosting caveat.** `site/index.html` is written in Artifact format: no
  `<!doctype>`, `<html>`, `<head>` or `<body>` — the publish wrapper supplies
  the skeleton. Served as a bare static file it still renders (browsers infer
  the structure) but it is not a standards-clean document. Decide before
  pointing a real domain at it.
- **The Act I pin is 5.4 viewports of scroll.** With six movements the page is
  ~12,900 px at 1440. If that reads as too long, the pin length is the dial.

---

## How to verify without eyes

**No screenshot or vision review** — it has repeatedly hit a 5 MB message limit
and killed sessions. Use the DOM probe instead; it reads the page and reports
text.

```bash
node site/tools/probe.mjs                              # default six widths
node site/tools/probe.mjs --widths 375,1440 --scroll   # + a full scroll pass
node site/tools/probe.mjs --widths 375,1440 --reduced  # prefers-reduced-motion
```

It launches headless Chrome, drives it over CDP with Node's built-in
`WebSocket` (no dependencies), and returns: viewport and document metrics,
`horizontalOverflow`, per-section top/height, elements outside the viewport,
console errors and exceptions, `ledgerCounts`, `readout`, `asideStats`,
`rungs` (each with its bar fill measured in pixels), `rail` (tick count, signal
count, line count, tick heights), `figures`, `meters`, and an `animated` opacity
map for everything the scroll drives.

Two traps it has already caught, both worth keeping in mind:

- **`getBoundingClientRect()` includes transforms.** A pending `scaleY(0)`
  reveal tween makes an element measure as zero height and hides a real CSS bug.
  The rail is measured with `offsetHeight` for this reason.
- **Whitespace and the `<i>` elements.** The rail's ticks are flex items, so the
  newlines between them in the markup are not rendered — but the signal tick is
  taller, so counting distinct `top` values over-counts lines. It counts
  distinct `bottom` values instead.

Checklist for any act before commit:

1. No horizontal overflow at 320 / 375 / 768 / 1024 / 1440 / 2560 px.
2. No console errors or exceptions at any width.
3. `--scroll` pass: every animated element lands at opacity 1.00 and every
   transform returns to identity; the readout shows the real verdict.
4. `--reduced`: `flat = true`, a complete stacked document, nothing hidden.
5. All quoted figures match `verify_claims.py` output.
6. Act heights sane — no accidental 10,000 px scroll gaps.

---

## Commands

```bash
# regenerate every number quoted on the page
python site/verify_claims.py
python site/verify_claims.py --flop

# the three simulations the page quotes (slow: ~1 s per hand)
python -m tools.simulate --hands 10000 --trials 1  --bankroll 50000   --max-bet 5000 --seed 20261106
python -m tools.simulate --hands 5000  --trials 1  --bankroll 1000000 --max-bet 5000 --seed 20261106
python -m tools.simulate --hands 2000  --trials 10 --bankroll 50000   --max-bet 5000 --seed 20261106

# probe the page (see "How to verify without eyes")
node site/tools/probe.mjs --widths 375,1440 --scroll

# serve the page locally
python -m http.server 8000 --directory site
```

`_simout/` holds the raw simulation output and probe JSON. It is gitignored —
everything in it is regenerable, and the numbers that matter are transcribed
into this file and into `verify_claims.py`.

---

## Simulation re-run (2026-11-08)

Three runs launched to independently confirm the root notes' figures. Throughput
is about **1 second per hand** (the flop sweep is 32 sampled runouts × 990 dealer
hands per hand), so 10,000 hands is ~3 hours and 20,000 is ~6.

| Run | Hands | Bankroll | R-B EV/hand | Realised/hand | Ruin | Status |
| --- | --- | --- | --- | --- | --- | --- |
| headline | 10,000 | 50,000 (40 antes) | −0.0440 ± 0.0136 | −0.1449 | hand 81 | **done — matches the notes exactly** |
| deep | 5,000 | 1,000,000 (800 antes) | −0.0405 ± 0.0193 | −0.1627 | hand 4,990 | **done — matches the notes exactly** |
| pooled | 10 × 2,000 | 10 × 50,000 | −0.0132 ± 0.0104 | +0.0036 | 8 of 10 | running at the time of writing |

Both completed runs reproduced the recorded figures to the digit, including
`ruin at hand 81` and `final bankroll −1,761,875` — the meaningless number the
known bug prints for a ruined run. That the bug reappears in an independent
re-run is worth knowing: it is not a stale observation.

The pooled run was still going when this file was last updated. **Read
`_simout/pooled.txt` and transcribe the result here before relying on the
"8 of 10" figure** — though it is already in the root `SESSION_NOTES.md` and in
the README, so the page is not blocked on it.
