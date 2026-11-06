# Ultimate Texas Hold'em — Decision Engine

A decision engine for Ultimate Texas Hold'em that computes the mathematically
correct play on every street, plus a bankroll simulator that plays complete
hands through it and reports what a bankroll does over thousands of them.

**Status: concluded.** The decision engine is complete, tested and simulated.
The perception and action layers described in the build spec were never built
and are not planned — the project ends at the decision boundary.

---

## Headline result

Simulated over **35,000 hands**, the engine **loses 2.70% ± 0.76% of an ante per
hand**.

That is the published optimal figure for Ultimate Texas Hold'em (2.185%). The
gap is 0.68σ — **the engine plays this game essentially as well as it can be
played, and the loss is the house edge, not a defect.** No strategy beats this
game; the question was only whether this one is close to optimal, and it is.

Read any single run and you would be misled — the 10,000-hand run alone says
−4.4% and the 20,000-hand pooled run alone says −1.3%. Only the pooled estimate
over all three runs is meaningful. Details in
[SESSION_NOTES.md](SESSION_NOTES.md).

### What that means for a bankroll

The edge is tiny next to the variance: **~4.2 units of swing per hand against a
0.027-unit edge**, a signal-to-noise ratio of about **1:156**. A session's
realised profit or loss is therefore almost pure noise — in the pooled run,
20,000 hands realised a *profit* on a game that loses.

Stack size relative to the ante is what decides whether you survive long enough
to see any of it:

| Stack | Example | Ruin over 10,000 hands |
| --- | --- | --- |
| 40 antes | 50,000 chips @ 5,000 max bet | ~97% |
| 400 antes | 500,000 chips | ~57% |
| 800 antes | 1,000,000 chips | ~17% |
| 1,200 antes | 1,500,000 chips | ~2% |

Measured: at 40 antes, **8 of 10 simulated bankrolls went broke.** A 50k bankroll
with a 5k max bet is unplayable — not because the strategy is bad, but because
the bet is far too large for the stack.

---

## Quickstart

