# SESSION_NOTES — Ultimate Texas Hold'em Bot

Working notes for re-orienting a fresh session on the `decision/` module without
replaying chat history. Seeded from section 10 of the build spec on 2026-11-01
and maintained by Claude Code from here on.

**Read this *and* run `git log --oneline --stat -10` and `git status`. Notes
drift; the repo is the truth.**

Scope: `decision/` only. `perception/`, `action/` and `main.py` are a later
phase and must not be touched without asking first.

## Status as of 2026-11-01

- Branch: `main`. (Spec section 10 claimed work was happening on a
  `decision-engine` branch — that was wrong. No such branch exists; everything
  has been committed to `main` all along.)
- Built, tested, committed:
  | Module | Spec | Commit | Tests |
  | --- | --- | --- | --- |
  | `decision/evaluator.py` | 3a | `ded39b7` | 11 |
  | `decision/ev.py` | 3e | `5aaf4ea`, `deb0847` | 25 |
  | `decision/river.py` | 3b | `355b7d5`, `deb0847` | 20 |
  | `decision/flop.py` | 3c | `8091353`, `aa95a91` | 18 |
- Full suite: 74 tests, ~40s. Green.
- **Both built streets are exact**, so both are ground truth for validating the
  pre-flop table later.
- **Next concrete step:** `decision/preflop.py` + `tools/generate_preflop_table.py`
  (spec 3d) — the offline generator at N=2,000,000 trials per starting-hand
  class, ~1.6h one-time.

## Decisions locked this session (flop.py, spec 3c)

### 1. The flop enumerates exactly; it does not sample

Spec 3c specifies Monte Carlo at N=100,000, on the grounds that exact
enumeration is "~1M+ combos" and therefore avoidable. That premise was checked
and **the spec is right** — the exact count is

    C(47, 2) turn+river x C(45, 2) dealer hands = 1,081 x 990 = 1,070,190

Measured cost is ~8.3s per decision, versus ~1.6s for the specified N=100,000
sample. The project owner chose **exact** anyway: there is no timer on the
practice site, and zero variance is worth more than a ~6x speedup here. This
supersedes the sample size in locked decision 5 below (which still governs the
pre-flop generator).

### 2. A bias bug was found and fixed in the first implementation — do not reintroduce it

The first `flop.py` enumerated `combinations(deck, 4)` and split each with
`draw[:2]` / `draw[2:]`. Because `itertools.combinations` emits each subset in
the iterable's order and `remaining_deck` is ordered rank-then-suit, `draw[:2]`
was *always the two lowest-ranked cards* — the dealer systematically got the
small cards and the board the big ones. It also covered only 1/6 of the outcome
space, since a 4-card set splits 6 ways between dealer and runout and all 6 are
distinct, equally-likely situations.

The failure mode was nasty because the buggy version is *faster*: it ran in
~2.7s, which made exactness look nearly free and led to a wrong recommendation
that had to be retracted. Symptoms: a 55% push rate on a hand whose true push
rate is 14.5%.

The fix is to draw the dealer hand and the runout as the two separate draws they
actually are. `tests/test_flop.py::test_the_enumeration_agrees_with_independent_
monte_carlo` exists specifically to keep this caught — it compares the
enumeration against an independent seeded sampler at a 5-sigma tolerance (the
bug was ~40 sigma out on push rate). The module docstring documents the trap.

### 3. The flop's baseline is the EV of checking, not the −2 of folding

This was raised as an open question at the end of the last step and resolved:
built properly rather than carried as documented bias.

**Checking and folding are not the same alternative.** Spec 10 locked decision 1
says the baseline is `ev_of_fold` = −2 "on all three streets"; on the flop that
is a modelling shortcut, because folding is not an available action — spec 3c's
alternative is *checking*, which keeps the Ante and Blind alive into the turn
and river. Folding is still available on the river, so −2 is the **floor** of
checking's value, never its value. Comparing a 2x bet against −2 overstated
every margin by exactly that gap, one-directionally, in favour of betting.

`flop.decide` now computes

    ev_check = mean over all 1,081 runouts of river.optimal_ev(runout_outcomes, player_blind)

and bets 2x only when `ev_bet > ev_check`. The number is free: the enumeration
visits every runout anyway, and `river.optimal_ev` is exact for each. It is
computed in the *same pass* as the counts, deliberately — a separate pass could
drift from the outcomes it is supposed to price. Averaging per runout equals
averaging over all 1,070,190 pairs, since each runout owns exactly 990 of them.

`FlopDecision.ev_fold` is gone; it is `ev_check` now. Reading the two as
interchangeable would reintroduce the bias.

### 4. The flop's Blind is priced, as an exact effective multiplier

Previously `flop.py` passed `blind_multiplier=0.0` (spec 10 locked decision 3,
deferred "by design"). That deferral is now resolved too, and it mattered more
than expected: with the Blind left at 0.0 on the bet side **the flopped royal
would have flipped to CHECK**, because checking it is worth a guaranteed
+501.83 while an unpriced 2x bet is worth only +2.83.

The flop cannot *look up* the multiplier the way the river does — its final hand
class varies with the runout. But it can accumulate the real total: the
enumerator already knows the player's final hand for every outcome it visits, so
`blind_sum` accumulates `wins_in_runout x blind_multiplier_for_score(final hand)`
and

    effective_blind = blind_sum / total_wins

