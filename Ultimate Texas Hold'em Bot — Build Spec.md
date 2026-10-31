# Ultimate Texas Hold'em Bot — Build Spec

By Coolguy, design session with Claude · Teach Sumit 101

## 1. What this bot does

Fully autonomous: reads the practice site's table state (hole cards, board, pot, available actions), decides the mathematically correct action (check/bet/fold, and bet size where relevant), and executes it — no manual clicking.

## 2. Three-layer architecture

```
[ Perception ]  -->  [ Decision Engine ]  -->  [ Action ]
   reads site         computes correct move      clicks/types
```

These are independent modules with a clean interface between them. This matters: you can build and test the Decision Engine entirely offline, with fake hands, before the Perception layer even exists. Don't build them in sequence by necessity — build Decision Engine first because it's pure logic and testable in isolation.

## 3. Decision Engine (the core — build this first)

### 3a. Hand evaluator (foundation for everything else)

- Use the `treys` Python library (or `deuces`) for 5-card hand ranking. Do not hand-roll this.
- For 7-card hands (2 hole + 5 board), brute-force all C(7,5)=21 five-card subsets, keep the best-scoring one via `treys.Evaluator.evaluate()`.
- Wrap this in one function: `best_hand_rank(hole: list[Card], board: list[Card]) -> int`. Lower treys score = stronger hand (treys convention — verify and document this in code comments, it trips people up).

### 3b. River decision (exact enumeration)

