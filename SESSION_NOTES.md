# SESSION_NOTES — Ultimate Texas Hold'em Bot

> **PROJECT CONCLUDED 2026-11-06.** The decision engine is complete, tested and
> simulated; see [README.md](README.md) for the summary and "Simulation
> results" below for the numbers. `perception/`, `action/` and `main.py` were
> deliberately never built and are **not** planned. Nothing here is in flight —
> the notes are kept as the record of what was measured and why.

Working notes for re-orienting a fresh session on `decision/` without replaying
chat history. Seeded from section 10 of the build spec on 2026-11-01 and
maintained by Claude Code from here on.

**Read this *and* run `git log --oneline --stat -10` and `git status`. Notes
drift; the repo is the truth.**

Scope: `decision/` and `tools/` only. The perception and action layers are out
of scope permanently.

## Status as of 2026-11-06

- Branch `main`; everything is committed there. (Spec section 10's claim that
  work was happening on a `decision-engine` branch was wrong — no such branch
  ever existed.)
- **The decision engine is complete.** All five modules decide, and `tools/
  simulate.py` plays full hands through them. Built, tested, committed:

  | Module | Spec | Commit | Tests |
  | --- | --- | --- | --- |
  | `decision/evaluator.py` | 3a | `ded39b7` | 11 |
  | `decision/ev.py` | 3e | `5aaf4ea`, `deb0847` | 25 |
  | `decision/river.py` | 3b | `355b7d5`, `deb0847` | 20 |
  | `decision/flop.py` | 3c | `8091353`, `aa95a91` | 18 |
  | `decision/preflop.py` | 3d | `9b77c21`, `390da5e` | 30 (canonicaliser **and** `decide()`) |
  | `tools/simulate.py` | — | `4436f7e` | 22 |

- Full suite: **146 tests, ~2 min, green.**
- **Both built streets are exact** (exhaustive enumeration), so both are ground
  truth for validating the pre-flop table later.
- **The 169-class table is built and committed** (`tools/preflop_table.json`,
  `ad82766`, generated 2026-11-01): 2,000,000 full runouts + 6,000 boards per
  class, seed `20261101`. Every row holds the five-bucket rates, `B_eff`, and
  `check_value` with its SE. Spot-checked at full size against two recomputed
  rows — one from each run — and the values were identical.
- `tools/generate_preflop_table.py` is **built, tested and committed**
  (`24ced31`, parallelized in `c65eff3`): one class per worker, `--jobs`
  (default one per CPU), **14x measured** on the 24-core dev machine. Per-class
  seeds make the parallel table equal a serial one row for row; the tests
  assert it. Full serial-equivalent cost is ~4h; the remaining 64 classes took
  6.6 min.
- `preflop.py` is **finished** (`390da5e`): `decide()` is a lazy, cached
  dictionary lookup plus the `ev_bet > ev_check` comparison. Of the 169 classes
  it bets 4x on 83 and checks on 86; only 6 sit inside the baseline's noise
  (`J6s`, `22`, `K2o`, `T8s`, `J5s`, `Q3s`), which is the tier-2 set.
- `tools/simulate.py` is **built** (`4436f7e`): plays complete hands through the
  engine and reports both a realised P/L and a Rao-Blackwellised EV. See "The
  bankroll simulator" below.
- **Next concrete step:** the tier-2 dense baseline pass, then the F-term probe.
  Neither is blocking — the engine decides on every street today.

## Where the reasoning lives

The "why we chose this over that" for anything already built is permanently in
the code. Read it there; it is not duplicated here.