This is **exact, not an estimate**: bucket payoffs credit the Blind on the two
win buckets only, so `(win rate) x (blind_sum / wins) == blind_sum / N` by
construction. Measured effective multipliers: royal **500.0** (every runout is a
royal flush, so the average is exactly the lookup), the pair case **0.3101**
(diluted by pair/two-pair wins that pay nothing), `7c 2d` **0.0** (cannot make a
straight or better from two cards).

### 5. `dealer_qualifies` and `breakeven_or_none` moved into `ev.py`

Both were in `river.py` only because the river was built first, and `flop.py`
had to import them back across a module boundary. Both are street-agnostic
(spec 9's qualification rule; the measured-rates wrapper around
`breakeven_win_rate`). `ev.py` is their home now.

`breakeven_win_rate` also gained a keyword-only `baseline`, defaulting to
`ev_of_fold()` — which is right for the river. The flop passes `baseline=ev_check`,
because that is the alternative a flop bet has to beat. Without the parameter the
flop threshold could only ever have been anchored to the wrong alternative.
`river.optimal_ev()` is the shared name for "play this river optimally", so
`flop.py` prices checking without restating the definition.

## What the baseline change did to the hand-table verdicts

The three example verdicts are **unchanged** — royal **BET**, `9h9d` **BET**,
`7c2d` **CHECK**. The margins are not:

| case | EV(bet) | EV(check) | margin | old margin vs −2 |
| --- | --- | --- | --- | --- |
| `Js Ts` on `As Ks Qs` | +502.825 | +501.825 | **+1.000** | +504.8 |
| `9h 9d` on `Ks Qh Jd` | +0.254 | +0.043 | **+0.211** | +2.254 |
| `7c 2d` on `Ks Qh Jd` | −2.454 | −1.651 | **−0.803** | −0.454 |

The royal's margin is analytically exactly +1.000: the hand never loses, so the
extra 1x Play bet is a pure even-money wager that is always won. The pair's edge
falls from +2.25 to +0.21 — still a bet, but the real decision is far closer than
the old baseline suggested, and `7c2d`'s check is now a much larger margin
(−0.803 vs −0.454) because checking is worth −1.651 rather than −2.

## Corrections to the spec's stated numbers

- Spec 3c's "~1M+ combos" for the flop: **correct** (1,070,190). An earlier
  claim this session that it was 178,365 / off by ~6x was an artifact of the bug
  in §2 and has been retracted.
- Spec 3d's pre-flop exact count is ~**100 million** (`C(50,7) = 99,884,400`),
  not the "~2 billion" quoted in the last session's handoff. Conclusion is
  unchanged — at ~16µs per draw that is ~0.4h *per distinct holding* against
  1,326 holdings, so Monte Carlo at N=2,000,000 stays — but the figure is off by
  ~20x and worth not repeating.
- Carried forward from the `ev.py` session, still true: the "~19% breakeven
  matches the published '21 dealer outs' heuristic" claim does **not** hold
  precisely (it lands nearer 24–25 outs); and the non-qualify Ante-push rule
  shifts the threshold by ~0.04pp, not by the tens of points the spec implies.
  The real driver is that folding costs 2 units. See `ev.py`'s module docstring.

## Locked design decisions carried forward (do not re-litigate)

1. **EV baseline**: folding forfeits Ante + Blind = −2 units. That is the
   baseline for the **river**, where folding really is the alternative. The
   **flop** passes the EV of *checking* instead — see §3. The pre-flop table
   (3d) needs the same question asked: its alternative is also checking.
2. **Outcome buckets**: 5, not 3 — `win_qualified`, `win_unqualified`, `push`,
   `lose_qualified`, `lose_unqualified`, because the Ante resolves differently
   depending on dealer qualification.
3. **Blind handling**: `blind_multiplier` passed explicitly. `river.py` computes
   it by lookup (`blind_multiplier_for_score()`), because its final hand is
   known. `flop.py` computes it as an exact win-weighted expectation (§4).
   Neither is deferred any more. The pre-flop stage will need a third form
   again, since its final hand is also unknown at decision time.
4. **Threshold form**: `breakeven_win_rate(...)`, solved numerically by
   bisection against `ev_of_bet` so it can never drift from the EV it is the
   root of. Each caller passes its own measured `tie_rate`, conditional qualify
   rates, and `baseline`.
5. **Monte Carlo sample sizes**: the pre-flop generator uses N=2,000,000 trials
   per starting-hand class. (The flop's N=100,000 is superseded by §1 above.)

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
   unavoidable — see the corrected count above. **Decide first** whether the
   table should also store the pre-flop Blind expectation (locked decision 3
   will need it) — that is a judgment call, not a detail.
2. `decision/preflop.py` (spec 3d): canonicalize two hole cards into one of the
   169 classes, look up the stored rates, decide bet 4x / check.
3. Validate `river.py` output against published UTH river strategy charts for a
   few known hands — still outstanding from the previous session and not yet
   done; the flop is now also exact enough to cross-check the same way.

Ask before: anything touching `perception/`, `action/` or `main.py`; any sample
size change; any change to the payout table or the 5-bucket model.