- All 5 board cards known. Only unknown: dealer's 2 hole cards.
- Enumerate all C(45,2) ≈ 990 combos of dealer hole cards from the remaining deck (52 − 2 hole − 5 board).
- For each: compute dealer's best 7-card hand, compare to yours. Tally win/lose/push.
- Decision: bet 1x if win% (counting pushes as neutral) clears the breakeven threshold for a 1x bet given the payout structure (push-on-no-qualify changes this breakeven point vs. a naive 50% threshold — compute this properly from the payout table, don't assume 50%). Otherwise fold.
- Cost: trivial, runs in milliseconds.

### 3c. Flop decision (Monte Carlo simulation)

- 3 board cards known. Unknowns: dealer's 2 hole cards + turn + river (4 cards from remaining 47).
- Exact enumeration (\~1M+ combos) is avoidable — instead sample N random completions (start with N=20,000, tune up if variance is a problem) of {dealer hand, turn, river} from the remaining deck, score win/lose/push for each sample, estimate win% from the sample.
- Decision: bet 2x if estimated equity clears the breakeven threshold for a 2x bet. Otherwise check.
- This is the one place where you're trading exactness for speed on purpose. Document that tradeoff in a code comment — future-you will wonder why this isn't exact like the river function.

### 3d. Pre-flop decision (precomputed lookup table)

- Only 2 hole cards, no board. Due to suit symmetry there are only 169 distinct starting-hand classes (e.g. "AKs", "72o", "33").
- Build a **separate offline script** (`generate_preflop_table.py`), run once, not at runtime: for each of the 169 classes, Monte Carlo simulate a large number of full random hands (deal a random dealer hand + random 5-card board, thousands to millions of trials) and record the resulting win/push/lose rates.
- Save the result as a static lookup table (JSON or a Python dict literal) — 169 entries.
- At runtime, the bot does zero computation pre-flop: canonicalize your 2 hole cards into one of the 169 classes, look up the win rate, compare to the 4x-bet breakeven threshold, decide bet or check.

### 3e. Shared breakeven math

- Write one function that, given the payout table (ante/blind payout odds, push-on-no-qualify rule, bet multiplier) and a win/push/lose probability triple, returns the expected value of betting vs. checking/folding. All three decision functions (3b/3c/3d) call this — don't duplicate the EV math three times.

## 4. Perception layer (build second — needs a decision first)

**Open question, needs your input before this layer can be designed:** what does the practice site actually look like technically?

- Plain HTML/DOM table → DOM-scraping (read card images/text via element selectors or alt-text) is straightforward and robust.
- Canvas-rendered or heavily obfuscated → likely needs screen-capture + image recognition (template matching on card images, or OCR) via something like OpenCV, which is far more fragile and a bigger build.
- Does the site have any inspectable API calls (check browser dev tools → Network tab for XHR/fetch calls during a hand) → if yes, reading those directly is far more reliable than reading pixels at all.

This determines whether Perception is a 1-day task or a multi-day fragile-automation project. Check this before Claude Code starts building it — tell it which case you're in.

## 5. Action layer (build third)

- Browser automation via Playwright or Selenium (Playwright preferred — faster, more modern API) to click the actual buttons (bet 4x / bet 2x / bet 1x / check / fold) once Decision Engine has returned a verdict.
- Keep this layer dumb — it only translates a decision enum into a click. All intelligence stays in the Decision Engine.

## 6. Suggested file layout

```
holdem-bot/
  decision/
    evaluator.py       # 3a
    river.py            # 3b
    flop.py             # 3c
    preflop.py          # 3d (loads the precomputed table)
    ev.py               # 3e shared breakeven math
  tools/
    generate_preflop_table.py   # offline, run once
    preflop_table.json          # generated output, checked into repo
  perception/
    reader.py           # site-specific, built after Q in section 4 is answered
  action/
    controller.py        # Playwright click wrapper
  main.py                 # orchestration loop
  tests/
    test_evaluator.py
    test_river.py
    test_flop.py
```

## 7. Build order (hand this to Claude Code roughly in this sequence)

1. Hand evaluator (3a) + tests against known hands
2. River exact decision (3b) + tests — this validates the EV math (3e) end to end on the cheapest case
3. Flop Monte Carlo (3c) — reuses the same evaluator and EV math, just samples instead of enumerates
4. Pre-flop table generator (3d) — run once offline, commit the resulting JSON
5. Answer the Perception question (section 4), then build perception/reader.py
6. Action layer + Playwright wiring
7. main.py orchestration loop tying it all together
8. End-to-end test on the actual practice site

## 8. Libraries

- `treys` — hand evaluation
- `playwright` — browser automation
- Standard lib `itertools.combinations` for exact enumeration (river, and the C(7,5) subset check)
- Standard lib `random` for Monte Carlo sampling (flop, preflop table generation)

## 9. Payout rules (verified against official casino rule sheets)

These are the exact numbers `decision/ev.py` should use. Don't let Claude Code infer or guess variations — qualification affects the Ante *only*; Play and Blind always resolve by directly comparing player's best hand to dealer's best hand, regardless of whether the dealer qualified.

### Blind bet

Pays only if your hand is a Straight or better AND you beat or tie the dealer. Otherwise push (even if you win with a weaker hand).

| Hand | Payout |
| --- | --- |
| Royal Flush | 500 : 1 |
| Straight Flush | 50 : 1 |
| Four of a Kind | 10 : 1 |
| Full House | 3 : 1 |
| Flush | 3 : 2 |
| Straight | 1 : 1 |
| Trips or lower | Push |

### Ante and Play — dealer QUALIFIES (pair or better)

- Player beats dealer → Ante 1:1, Play 1:1
- Dealer beats player → Ante loses, Play loses, Blind loses
- Tie → Ante push, Play push, Blind push

### Ante and Play — dealer DOES NOT qualify

- **Ante** → always pushes, regardless of outcome
- **Play** → still compared normally: player beats dealer's (non-qualifying) hand → pays 1:1; dealer beats player → Play loses; tie → Play pushes
- **Blind** → same table as above, same hand-vs-hand comparison — qualification is irrelevant to Blind

**Verify against the actual practice site's rules page before finalizing `ev.py`** — some online variants (especially non-US ones) tweak the Blind paytable slightly. These numbers are the generic/standard casino version; confirm the site matches before trusting them in the EV math.

## 10. Session handoff notes (for a fresh Claude Code session)

Use this section to re-orient a new session on the decision/ module without replaying the full chat history. Paste this whole section (or the doc) into the new session, or just point it at this doc plus `git log`.

### Status as of last session

- Branch: work has been happening on `decision-engine` (not `main`) — check `git branch` and merge/push as needed before continuing.
- Committed: `evaluator.py` (commit `ded39b7`), `ev.py` (commit `5aaf4ea`). Both have passing test suites (11 tests, 32 tests respectively).
- In progress / next: `river.py` has been written (not yet confirmed committed — check `git log` and `git status` first) implementing spec 3b. Next after that is `flop.py` (3c), then the pre-flop table generator (3d).
- Reason for this handoff: the previous session hit a context-window limit on the `deepseek-v4.1-flash` combo (128K token cap) and needed a fresh start.

### Locked-in design decisions (don't re-litigate these)

1. **EV baseline**: folding forfeits the Ante AND Blind (`ev_of_fold` = -(ante\_stake + blind\_stake) = -2 units), on all three streets. This, not the qualification rule, is why breakeven is \~19% instead of 50%.
2. **Outcome buckets**: 5 buckets, not 3 — `win_qualified`, `win_unqualified`, `push`, `lose_qualified`, `lose_unqualified` (see `decision.ev.Outcomes` and `BUCKETS`). A plain win/push/lose triple is insufficient because the Ante resolves differently depending on dealer qualification.
3. **Blind handling**: `bucket_payoffs(multiplier, blind_multiplier, table)` takes `blind_multiplier` as an explicit float — the Blind payout for the player's own final hand class. `river.py` computes it exactly via `blind_multiplier_for_score()` since the final hand is fully known. `flop.py`/`preflop.py` should pass 0.0 for now (not yet implemented — estimating it there was explicitly deferred, not forgotten).
4. **Threshold form**: `breakeven_win_rate(multiplier, *, tie_rate, qualify_on_win, qualify_on_lose, blind_multiplier=0.0, table=PAYOUT_TABLE)` — solved numerically by bisection against `ev_of_bet`, not a closed-form formula, so it can never drift out of sync with the EV calculation it's the root of. Each caller passes its own measured `tie_rate` and conditional qualify rates — never a global assumed constant.
5. **Monte Carlo sample sizes** (for flop.py and the pre-flop generator, not yet built): flop N=100,000 per decision (\~1.7s, acceptable — no live-latency constraint, single-player vs. house). Pre-flop table generator: N=2,000,000 trials per starting-hand class (\~1.6 hours total, one-time offline cost, not yet run).

### Two corrections made during the ev.py session (already fixed in the code/docstrings, kept here as context for why the numbers are what they are)

- The claim "\~19% breakeven matches the published '21 dealer outs' heuristic" was checked properly and does NOT hold precisely (lands closer to 24–25 outs) — directionally consistent, not a validated match. Real validation comes from `river.py` output compared against published hand-by-hand river charts.
- The spec's original claim that the non-qualify Ante-push rule is why breakeven isn't 50% is wrong. That rule only shifts the threshold by about 0.04 percentage points (the two effects of the rule nearly cancel). The real driver is simply that folding costs 2 units, not 0 — see the breakeven-at-zero-cost test and the module docstring in `ev.py` for the measured proof.

### Key function signatures already built (so new code composes with them, not around them)

```python
# decision/evaluator.py
best_hand_rank(hole: Sequence[int], board: Sequence[int]) -> int   # LOWER = stronger; 5-7 cards
hand_class(score: int) -> HandClass                                  # 0=royal flush ... 9=high card
remaining_deck(*known: Sequence[int]) -> list[int]
parse_cards(text: str | Iterable[str]) -> list[int]                  # "As Ks" -> treys ints

# decision/ev.py
class Outcomes:  # win_qualified, win_unqualified, push, lose_qualified, lose_unqualified
    @classmethod
    def from_counts(cls, **bucket_counts) -> "Outcomes": ...   # normalizes raw tallies

bucket_payoffs(multiplier, blind_multiplier=0.0, table=PAYOUT_TABLE) -> dict[str, float]
ev_of_bet(multiplier, outcomes, blind_multiplier=0.0, table=PAYOUT_TABLE) -> float
ev_of_fold(table=PAYOUT_TABLE) -> float
ev_advantage(multiplier, outcomes, blind_multiplier=0.0, table=PAYOUT_TABLE) -> float
should_bet(multiplier, outcomes, blind_multiplier=0.0, table=PAYOUT_TABLE) -> bool
breakeven_win_rate(multiplier, *, tie_rate, qualify_on_win, qualify_on_lose, blind_multiplier=0.0, table=PAYOUT_TABLE) -> float

# decision/river.py (spec 3b, written this session)
dealer_qualifies(score: int) -> bool
enumerate_dealer_outcomes(hole, board) -> dict[str, int]   # all C(45,2)=990 dealer combos, exact
decide(hole, board, table=PAYOUT_TABLE) -> RiverDecision    # .action is RiverAction.BET or .FOLD
```

### Next step for the new session

Confirm `river.py`'s commit status, then build `decision/flop.py` (spec 3c): Monte Carlo sampling over {dealer hand, turn, river} completions at N=100,000 samples, reusing `evaluator.py` and `ev.py` exactly as `river.py` does, but passing `blind_multiplier=0.0` (not yet estimated) and the sampled qualify-rate/tie-rate instead of exact enumeration. Validate `river.py`'s output against published UTH river strategy charts for a few known hands before moving on, per the deferred validation noted above.