| Question | Answer lives in |
| --- | --- |
| Why the flop enumerates all 1,070,190 outcomes instead of sampling per spec 3c | `flop.py` docstring, "HOW BIG THE ENUMERATION IS" |
| Why splitting 4-card subsets is wrong — and why the bug is a *trap* (it is faster) | `flop.py` docstring, "THE TRAP"; kept caught by `tests/test_flop.py::test_the_enumeration_agrees_with_independent_monte_carlo` |
| Why the flop's baseline is the EV of *checking*, not the −2 of folding | `flop.py` docstring, "THE VERDICT IS BET 2x OR CHECK"; `test_checking_is_never_worse_than_folding`, `test_the_old_flat_baseline_overstated_the_margin` |
| How the flop prices the Blind with no known final hand (exact, not estimated) | `flop.py` docstring, "THE BLIND IS PRICED HERE"; `test_the_blind_is_priced_as_an_expected_multiplier`, `test_the_effective_blind_reproduces_the_total_blind_profit` |
| Why 5 outcome buckets, not 3; the full spec-9 payout model; why breakeven is ≈19% and not 50% | `ev.py` module docstring |
| Why `breakeven_win_rate` bisects instead of using a closed form | `ev.py::breakeven_win_rate` docstring |
| Why `dealer_qualifies` / `breakeven_or_none` live in `ev.py` rather than `river.py` | their docstrings in `ev.py` |
| Why the flop's check baseline and Blind are fused into one pass | `flop.py::FlopSweep` docstring; cross-checked by `test_the_check_baseline_and_the_blind_come_back_out_of_the_river` |

## The bankroll simulator — `tools/simulate.py` (2026-11-06)