Requires Python 3.10+ and [`treys`](https://pypi.org/project/treys/).

```bash
pip install treys
python -m pytest                                    # 146 tests, ~2 minutes
python -m tools.simulate --hands 10000 --trials 1 --bankroll 50000 --max-bet 5000
```

**Use `python -m`, not `python tools/simulate.py`.** The repo root is only on
`sys.path` under `-m` (or pytest's `pythonpath = .`); running a script by path
fails with `ModuleNotFoundError: No module named 'decision'`.

The test suite takes ~2 minutes, almost all of it `tests/test_flop.py` — an
exact flop decision costs ~8s. Everything expensive is computed once in
module-scoped fixtures; don't convert those to per-test calls.

---

## Architecture

```
              decision/  (pure logic, no I/O, no screen)
  ┌───────────────────────────────────────────────────────────┐
  │  evaluator  →  ev  →  river  →  flop  →  preflop          │
  └───────────────────────────────────────────────────────────┘
                              ↑
                    tools/simulate.py  (spends the answers)
```

| Module | What it does | Exactness | Tests |
| --- | --- | --- | --- |
| `decision/evaluator.py` | `treys` wrapper; `best_hand_rank(hole, board)` | exact | 11 |
| `decision/ev.py` | 5-bucket payout model, EV, breakeven thresholds | exact | 25 |
| `decision/river.py` | Bet 1x or fold, given all 5 board cards | **exact** — C(45,2) = 990 dealer hands | 20 |
| `decision/flop.py` | Bet 2x or check, given 3 board cards | **exact** — 1,081 runouts × 990 = 1,070,190 | 18 |
| `decision/preflop.py` | Bet 4x or check, given 2 hole cards | lookup — 169-class table | 30 |
| `tools/generate_preflop_table.py` | Builds that table offline | 2M trials + 6,000 boards/class | 20 |
| `tools/simulate.py` | Plays full hands, tracks a chip bankroll | flop sampled (32 runouts) | 22 |

`decision/` has no I/O and imports nothing from `tools/`. The engine is
testable entirely offline against fake hands.

### The decision chain

```python
from decision.evaluator import parse_cards
from decision.preflop import decide as preflop_decide
from decision.flop import decide as flop_decide
from decision.river import decide as river_decide

preflop_decide(parse_cards("As Kh"))            # -> PreflopDecision: bet 4x | check
flop_decide(parse_cards("9h 9d"), parse_cards("Ks Qh Jd"))   # -> bet 2x | check
river_decide(parse_cards("9h 9d"), board)       # -> bet 1x | fold
```

Each returns a frozen dataclass carrying the verdict *and* the reasoning — the
EV of each option, the margin, and the sampling resolution behind it.

---

## Design decisions worth knowing

These are the non-obvious calls. The full reasoning is in the module docstrings
and in [SESSION_NOTES.md](SESSION_NOTES.md).

- **Five outcome buckets, not three.** The Ante resolves differently depending
  on whether the dealer qualifies, so `win_qualified` / `win_unqualified` /
  `push` / `lose_qualified` / `lose_unqualified` are tracked separately. The
  Blind pays the same either way.
- **All EV is in ante units.** Ante = Blind = 1 unit; the Play bet is the
  multiplier. Chips are a presentation layer (`tools/simulate.py` derives
  `ante = max_bet / 4`, since the 4x pre-flop Play bet *is* the table maximum).
- **Betting is compared against *checking*, never against folding.** Folding
  forfeits Ante + Blind (−2 units) and is only a real option on the river. Pre-
  flop and on the flop, the alternative is checking, so that is the baseline.
- **The flop is exact, not Monte Carlo.** The spec suggested sampling; there is
  no timer on the practice site, so 8 seconds of enumeration buys zero variance.
- **The pre-flop table stores a win-conditional Blind scalar** (`blind_sum /
  wins`), which is exact for the EV the decision uses but only indicative inside
  `breakeven_or_none`.
- **`treys` scores are inverted** — lower is stronger (1 = royal, 7462 = worst).
  This trips people up and is called out in the code.

---

## Known limitations

1. **The pre-flop table understates checking.** Its `check_value` prices "check
   pre-flop, check the flop, play the river" and therefore omits the value of
   betting the flop when that is +EV. The omission is worth **0.055 ante
   units/hand** — measured by the simulator, not assumed — and biases `decide()`
   toward betting 4x. The simulation prices the true EV correctly; the table
   itself is uncorrected. Fixing it needs a per-class measurement of
   `E_flop[max(0, flop.ev_advantage)]`.
2. **`format_report` misreports ruined runs.** The simulator deliberately keeps
   playing past ruin so the worst hands aren't truncated, so a broke run's
   "final bankroll" is meaningless — it once printed "profitable trials 7 of 10"
   when 8 of 10 had gone broke. Trust `ruin_at` and the Rao-Blackwellised EV,
   not the bankroll line.
3. **Six pre-flop classes sit inside the baseline's noise** (`22`, `J6s`, `K2o`,
   `T8s`, `J5s`, `Q3s`). A denser tier-2 pass would resolve them; it was never
   run.
4. **The simulator samples the flop** (32 of 1,081 runouts) because an exact
   sweep costs ~10s per hand. Validated against exact on 20 flops: 19/20 verdict
   agreement, and the one disagreement was a coin-flip where flipping is free.
5. **`river.py` was never validated against published strategy charts.** It is
   exact enumeration and the EV pipeline was cross-checked independently, but
   the external cross-check is outstanding.
6. **No perception or action layer.** By decision — the project is scoped to the
   engine.

---

## Repo layout

```
decision/            the engine — pure logic, no I/O
  evaluator.py         hand ranking (treys wrapper)
  ev.py                payout model, EV, breakeven
  river.py             exact river decision
  flop.py              exact flop decision
  preflop.py           169-class lookup + table loader
tools/
  generate_preflop_table.py   offline table generator (parallel)
  preflop_table.json          the generated table
  simulate.py                 bankroll simulator
tests/               146 tests, ~2 min
SESSION_NOTES.md     the working log — decisions, costs, measurements
```

`SESSION_NOTES.md` is the project's memory: it records what was measured, what
was rejected and why, and what is still open. Read it alongside the code.
