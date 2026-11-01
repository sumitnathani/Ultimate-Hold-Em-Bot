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
  | `decision/ev.py` | 3e | `5aaf4ea` | 32 |
  | `decision/river.py` | 3b | `355b7d5` | 12 |
  | `decision/flop.py` | 3c | (this session) | 13 |
- Full suite: 63 tests, ~30s. Green.
- **Next concrete step:** `decision/preflop.py` + `tools/generate_preflop_table.py`
  (spec 3d) — the offline generator at N=2,000,000 trials per starting-hand
  class, ~1.6h one-time.

## Decisions locked this session (flop.py, spec 3c)

### 1. The flop enumerates exactly; it does not sample

Spec 3c specifies Monte Carlo at N=100,000, on the grounds that exact
enumeration is "~1M+ combos" and therefore avoidable. That premise was checked
and **the spec is right** — the exact count is

    C(47, 2) dealer hands x C(45, 2) turn+river = 1,081 x 990 = 1,070,190

Measured cost is ~8–10s per decision, versus ~1.6s for the specified N=100,000
sample. The project owner chose **exact** anyway: there is no timer on the
practice site, and zero variance is worth more than a ~6x speedup here. This
supersedes the sample size in locked decision 5 below (which still governs the
pre-flop generator).

Consequence worth knowing: the flop decision is now exact in the same sense the
river is, so **both streets are ground truth** for validating the pre-flop
table later.

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

### 3. Open question, not yet resolved: the flop's comparison baseline

Spec 10 locked decision 1 says the EV baseline is `ev_of_fold` = −2 units "on
all three streets". On the flop that is modelling, not reality: **folding is not
an available action** — spec 3c's alternative is *checking*, which keeps the
Ante and Blind alive into the turn and river. The true EV of checking is
therefore strictly above −2, so using −2 as the baseline makes betting look
better than it is and biases the screen toward betting 2x.

Built as specified (baseline −2, action `BET`/`CHECK`) and documented in the
module docstring, but flagging it: if a check-aware baseline is wanted, it is a
change to `flop.decide` plus its tests, not to the enumeration.

### 4. Follow-up proposal: `dealer_qualifies` and `breakeven_or_none` belong in `ev.py`

`flop.py` currently imports both from `decision/river.py`, where they landed
only because the river was built first. Both are street-agnostic (spec 9's
qualification rule and the measured-rates wrapper around
`ev.breakeven_win_rate`). Importing them keeps one implementation instead of a
copy that can drift, but `flop -> river` is an odd dependency direction.
Relocating them into `decision/ev.py` would be cleaner. Deliberately *not* done
this session so the change stayed a one-file step.

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

1. **EV baseline**: folding forfeits Ante + Blind = −2 units. See the open
   question in §3 above for the flop-specific caveat.
2. **Outcome buckets**: 5, not 3 — `win_qualified`, `win_unqualified`, `push`,
   `lose_qualified`, `lose_unqualified`, because the Ante resolves differently
   depending on dealer qualification.
3. **Blind handling**: `blind_multiplier` passed explicitly. `river.py` computes
   it exactly via `blind_multiplier_for_score()`. `flop.py` passes **0.0** —
   deferred by design, not forgotten: the Blind pays per the player's *final*
   hand class, which the flop does not resolve to a single value. 0.0 can only
   understate betting, so it errs toward checking.
4. **Threshold form**: `breakeven_win_rate(...)`, solved numerically by
   bisection against `ev_of_bet` so it can never drift from the EV it is the
   root of. Each caller passes its own measured `tie_rate` and conditional
   qualify rates.
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
bucket_payoffs(multiplier, blind_multiplier=0.0, table=PAYOUT_TABLE) -> dict
ev_of_bet(multiplier, outcomes, blind_multiplier=0.0, table=PAYOUT_TABLE) -> float
ev_of_fold(table=PAYOUT_TABLE) -> float
ev_advantage(...), should_bet(...)
outcomes_from_win_rate(p_win, *, tie_rate, qualify_on_win, qualify_on_lose)
breakeven_win_rate(multiplier, *, tie_rate, qualify_on_win, qualify_on_lose,
                   blind_multiplier=0.0, table=PAYOUT_TABLE) -> float

# decision/river.py  (exact, spec 3b)
dealer_qualifies(score) -> bool
enumerate_dealer_outcomes(hole, board) -> dict[str, int]   # C(45,2)=990
decide(hole, board, table=PAYOUT_TABLE) -> RiverDecision   # .action BET|FOLD
breakeven_or_none(outcomes, multiplier, blind_multiplier, table) -> float | None

# decision/flop.py  (exact, spec 3c)
FLOP_PLAY_MULTIPLIER = 2.0
ENUMERATION_SIZE = 1_070_190
enumerate_runout_outcomes(hole, board) -> dict[str, int]   # C(47,2)*C(45,2)
decide(hole, board, table=PAYOUT_TABLE) -> FlopDecision    # .action BET|CHECK
```

## Runtime notes

- The full suite takes ~30s, almost entirely `tests/test_flop.py`: every
  `decide()` costs ~8.5s. The three expensive cases are computed once in
  module-scoped fixtures — **do not convert them to per-test calls**, or the
  suite goes from 30s to several minutes.
- `river.decide` is milliseconds; `flop.decide` is ~8–10s; pre-flop will be a
  dictionary lookup (zero computation at runtime).

## Next session steps

1. `tools/generate_preflop_table.py` (spec 3d): for each of the 169
   starting-hand classes, Monte Carlo N=2,000,000 full runouts, recording the
   five-bucket outcome rates; write `tools/preflop_table.json`, checked into the
   repo. Seed it for reproducibility. This is the one place sampling is genuinely
   unavoidable — see the corrected count above.
2. `decision/preflop.py` (spec 3d): canonicalize two hole cards into one of the
   169 classes, look up the stored rates, decide bet 4x / check via
   `ev.breakeven_win_rate`. Zero runtime computation.
3. Validate `river.py` output against published UTH river strategy charts for a
   few known hands — still outstanding from the previous session.
4. Decide the open question in §3 (flop check-vs-fold baseline) and the
   follow-up in §4 (relocating the two shared helpers into `ev.py`).

Ask before: anything touching `perception/`, `action/` or `main.py`; any sample
size change; any change to the payout table or the 5-bucket model.