The first code that *spends* the engine's answers. Offline, like the generator;
nothing in `decision/` imports it. Run it as `python -m tools.simulate` (the
repo root is only on `sys.path` under `-m` or pytest's `pythonpath = .`).

**Chips from units.** The engine works in ante units; the simulator takes one
more number, the table's maximum bet — the largest single wager the rules
allow, which is the 4x pre-flop Play bet — and derives `ante = max_bet / 4`. So
a 5,000-chip max is a **1,250-chip ante**, a 2,500-chip fold, a 7,500-chip worst
case, and a 50,000-chip bankroll is **40 antes**. Every figure is reported in
units as well, because units are what the strategy earns and they do not move
when the ante does.

**Two estimators, deliberately both reported.** Realised P/L is what a player
actually wins or loses, but its sd is ~4.2 units/hand, so at any sample size a
run can afford, its SE is *larger than the edge* — it cannot answer "are we up
or down" on strategy. The Rao-Blackwellised estimator accumulates the engine's
own conditional EV per hand instead: sd ~1.4, an order of magnitude tighter for
the same hands. Report the R-B figure for the edge; report realised P/L for
what the bankroll did.

**The one approximation: the flop.** Exact `flop.decide` is ~10s, which prices a
10,000-hand run at 28 hours, so the simulator sweeps `--flop-runouts` sampled
runouts (default 32 of 1,081) and enumerates all 990 dealer hands exactly inside
each. Validated against exact on 20 flops: 19/20 verdict agreement, margin delta
mean +0.0145 sd 0.1163, the single disagreement being a true coin-flip where a
flip costs nothing.

**The margin is well behaved; `ev_check` is not.** A live royal makes `ev_check`
heavy-tailed — `Ah Kh` on `Qh 8s 3d` can run out a royal worth ~500 units on one
runout in 1,081, so at 64 runouts the sample usually misses it and its sd across
seeds is **3.3**. The royal moves `ev_bet` and `ev_check` *together* (same
runouts), so the **margin** stays clean: sd 0.064 at 64 runouts, max error 0.127
over 10 seeds. This is the same tail the notes flagged as `max check_value_se
0.22` for suited broadways. Anything binding the sampled flop to the exact one
must assert on the margin, not on `ev_check` — see
`tests/test_simulate.py::test_the_sampled_flop_agrees_with_the_exact_one`.

**A royal pays 625,000 chips** at a 1,250-chip ante (500:1 on the Blind), which
dwarfs a 50,000-chip bankroll. Real UTH, not a bug — but it means bankroll
outcomes are dominated by a rare tail, and that "ruined" says little about the
strategy. The R-B EV is bankroll-independent by construction.

## Simulation results (2026-11-06)

The headline question was "50k chips, 5k max bet — do we come out up or down,
and by how much". Answer: **down, by 2.70% ± 0.76% of an ante per hand** — which
is the published optimal figure for this game, so the engine plays essentially
as well as the game can be played and the loss is the house edge, not a bug.

| Run | Hands | Bankroll | R-B EV/hand | Realised/hand | Ruin |
| --- | --- | --- | --- | --- | --- |
| headline | 10,000 | 50,000 (40 antes) | −0.0440 ± 0.0136 | −0.1449 ± 0.0422 | hand 81 |
| deep | 5,000 | 1,000,000 (800 antes) | −0.0405 ± 0.0193 | −0.1627 ± 0.0596 | hand 4,990 |
| pooled | 20,000 | 10 × 50,000 (40 antes) | −0.0132 ± 0.0104 | +0.0036 ± 0.0395 | 8 of 10 |

All use max bet 5,000 (ante 1,250), seed `20261106`, 32 flop runouts.

**The edge is a loss of −2.70% ± 0.76% of an ante per hand** — the
inverse-variance weighted mean of the three R-B estimates over 35,000 hands
(χ² = 3.81 on 2 df, so the three agree with their stated SEs). Read any single
run and you would be misled: the headline alone says −4.4% and the pooled alone
says −1.3%, but neither is the answer.

**That is the published UTH optimum.** The figure for perfect play is −2.185% of
the ante; the engine is **0.68σ away** — statistically indistinguishable from
optimal. The loss is inherent to the game, not to the engine. This supersedes
the earlier single-run reading of "−4.4%, in the right neighbourhood but not
matching".

Caveat: all three runs share the same base seed, so their first 2,000 hands are
the *same* hands (~6% overlap). Not enough to change the conclusion, but they
are not fully independent, and a clean replication would use disjoint seeds.

**The F term is now measured, not asserted.** `analytic_ev_per_hand()` (the
table's own claim) is −0.0821; the simulation, which actually *plays* the flop,
comes in at −0.0270. The gap, **+0.0551 units**, is exactly the weighted average
of `F̄ = E_flop[max(0, flop.ev_advantage)]` over the classes the table checks —
the value of the flop bet that `check_value` omits. So the omission is worth
**~0.055 units/hand**, about 5.5% of an ante, and it is the entire distance
between the table's −0.0821 and reality. This confirms the mechanism predicted
in "Pre-flop baseline" above: the table understates checking and bets 4x too
often.

**Variance dominates everything.** Realised sd is ~**4.2 units/hand** against an
edge of 0.027 — a signal-to-noise ratio of about **1:156**. A single session's
realised P/L is therefore almost pure noise: the headline and deep runs both
realised −0.14 to −0.16, 2σ+ *below* the true edge, and the pooled 20,000 hands
realised **+0.004** — a *profit* — on a game that loses. This is why the
simulator reports the Rao-Blackwellised figure as *the* edge and the realised
figure only as what the bankroll did.

Note the realised sd is not itself stable: 4.21 over 10,000 hands vs 5.59 over
20,000. That is not a contradiction — the royal flush pays 505 units on one hand
in ~31,000, so the sample sd is dominated by whether a royal happened to land.
Treat ~4.2 as indicative only.

**Bankroll sizing — the rule of thumb.** With the corrected μ = 0.027 and
σ = 4.2, the infinite-horizon diffusion approximation `RoR ≈ exp(−2·|μ|·B/σ²)`
is **`exp(−B/327)`** for `B` in antes. For finite sessions use the full
expression (`Φ((−B−μN)/(σ√N)) + exp(−2μB/σ²)·Φ((μN−B)/(σ√N))`):

| Stack | Example | 5,000 hands | 10,000 hands | 20,000 hands |
| --- | --- | --- | --- | --- |
| 40 antes | 50,000 chips | 94% | 97% | 99% |
| 200 antes | 250,000 chips | 65% | 81% | 91% |
| 400 antes | 500,000 chips | 31% | 57% | 79% |
| 800 antes | 1,000,000 chips | 2% | 17% | 47% |
| 1,200 antes | 1,500,000 chips | ~0% | 2% | 20% |

The expected loss over 10,000 hands is **270 antes**, so no stack under ~270
antes can even cover its own expected loss — which is why the 40-ante table
above is so brutal.

Measured against it: at 40 antes, **8 of the 10 pooled trials went broke**
(model: 94–99% over 2,000 hands, so 8–10 was expected), and the headline died at
hand 81. The deep run went broke at 800 antes over 5,000 hands, which the model
puts at ~2% — a genuinely unlucky draw, and a reminder that one trial settles
nothing.

**Practical upshot:** the chip figures are cosmetic; only the stack-to-ante
ratio matters, and it needs to be in the hundreds. **50k with a 5k max bet is
unplayable at 40 antes** — not because the strategy is bad but because the bet
is too large for the stack.

### Reproducing

```bash
python -m tools.simulate --hands 10000 --trials 1  --bankroll 50000   --max-bet 5000 --seed 20261106
python -m tools.simulate --hands 5000  --trials 1  --bankroll 1000000 --max-bet 5000 --seed 20261106
python -m tools.simulate --hands 2000  --trials 10 --bankroll 50000   --max-bet 5000 --seed 20261106
```

`--json PATH` also dumps per-trial metrics. Note the repo root is only on
`sys.path` under `-m` (or pytest's `pythonpath = .`), so `python tools/simulate.py`
fails with `ModuleNotFoundError: No module named 'decision'`.

**Known wart, not yet fixed — and it matters.** `format_report`'s bankroll
section reports the final bankroll even for a ruined run, and the run
deliberately continues past ruin, so a broke trial keeps "playing" and the
number is meaningless. In the headline run it printed a final bankroll of
−1,761,875; in the pooled run it reported **"profitable trials 7 of 10"** when
**8 of 10 had actually gone broke**. Any bankroll headline from a ruined run is
noise. The meaningful figures are `ruin_at` and the R-B edge; the fix is to
floor the reported bankroll at zero or report the bankroll *at* ruin. **Do not
quote final-bankroll or "profitable trials" numbers until this is fixed.**

## Locked decisions (do not re-litigate)

1. **EV baseline.** Folding forfeits Ante + Blind = **−2 units**. That is the
   right baseline for the **river**, where folding really is the alternative.
   The **flop** passes the EV of *checking* instead (`flop.py`). Pre-flop (3d)
   is the same shape of question: its alternative is also checking, not folding.
2. **Outcome buckets.** 5, not 3 — `win_qualified`, `win_unqualified`, `push`,
   `lose_qualified`, `lose_unqualified`, because the Ante resolves differently
   depending on dealer qualification.
3. **Blind handling.** `blind_multiplier` is passed explicitly. `river.py`
   computes it by lookup (final hand known); `flop.py` as an exact win-weighted
   expectation. Neither is deferred any more. Pre-flop will need a third form,
   since its final hand is unknown at decision time — see "Open" below.
4. **Threshold form.** `breakeven_win_rate(...)`, solved numerically by bisection
   against `ev_of_bet` so it can never drift from the EV it is the root of. Each
   caller passes its own measured `tie_rate`, conditional qualify rates, and
   `baseline`.
5. **Flop is exact, not sampled.** Supersedes spec 3c's N=100,000 Monte Carlo:
   no timer on the practice site, so zero variance is worth the ~8.3s decision.
   The pre-flop generator keeps spec 3d's N=2,000,000 trials per class.
6. **Reference verdicts** (all exact, all asserted in tests): flopped royal
   `Js Ts` on `As Ks Qs` → BET; `9h 9d` on `Ks Qh Jd` → BET; `7c 2d` on the same
   board → CHECK.

## Pre-flop generator and bias probe — settled 2026-11-01

- **The table stores the Blind**, as a win-conditional scalar
  `B_eff = blind_sum / wins` computed in the same 2M loop, exactly the
  construction `flop.py` uses. It *cannot* be computed at runtime: at decision
  time there is no board, so there is no final hand class to look up. SE ≈ 0.002
  at 2M samples (dominated by the 500:1 royal term). Carry this caveat into
  `preflop.py`'s docstring: `B_eff` is win-conditional, so it is exact for the EV
  the decision uses but only approximate inside `breakeven_or_none`, which varies
  `p_win` while holding it fixed. Rejected: also storing the full conditional
  final-hand distribution — buys nothing for the decision.
- **Baseline sampling is two-tier and adaptive.** 6,000 boards for all 169
  classes (SE 0.02, 2.50h measured), then a denser pass (~60,000 boards,
  SE 0.006, ~9 min/class) for any class whose |margin| < 3×SE. 6,000 alone
  cannot resolve a verdict whose margin is ~0.01 — the noise is larger than the
  signal.
- **Measured SEs are class-dependent, so tier 2 must use each row's stored
  `check_value_se`, not a flat 0.02.** Median 0.024, but 45 classes exceed
  0.03 and the max is 0.22 (suited broadways: the royal/straight-flush tail
  enters through the river's optimal decision). At 3×SE the widest class has a
  ±0.67 band, so "which classes go to tier 2" needs a look before the dense
  pass is launched — the band, not a hand-picked list, decides.
- **The F term is measured, not asserted**, by `tools/measure_flop_bias.py`,
  separate from the generator (different output, different lifetime):

      F̄(class) = E_flop[ max(0, flop.ev_advantage) ]      flops ~ uniform C(50,3)

  each flop priced exactly by `flop.decide` (8.3s, so no double-sampling error).
  Order: a 30-flop warm-up probe on 3 classes (~12 min) to reproduce this file's
  F numbers before spending hours, then the ~10 classes with the smallest
  |margin| at 400–600 flops each (~4.6h+), plus the three reference hands as
  controls. SE ≈ 0.011 at n=200, which is why the thin classes get more.
- **Both corrections are one-directional** (`margin_corrected = margin − F̄`, and
  F̄ ≥ 0), so only BET→CHECK flips are possible.

## Still open

- River validation against published charts (next step 4).

## Pre-flop baseline (spec 3d) — decided and measured

The pre-flop decision is bet 4x or check, so its baseline is the value of
checking — the same *shape* of question the flop answered, but not the same
answer: checking pre-flop buys **two** further decisions (flop 2x/check, then
river 1x/fold), where checking the flop buys one.

**True backward induction is infeasible, and not marginally so.** The flop node
costs ~8.3s and depends only on `(hole, flop)`, so the honest count is the
~17k–69k *distinct* flops per class — not 2M samples, which overcounts by ~100x.
That is still ~160h per class, ~3 years for all 169. Sampling a subset of flops
instead just trades a bias for noise at ~11.5h per class even at n=5,000.

**Decided: average the optimal river decision over sampled boards.**

    check_value = E_boards[ max( ev_of_bet(1x, board_outcomes, board_blind), -2 ) ]

"Check pre-flop, check flop, then play the river optimally." The implementation
is `river.decide` per board — the same call `flop.py` already makes per runout,
so there is no new logic, and the Blind needs no effective-multiplier trick here
because the board is known, so it is a plain lookup.

Measured cost: **8.9 ms per board** (an earlier session measured 7.55ms; this
one's figure is the one the generator's ETA is built on), board-level SD ≈ 1.5,
tails well-behaved (top-3 boards contribute 0.01–0.015 of the mean, max +12 — the
500:1 royal does not blow the variance up). 6,000 boards/class → 53s/class →
**2.50h for all 169 classes, SE 0.02** (confirmed: 0.068 at 500 boards).

### Rejected: full-board showdown equity

`ev_of_bet(1x, preflop_outcomes, blind)`, taken free from the same 2M-sample
loop. Rejected because it prices *no* remaining decision, so it omits two
options rather than the one the first proposal acknowledged:

| option | royal | pair `9h9d` | weak `7c2d` |
| --- | --- | --- | --- |
| **F** the flop's 2x bet | 1.000 | 0.211 | 0.000 |
| **R** the river's fold option | 0.000 | 0.000 | 0.230 |

and **`F = max(0, (w−l) − R)`** holds exactly (verified to 6dp on all three).
So F is ≈0 for a coin-flip hand while R is not: the bias is ≈0 where the hand is
clear and ≈R where the decision is close — aimed at the wrong end. Both terms
are ≥0, so the bias is one-directional **toward betting 4x**, the same class of
error as the flop's old −2 baseline, and 0.230 is the same size as the pair's
0.211 decision margin. R is the term that actually matters, and the
board-averaged baseline removes it exactly.

### Residual, and how to bound it

The board-averaged baseline still omits F (one-directional toward betting 4x,
≈0 for marginal hands). Do not assert it is small — **measure** it: ~10 classes
× 200 flops through today's exact `flop.decide` is ~4.6h offline and yields a
per-class number to check against that class's margin.

### Consequence for the generator's shape: two loops, additive cost

They cannot share samples. The rates want millions of *samples* (a dealer hand
is ~14µs to sample, and board-level variance dominates — Rao-Blackwellizing the
dealer is ~100x worse per unit cost), while the river decision needs the
dealer's exact distribution and so wants distinct *boards*, where 8.9ms is the
floor. Each of the 2M samples carries only one dealer hand, so none of them can
be reused for the baseline.

Per class the table therefore stores: the five-bucket full-board rates **and**
the effective Blind multiplier (both from the 2M loop), plus `check_value` (from
the 6,000-board loop).

## Corrections to the spec's stated numbers

- Spec 3d's pre-flop exact count is ~**100 million** (`C(50,7) = 99,884,400`),
  not the "~2 billion" quoted in an earlier handoff. Conclusion unchanged — at
  ~16µs per draw that is ~0.4h *per distinct holding* against 1,326 holdings, so
  Monte Carlo at N=2,000,000 stays — but the figure was off by ~20x.
- Spec 3c's "~1M+ combos" for the flop: **correct** (1,070,190). See `flop.py`.
- The "~19% breakeven matches the published '21 dealer outs' heuristic" claim
  does **not** hold precisely (it lands nearer 24–25 outs); and the non-qualify
  Ante-push rule shifts the threshold by ~0.04pp, not by the tens of points the
  spec implies. Both are already corrected in `ev.py`'s docstring and measured
  by `test_nonqualify_ante_push_barely_moves_the_breakeven`.

## Key function signatures (compose with these, don't work around them)

```python
# decision/evaluator.py
best_hand_rank(hole, board) -> int      # LOWER = stronger; 5-7 cards
hand_class(score) -> HandClass          # 0=royal flush ... 9=high card
remaining_deck(*known) -> list[int]
parse_cards("As Ks") -> list[int]

# decision/ev.py
class Outcomes                          # 5 buckets; .from_counts(**counts)
class PayoutTable, PAYOUT_TABLE         # spec-9 payout structure, all knobs
bucket_payoffs(multiplier, blind_multiplier=0.0, table=PAYOUT_TABLE) -> dict
ev_of_bet(multiplier, outcomes, blind_multiplier=0.0, table=PAYOUT_TABLE) -> float
ev_of_fold(table=PAYOUT_TABLE) -> float
ev_advantage(...), should_bet(...)
outcomes_from_win_rate(p_win, *, tie_rate, qualify_on_win, qualify_on_lose)
breakeven_win_rate(multiplier, *, tie_rate, qualify_on_win, qualify_on_lose,
                   blind_multiplier=0.0, baseline=None, table=PAYOUT_TABLE) -> float
dealer_qualifies(score) -> bool
breakeven_or_none(outcomes, multiplier, blind_multiplier, table=PAYOUT_TABLE,
                  *, baseline=None) -> float | None

# decision/river.py  (exact, spec 3b)
RIVER_PLAY_MULTIPLIER = 1.0
enumerate_dealer_outcomes(hole, board) -> dict[str, int]   # C(45,2)=990
optimal_ev(outcomes, blind_multiplier=0.0, table=PAYOUT_TABLE) -> float
decide(hole, board, table=PAYOUT_TABLE) -> RiverDecision   # .action BET|FOLD

# decision/flop.py  (exact, spec 3c)
FLOP_PLAY_MULTIPLIER = 2.0
RUNOUT_COUNT = 1_081                    # C(47,2)
ENUMERATION_SIZE = 1_070_190
class FlopSweep                         # counts, runouts, blind_sum, check_sum
                                        # .outcomes .wins .effective_blind_multiplier .ev_check
enumerate_flop_outcomes(hole, board, table=PAYOUT_TABLE) -> FlopSweep
decide(hole, board, table=PAYOUT_TABLE) -> FlopDecision    # .action BET|CHECK
                                        # .ev_bet .ev_check .ev_advantage .blind_multiplier
```

## Runtime notes

- Full suite: **146 tests, ~2 min**, almost entirely `tests/test_flop.py`: every
  `decide()` costs ~8.3s, and `test_the_check_baseline_and_the_blind_come_back_
  out_of_the_river` costs another ~8s re-deriving the same numbers through
  `river.decide`. All of it is computed once in module-scoped fixtures — **do
  not convert them to per-test calls**, or the suite goes from ~2 min to much
  longer. `tests/test_simulate.py` follows the same rule for its three exact
  flops (~30s of the total).
- `river.decide` is milliseconds; `flop.decide` is ~8.3s; pre-flop is a
  dictionary lookup (zero computation at runtime).
- The table generator is parallel by default (`--jobs`, one worker per CPU).
  Measured on this machine: 81 s/class serial, ~140 s/class under 24-way load,
  **14x effective**; the remaining 64 classes took 6.6 min. A single-class run
  (`--classes X`) stays in-process and is not worth parallelizing.
- Tests call the generator through a `run()` helper that appends `--jobs 1`;
  the parallel path is covered by one subprocess test that compares a
  three-class parallel table with the serial one, row for row.

## Next session steps

**The project is concluded — none of these are planned.** They are recorded so
that a future session picking this up knows where the loose ends are, in rough
priority order.

1. ~~`tools/generate_preflop_table.py` + the full table~~ **Done** — committed
   in `24ced31`/`c65eff3`/`ad82766`; see Status above.
2. ~~`decision/preflop.py::decide()`~~ **Done** — committed in `390da5e`.
3. ~~A bankroll simulator over the finished engine~~ **Done** — committed in
   `4436f7e`; results in "Simulation results" above.
4. Tier-2 dense baseline pass over the boundary classes — the measured SEs vary
   by class (see "Pre-flop generator and bias probe"), so pick the set from the
   stored `check_value_se`. `decide()` now names the current six: `J6s`, `22`,
   `K2o`, `T8s`, `J5s`, `Q3s`.
5. Validate `river.py` output against published UTH river strategy charts for a
   few known hands — still outstanding from the previous session and not yet
   done; the flop is now also exact enough to cross-check the same way.
6. `tools/measure_flop_bias.py`: warm-up probe, then the boundary classes —
   see "Pre-flop generator and bias probe" above. **Lower priority now:** the
   simulation has already measured the aggregate `F̄` (0.055 units/hand, see
   "Simulation results"), so this is only needed for the per-class numbers that
   would let the *table* be corrected rather than just the EV account for it.
7. `perception/`, `action/`, `main.py` — **not built, not planned.** The project
   ends at the decision boundary; the README says so.
8. The `format_report` bankroll wart (see "Known wart" above) — a ~10-line fix,
   left undone at conclusion.

If this is ever revived, ask before: any sample size change, or any change to
the payout table or the 5-bucket model. Those are the two things every number
in this file is downstream of.