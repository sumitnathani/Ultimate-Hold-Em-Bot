#!/usr/bin/env python
"""Offline pre-flop table generator (spec 3d).

Runs once, not at runtime. For each of the 169 starting-hand classes it measures
two things and writes them to ``tools/preflop_table.json``, which is checked
into the repo so :mod:`decision.preflop` can look them up with zero computation.

TWO LOOPS, AND WHY THEY CANNOT SHARE SAMPLES
--------------------------------------------
**Rates** (``--trials``, default 2,000,000). Deal a random dealer hand and five
random board cards, agree the hole cards, and bucket the result. This is the one
place sampling is genuinely unavoidable in the whole project: the exact count is
C(50,7) = 99,884,400 per holding, which is ~0.4h *per distinct holding* against
1,326 of them. Millions of *samples* are wanted here, and the dealer is cheap to
sample (~14us of play, ~17us including both hand evaluations), so each sample
carries its own dealer hand.

**Baseline** (``--boards``, default 6,000). The pre-flop alternative to a 4x bet
is *checking*, and checking buys two further decisions, not one. Its value is
averaged over boards with the same definition the flop already uses per runout:
``river.optimal_ev`` over the dealer's exact C(45,2) distribution. That needs
distinct *boards* at ~8.9ms each, and no rate sample can be reused for it --
each carries one dealer hand out of 990, when the river wants all of them.

So the two loops are additive in cost, and the table stores one result from
each. They are also kept separate *in the file*, so a class can have its
baseline re-measured at a denser sample size without redoing 2,000,000 trials
(see "TIERS" below).

THE BLIND: A WIN-CONDITIONAL SCALAR
------------------------------------
At pre-flop decision time there is no board, so there is no final hand class and
the Blind multiplier **cannot** be looked up the way the river looks it up. It is
measured instead, exactly as :mod:`decision.flop` measures it: accumulate the
Blind payout over the *winning* samples and divide by the number of wins. Because
``bucket_payoffs`` credits the multiplier on precisely those same two win
buckets, a single scalar reproduces the total Blind profit exactly. (It is
win-conditional, so it is exact for the EV the decision uses, but only an
approximation inside ``breakeven_or_none``, which hypothesises other win rates.)

TIERS
-----
6,000 boards gives a check_value standard error of ~0.02, which is *coarser* than
the margin of the classes near the decision boundary -- the noise would be larger
than the signal the table exists to resolve. So the run is two-tier: everything
at 6,000, then a denser pass (``--boards 60000 --classes ...``) over just the
classes whose margin falls inside that band. A denser run re-measures only the
baseline and keeps the rates, since they are already converged.

CHECKPOINTING
-------------
The full run is ~4h measured on the development machine -- 1.6h of rates
(2,000,000 trials x 169 at ~17us) plus 2.5h of baselines (6,000 boards x 169 at
~8.9ms) -- so waiting until the end to write anything would mean
losing all of it to a crash, a kill, or a context limit. Each class is written
as it completes, and the write is atomic (temp file + replace) so an interrupted
write cannot truncate the table. Re-running skips work that is already done at
the requested sample sizes; ``--force`` redoes it.

Reproducibility: each class draws from its own seed derived from
``(--seed, label, loop)``, so class #57's numbers do not depend on whether the
classes before it ran, or on whether the run was resumed. A single shared RNG
stream would make a resumed table differ from a from-scratch one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from itertools import combinations
from pathlib import Path
from typing import Sequence

from treys import Card

from decision.evaluator import best_hand_rank, full_deck, remaining_deck
from decision.ev import (
    BUCKETS,
    PAYOUT_TABLE,
    Outcomes,
    PayoutTable,
    blind_multiplier_for_score,
    dealer_qualifies,
)
from decision.preflop import (
    STARTING_HAND_CLASS_COUNT,
    starting_hand_class,
    starting_hand_classes,
)
from decision.river import BOARD_SIZE, enumerate_dealer_outcomes, optimal_ev

#: 2 hole cards for the dealer + 5 board cards, drawn as one sample.
DEAL_SIZE = 7

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "preflop_table.json"
DEFAULT_SEED = 20_261_101
DEFAULT_TRIALS = 2_000_000
DEFAULT_BOARDS = 6_000

#: Bumped when the table's schema changes, so a stale file is detectable rather
#: than silently misread.
TABLE_VERSION = 1


def class_seed(seed: int, label: str, loop: str) -> int:
    """Deterministic per-class, per-loop seed.

    Hashed rather than added, so neighbouring classes get unrelated streams --
    ``seed + index`` would make consecutive classes draw correlated samples.
    The label is in the hash so a class can be re-measured alone and get exactly
    the numbers a full run would have given it.
    """
    digest = hashlib.sha256(f"{seed}:{label}:{loop}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def representative_holdings() -> dict[str, list[int]]:
    """One concrete two-card holding per class, e.g. ``"AKs"`` -> ``[Ks, As]``.

    Found by sweeping all C(52,2) = 1,326 holdings and keeping the first seen for
    each class, rather than by an inverse of :func:`starting_hand_class` that
    would encode the label convention a second time and could drift from it.

    Which holding is picked does not affect the result: suit symmetry means every
    holding in a class is the same hand up to relabelling the suits, which is a
    bijection on the sample space. The choice is recorded in the table's metadata
    so a row can always be traced back to the cards that produced it.
    """
    representatives: dict[str, list[int]] = {}
    for holding in combinations(full_deck(), 2):
        representatives.setdefault(starting_hand_class(holding), list(holding))
    if len(representatives) != STARTING_HAND_CLASS_COUNT:
        raise RuntimeError(
            f"the sweep found {len(representatives)} classes, expected "
            f"{STARTING_HAND_CLASS_COUNT} -- starting_hand_class is not "
            f"canonicalising the 1,326 holdings into 169"
        )
    return representatives


def sample_rates(
    hole: Sequence[int],
    trials: int,
    seed: int,
    table: PayoutTable = PAYOUT_TABLE,
) -> dict:
    """Monte Carlo full runouts into the five buckets, plus the Blind scalar.

    Each trial draws 7 cards from the 50 left after the hole cards and splits
    them: two for the dealer, five for the board. Drawing a uniform 7-subset and
    splitting it positionally is exactly uniform over disjoint
    (dealer hand, board) pairs, so no hand is over- or under-weighted.

    The dealer is re-sampled every trial rather than Rao-Blackwellised: the play
    cost is trivial next to evaluating two 7-card hands, and board-level variance
    dominates anyway.
    """
    rng = random.Random(seed)
    deck = remaining_deck(hole)
    counts = dict.fromkeys(BUCKETS, 0)
    blind_sum = 0.0

    for _ in range(trials):
        cards = rng.sample(deck, DEAL_SIZE)
        dealer, board = cards[:2], cards[2:]

        player_score = best_hand_rank(hole, board)
        dealer_score = best_hand_rank(dealer, board)
        qualified = dealer_qualifies(dealer_score)

        # treys: LOWER score is the STRONGER hand, so this reads backwards from
        # how it looks. Player wins when their score is lower.
        if player_score < dealer_score:
            counts["win_qualified" if qualified else "win_unqualified"] += 1
            # The Blind pays per *our* final hand class, so it is accumulated on
            # wins only -- bucket_payoffs credits it on exactly these buckets.
            blind_sum += blind_multiplier_for_score(player_score, table)
        elif player_score > dealer_score:
            counts["lose_qualified" if qualified else "lose_unqualified"] += 1
        else:
            counts["push"] += 1

    wins = counts["win_qualified"] + counts["win_unqualified"]
    return {
        "counts": counts,
        "trials": trials,
        "wins": wins,
        "blind_multiplier": blind_sum / wins if wins else 0.0,
    }


def sample_check_value(
    hole: Sequence[int],
    boards: int,
    seed: int,
    table: PayoutTable = PAYOUT_TABLE,
) -> dict:
    """Average the optimal river decision over sampled full boards.

    "Check pre-flop, check the flop, then play the river optimally" -- the flop's
    2x bet is the one option this does *not* price, which is the known residual
    bias (see SESSION_NOTES and ``tools/measure_flop_bias.py``).

    Each board is priced exactly, by the same ``river.optimal_ev`` call
    :mod:`decision.flop` already makes per runout, so there is no second
    implementation of "play this board well" to drift.
    """
    rng = random.Random(seed)
    deck = remaining_deck(hole)
    total = 0.0
    total_sq = 0.0

    for _ in range(boards):
        board = rng.sample(deck, BOARD_SIZE)
        blind = blind_multiplier_for_score(best_hand_rank(hole, board), table)
        # The board is known here, so the Blind is a plain lookup -- the
        # effective-multiplier device the flop needs is unnecessary.
        outcomes = Outcomes.from_counts(**enumerate_dealer_outcomes(hole, board))
        value = optimal_ev(outcomes, blind, table)
        total += value
        total_sq += value * value

    mean = total / boards
    variance = (total_sq - boards * mean * mean) / (boards - 1) if boards > 1 else 0.0
    return {
        "check_value": mean,
        "boards": boards,
        "check_value_se": math.sqrt(max(variance, 0.0) / boards),
    }


def measure_class(
    label: str,
    hole: Sequence[int],
    *,
    trials: int,
    boards: int,
    seed: int,
    table: PayoutTable = PAYOUT_TABLE,
    loops: Sequence[str] = ("rates", "baseline"),
) -> dict:
    """Measure one class. ``loops`` selects which of the two to run."""
    entry: dict = {}

    if "rates" in loops:
        entry.update(sample_rates(hole, trials, class_seed(seed, label, "rates"), table))
    if "baseline" in loops:
        entry.update(
            sample_check_value(hole, boards, class_seed(seed, label, "baseline"), table)
        )
    return entry


def load_table(path: Path) -> dict:
    """The stored table, or an empty one. Raises if the schema has moved on."""
    if not path.exists():
        return {"meta": {"version": TABLE_VERSION}, "classes": {}}
    with path.open("r", encoding="utf-8") as handle:
        table = json.load(handle)
    version = table.get("meta", {}).get("version")
    if version != TABLE_VERSION:
        raise SystemExit(
            f"{path} is schema version {version}, this tool writes "
            f"{TABLE_VERSION} -- move it aside or pass --output elsewhere"
        )
    return table


def save_table(path: Path, table: dict) -> None:
    """Write atomically: a run killed mid-write leaves the old table intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(table, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(temporary, path)


def _needs(entry: dict, key: str, wanted) -> bool:
    """True when a measurement is missing or was taken at a different setting."""
    return entry.get(key) != wanted


def _format_span(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.2f}h"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--boards", type=int, default=DEFAULT_BOARDS)
    parser.add_argument(
        "--classes",
        nargs="+",
        metavar="LABEL",
        help="measure only these classes (default: all 169), e.g. --classes AKs 72o",
    )
    parser.add_argument(
        "--rates-only",
        action="store_true",
        help="skip the board-averaged baseline loop",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="re-measure the baseline only, keeping the stored rates",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-measure even where the stored results already match",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="only report the final summary",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.rates_only and args.baseline_only:
        raise SystemExit("--rates-only and --baseline-only are mutually exclusive")
    loops = []
    if not args.baseline_only:
        loops.append("rates")
    if not args.rates_only:
        loops.append("baseline")

    known = starting_hand_classes()
    labels = list(args.classes) if args.classes else known
    unknown = sorted(set(labels) - set(known))
    if unknown:
        raise SystemExit(f"not starting-hand classes: {', '.join(unknown)}")

    representatives = representative_holdings()
    table = load_table(args.output)
    table.setdefault("classes", {})
    meta = table.setdefault("meta", {})
    meta.update(
        {
            "version": TABLE_VERSION,
            "seed": args.seed,
            "trials": args.trials,
            "boards": args.boards,
            "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "representatives": {
                label: " ".join(Card.int_to_str(card) for card in representatives[label])
                for label in known
            },
        }
    )

    started = time.monotonic()
    measured = 0
    reused = 0

    for index, label in enumerate(labels, start=1):
        entry = table["classes"].get(label, {})
        todo = []
        if "rates" in loops and (
            args.force
            or _needs(entry, "trials", args.trials)
            or not entry.get("counts")
        ):
            todo.append("rates")
        if "baseline" in loops and (
            args.force or _needs(entry, "boards", args.boards)
        ):
            todo.append("baseline")

        if not todo:
            reused += 1
            continue

        class_started = time.monotonic()
        entry.update(
            measure_class(
                label,
                representatives[label],
                trials=args.trials,
                boards=args.boards,
                seed=args.seed,
                loops=tuple(todo),
            )
        )
        table["classes"][label] = entry
        save_table(args.output, table)
        measured += 1

        if not args.quiet:
            elapsed = time.monotonic() - started
            remaining = (len(labels) - index) * (elapsed / index)
            print(
                f"[{index:>3}/{len(labels)}] {label:<4} {'+'.join(todo):<17} "
                f"{time.monotonic() - class_started:6.1f}s  "
                f"elapsed {_format_span(elapsed)}  eta {_format_span(remaining)}",
                flush=True,
            )

    elapsed = time.monotonic() - started
    print(
        f"\n{args.output}: {measured} measured, {reused} already current, "
        f"{len(table['classes'])}/{STARTING_HAND_CLASS_COUNT} classes stored "
        f"in {_format_span(elapsed)}",
        flush=True,
    )
    if len(table["classes"]) < STARTING_HAND_CLASS_COUNT:
        missing = [label for label in known if label not in table["classes"]]
        print(f"still missing {len(missing)}: {', '.join(missing[:12])}...", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())