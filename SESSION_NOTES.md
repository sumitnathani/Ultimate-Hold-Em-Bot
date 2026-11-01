# SESSION_NOTES — Ultimate Texas Hold'em Bot

Working notes for re-orienting a fresh session on `decision/` without replaying
chat history. Seeded from section 10 of the build spec on 2026-11-01 and
maintained by Claude Code from here on.

**Read this *and* run `git log --oneline --stat -10` and `git status`. Notes
drift; the repo is the truth.**

Scope: `decision/` and `tools/` only. `perception/`, `action/` and `main.py` are
a later phase and must not be touched without asking first.

## Status as of 2026-11-01

- Branch `main`; everything is committed there. (Spec section 10's claim that
  work was happening on a `decision-engine` branch was wrong — no such branch
  ever existed.)
- Built, tested, committed:

  | Module | Spec | Commit | Tests |
  | --- | --- | --- | --- |
  | `decision/evaluator.py` | 3a | `ded39b7` | 11 |
  | `decision/ev.py` | 3e | `5aaf4ea`, `deb0847` | 25 |
  | `decision/river.py` | 3b | `355b7d5`, `deb0847` | 20 |
  | `decision/flop.py` | 3c | `8091353`, `aa95a91` | 18 |

- Full suite: **74 tests, ~40s, green.**
- **Both built streets are exact** (exhaustive enumeration), so both are ground
  truth for validating the pre-flop table later.
- **Next concrete step:** `tools/generate_preflop_table.py` + `decision/preflop.py`
  (spec 3d). Two judgment calls to settle first — see "Open" below.

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

## Open — settle before writing the generator

- **Does the table also store the pre-flop Blind expectation?** Locked decision 3
  says pre-flop needs a third form of Blind handling; whether that lives in the
  table or is computed at lookup time is a judgment call, not a detail.
- **How to measure the residual flop-bias (F term)** — see below; this follow-up
  must not get dropped.

## Pre-flop baseline (spec 3d) — decided, not yet built

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

Measured cost: **7.55 ms per board**, board-level SD ≈ 1.5–1.6, tails
well-behaved (top-3 boards contribute 0.01–0.015 of the mean, max +12 — the
500:1 royal does not blow the variance up). 6,000 boards/class → 45s/class →
**2.13h for all 169 classes, SE 0.02.**

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
dealer's exact distribution and so wants distinct *boards*, where 7.55ms is the
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

- The full suite takes ~40s, almost entirely `tests/test_flop.py`: every
  `decide()` costs ~8.3s, and `test_the_check_baseline_and_the_blind_come_back_
  out_of_the_river` costs another ~8s re-deriving the same numbers through
  `river.decide`. All of it is computed once in module-scoped fixtures — **do
  not convert them to per-test calls**, or the suite goes from 40s to minutes.
- `river.decide` is milliseconds; `flop.decide` is ~8.3s; pre-flop will be a
  dictionary lookup (zero computation at runtime).

## Next session steps

1. `tools/generate_preflop_table.py` (spec 3d): for each of the 169
   starting-hand classes, Monte Carlo N=2,000,000 full runouts, recording the
   five-bucket outcome rates; write `tools/preflop_table.json`, checked into the
   repo. Seed it for reproducibility. This is the one place sampling is genuinely
   unavoidable — see the corrected count above. Plus the board-averaged
   `check_value` loop (6,000 boards/class) and whatever "Open" above decides
   about the Blind.
2. `decision/preflop.py` (spec 3d): canonicalize two hole cards into one of the
   169 classes, look up the stored rates, decide bet 4x / check.
3. Validate `river.py` output against published UTH river strategy charts for a
   few known hands — still outstanding from the previous session and not yet
   done; the flop is now also exact enough to cross-check the same way.
4. Measure the residual F term (see "Residual, and how to bound it").

Ask before: anything touching `perception/`, `action/` or `main.py`; any sample
size change; any change to the payout table or the 5-bucket model.