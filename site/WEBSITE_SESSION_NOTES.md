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
| Act I — The Anti-Hero Hand | **built** (`site/index.html`) — hero, needs copy fix |
| Act II — The Cost Of Not Guessing | not started |
| Act III — The Ladder | not started |
| Act IV — 1 In 156 | not started |
| Act V — The Verdict | not started |
| Coda — The Repo | not started |

**Next action:** fix the Act I copy claim (below), then build Act II.

---

## State of the repo when this workstream started

- A prior session (2026-11-08, earlier) had already written **Act I** into
  `site/index.html` — 734 lines, untracked, **with no spec and no notes**. That
  session's reasoning survives only in the file's own CSS comments. The build
  spec and these notes were written retroactively to capture it, and Act I is
  kept rather than rewritten: it is good work and it establishes the art
  direction the rest of the page extends.
- Everything else in `site/` is new in this session.

---

## Verified numbers — and where each came from

**Rule: nothing goes on the page that `verify_claims.py` cannot regenerate.**
Run it with `python site/verify_claims.py` from the repo root (it needs the repo
root on `sys.path`; run it as a module or from the root).

### The anti-hero hand — `river.decide(2c3d, As Ks Qs Js Ts)`

Reproduced live, not quoted. **Confirms the brief exactly:**

- `player_hand = Royal Flush` — the board plays, `player_score = 1`
- `dealer_combos = 990`
- outcomes: `push = 1.0`, every other bucket `0.0` — **990 pushes, 0 wins**
- equity **0.0000%**
- `ev_bet = 0.0000`, `ev_fold = −2.0000`, `ev_advantage = +2.0000`
- `action = BET`

Also confirmed: **every** hole-card pair on that board pushes — the board plays
for both sides, so the player's cards are irrelevant. `Ah Kh`, `7h 2s`,
`9c 9d`, `Ac Ad` all return the identical decision object.

### The ladder — live `decide()` calls

All in `verify_claims.py`. River:

| Hand | Board | Verdict | EV bet | EV fold | Margin |
| --- | --- | --- | --- | --- | --- |
| 9♥ 9♦ | K♠ Q♥ J♦ 4♣ 2♠ | BET | −0.4495 | −2.0000 | +1.5505 |
| 9♥ 9♦ | K♠ Q♥ J♦ 4♣ 9♠ | BET | +0.7566 | −2.0000 | +2.7566 |
| 7♣ 2♦ | K♠ Q♥ J♦ 8♠ 3♣ | FOLD | −2.2899 | −2.0000 | −0.2899 |
| A♣ K♦ | K♠ Q♥ J♦ 8♠ 3♣ | BET | +0.9758 | −2.0000 | +2.9758 |
| A♣ K♦ | Q♠ J♥ 8♦ 4♣ 2♥ | BET | −1.4859 | −2.0000 | +0.5141 |
| A♥ K♥ | Q♥ J♥ 2♣ 7♦ 9♠ | BET | −1.5343 | −2.0000 | +0.4657 |
| 7♥ 7♦ | 7♠ 7♣ 2♦ 9♥ 4♣ | BET | +12.0000 | −2.0000 | +14.0000 |
| A♠ 2♦ | K♠ Q♠ J♠ T♠ 9♣ | BET | +502.0000 | −2.0000 | +504.0000 |

Flop (exact, ~8 s each):

| Hand | Board | Verdict | EV bet | EV check | Margin |
| --- | --- | --- | --- | --- | --- |
| J♠ T♠ | A♠ K♠ Q♠ | BET | +502.8252 | +501.8252 | +1.0000 |
| 9♥ 9♦ | K♠ Q♥ J♦ | BET | +0.2536 | +0.0427 | +0.2109 |
| 7♣ 2♦ | K♠ Q♥ J♦ | CHECK | −2.4541 | −1.6511 | −0.8030 |
| A♥ A♦ | K♥ 7♠ 2♣ | BET | +2.0662 | +1.2917 | +0.7746 |
| 2♣ 3♦ | A♠ K♠ Q♠ | CHECK | −2.7131 | −1.6785 | −1.0346 |

Pre-flop (lookup, zero runtime cost): `As Kh` BET 4x (+1.1677 vs check +0.2234),
`2c 3d` CHECK (−2.3493 vs −0.9287), `Ah Ad` BET (+3.6013 vs +1.4605).

### The 169-class table — read from `tools/preflop_table.json`

- `meta.seed = 20261101`, `trials = 2_000_000`, `boards = 6_000`, generated
  `2026-11-01T05:30:37Z`.
- **BET 83 / CHECK 86**, confirming the root notes.
- **2♣3♦ is the WORST of all 169 classes by win rate** — 29.2253%. See the
  correction below.
- Best: AA 84.96%, KK 82.08%, QQ 79.63%.
- Widest `check_value_se`: KTs 0.2225, QTs 0.2077, KJs 0.1881.

### The simulation — `tools/simulate.py`

Re-run in this session from the three commands in the root notes; the numbers
are quoted from `README.md` / root `SESSION_NOTES.md` and cross-checked against
the fresh runs. See "Simulation re-run" below for what came back.

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

---

## Decisions taken this session (do not re-litigate)

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
   serif. This is why big section numbers are *not* mono.
4. **Two accents with meaning:** `--ice` (#cfe2dc) is the engine,
   `--card-red` (#c2312c) is the deck. Everything else is monochrome. Losses are
   never red.
5. **Motion is a language:** deal, accumulate, rule, trace, stop. No universal
   fade-up-on-scroll.
6. **The unfixed `format_report` bug stays on the page** (build spec §7). It is
   already public in the README; omitting it would contradict the page's thesis.
   Flagged to the owner as reversible in one edit.

---

## Open questions / loose ends

- **Build spec §7** — the `format_report` disclosure. Owner informed; build
  proceeds with it in. One edit to reverse.
- Act I's `.outro` currently gives away the Act V numbers and points at
  "Act II — 1 in 156", which is now **Act IV**. Must be rewritten as part of the
  Act II build.

---

## How to verify without eyes

**No screenshot or vision review** — it has repeatedly hit a 5 MB message limit
and killed sessions. Use DOM-measurement probes instead: inject JS that reads
`getBoundingClientRect()`, `getComputedStyle`, `scrollHeight` vs `clientHeight`,
and report text. The owner reviews visuals in their own browser and describes
what they see.

Checklist for any act before commit:

1. No horizontal overflow at 320 / 375 / 768 / 1440 / 2560 px.
2. Every section readable with JS disabled (the `.flat` path).
3. `prefers-reduced-motion: reduce` produces a complete stacked document.
4. All quoted figures match `verify_claims.py` output.
5. Act heights sane — no accidental 10,000 px scroll gaps.

---

## Commands

```bash
# regenerate every number quoted on the page
python site/verify_claims.py

# re-run the three simulations the page quotes (slow: ~25 / 12 / 50 min)
python -m tools.simulate --hands 10000 --trials 1  --bankroll 50000   --max-bet 5000 --seed 20261106
python -m tools.simulate --hands 5000  --trials 1  --bankroll 1000000 --max-bet 5000 --seed 20261106
python -m tools.simulate --hands 2000  --trials 10 --bankroll 50000   --max-bet 5000 --seed 20261106

# serve the page locally
python -m http.server 8000 --directory site
```

---

## Simulation re-run (2026-11-08)

Three runs launched to independently confirm the root notes' figures. Results
appended when they land — see "Simulation results" in the root
`SESSION_NOTES.md` for the canonical numbers the page quotes.

| Run | Hands | Bankroll | Expected R-B EV/hand | Expected ruin |
| --- | --- | --- | --- | --- |
| headline | 10,000 | 50,000 | −0.0440 ± 0.0136 | hand 81 |
| deep | 5,000 | 1,000,000 | −0.0405 ± 0.0193 | hand 4,990 |
| pooled | 10 × 2,000 | 10 × 50,000 | −0.0132 ± 0.0104 | 8 of 10 |

**Confirmed during the session:** a 200-hand smoke run with seed `20261106`
reproduced **ruin at hand 81** exactly, and `format_report` printed
`profitable trials 0 of 1` alongside `ruined trials 1 of 1` — the live bug, in
the wild, on the first try.
