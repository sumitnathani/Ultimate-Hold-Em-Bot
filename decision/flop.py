"""Exact flop decision by enumeration (spec 3c).

Three board cards are known, so the unknowns are the dealer's two hole cards
*and* the turn and river. This module enumerates every combination of them and
counts exactly how often the hand wins, pushes and loses.

HOW BIG THE ENUMERATION IS, AND WHY
-----------------------------------
The unknowns split into two independent draws, not one:

    dealer's hole cards   C(47, 2) = 1,081   from the 47 cards left
    turn + river          C(45, 2) =   990   from the 45 left after that
    ---------------------------------------------------------------
    total                1,081 x 990 = 1,070,190

which is the "~1M+ combos" spec 3c cites. Every one of those 1,070,190 pairs is
equally likely, so enumerating all of them is exact: no sampling, no variance,
no standard error. Runtime is ~8-10s on the development machine.

THE TRAP: DO NOT ENUMERATE 4-CARD SUBSETS AND SPLIT THEM
--------------------------------------------------------
There is a tempting wrong way to write this that is both wrong and *faster*,
which makes it dangerous. It is:

    for draw in combinations(deck, 4):        # C(47,4) = 178,365  <-- WRONG
        dealer, runout = draw[:2], draw[2:]

``itertools.combinations`` yields each subset in the iterable's own order, and
``remaining_deck`` is ordered rank-then-suit, so ``draw[:2]`` is *always the two
lowest-ranked cards of the four*. The dealer would systematically receive the
small cards and the board the big ones. It also visits only 1/6 of the outcome
space, since a given 4-card set can be split 6 ways between dealer and runout
and all 6 are distinct, equally-likely situations.

That version runs in ~2.7s, which is exactly what makes it a trap: it looks
like the flop enumeration is cheap and the sampling in spec 3c is unnecessary.
It is not. It was written during this session, produced a 55% push rate on a
hand whose true push rate is 14%, and was caught by cross-checking against
independent Monte Carlo -- see ``test_the_enumeration_agrees_with_independent_
monte_carlo``, which exists to keep it caught. The fix is to draw the dealer
hand and the runout as the two separate draws they actually are, which is what
:func:`enumerate_runout_outcomes` does.

Ordering the loops runout-first is a genuine ~2x optimisation, not a
correctness trick: the player's score depends only on the five board cards, so
hoisting it out of the inner loop computes it 1,081 times instead of 1,070,190.

THE DECISION IT RETURNS
-----------------------
Bet 2x, or check -- there is no fold on the flop (spec 3c). The verdict is still
computed by comparing the EV of betting against :func:`decision.ev.ev_of_fold`,
the same 2-unit "give the hand up" baseline every street uses (spec 10, locked
decision 1). Note what that baseline is and is not: folding is not an action
available here, so ``ev_fold`` stands in for "do not bet now". Checking keeps the
Ante and Blind alive into the turn and river, so the true EV of checking is
strictly *above* -2 (folding is always available later, which makes -2 its
floor). Using -2 therefore makes betting look better than it is and biases this
screen toward betting 2x. That is a locked modelling simplification, flagged in
the session notes as an open question rather than silently baked in.

THE BLIND IS NOT YET PRICED HERE
--------------------------------
``blind_multiplier`` is 0.0. On the river the player's final hand class is fully
known, so the Blind payout can be read off the paytable exactly (see
:func:`decision.ev.blind_multiplier_for_score`). On the flop it is not: the
player's final five-card hand is one of the very things being enumerated, and
the Blind pays only for a Straight or better, so pricing it needs an expectation
over hand classes rather than a lookup. That estimation was explicitly deferred
by design (spec 10, locked decision 3). Zero is the correct *placeholder* rather
than a neutral guess: it can only understate the value of betting, so the error
is one-directional and this screen errs toward checking, not betting.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from typing import Sequence

from decision.evaluator import best_hand_rank, hand_name, remaining_deck
from decision.ev import (
    BUCKETS,
    PAYOUT_TABLE,
    Outcomes,
    PayoutTable,
    ev_of_bet,
    ev_of_fold,
)
# Both of these are street-agnostic: `dealer_qualifies` is spec 9's "pair or
# better" rule, and `breakeven_or_none` is the measured-rates wrapper around
# ev.breakeven_win_rate. They live in river.py only because the river was built
# first. Importing them keeps a single implementation rather than a second copy
# that can drift; relocating both into decision/ev.py would be the cleaner home,
# and is left as a follow-up so this step stays a one-file change.
from decision.river import breakeven_or_none, dealer_qualifies

__all__ = [
    "FLOP_PLAY_MULTIPLIER",
    "BOARD_SIZE",
    "DEALER_HAND_SIZE",
    "TURN_AND_RIVER",
    "ENUMERATION_SIZE",
    "FlopAction",
    "FlopDecision",
    "enumerate_runout_outcomes",
    "decide",
]

#: Spec 3c: the flop is a 2x bet or a check.
FLOP_PLAY_MULTIPLIER = 2.0
BOARD_SIZE = 3
DEALER_HAND_SIZE = 2
TURN_AND_RIVER = 2
#: C(47,2) * C(45,2). Named so tests can assert the enumeration is complete
#: without re-deriving the arithmetic.
ENUMERATION_SIZE = 1_070_190


class FlopAction(Enum):
    """What the decision engine wants the action layer to click."""

    BET = "bet"  # raise 2x
    CHECK = "check"


@dataclass(frozen=True)
class FlopDecision:
    """The full reasoning behind one flop decision, not just the verdict.

    Like :class:`decision.river.RiverDecision`, every number here is exact --
    the enumeration is exhaustive -- so any field can be used as ground truth.
    """

    action: FlopAction
    multiplier: float
    #: The player's *current* best five-card hand (2 hole + 3 board). Not the
    #: final hand: turn and river are still to come.
    player_score: int
    player_hand: str
    #: Always 0.0 for now -- see the module docstring.
    blind_multiplier: float
    outcomes: Outcomes
    #: Number of outcomes enumerated; always ENUMERATION_SIZE = 1,070,190.
    completions: int
    ev_bet: float
    ev_fold: float
    ev_advantage: float
    #: Win rate at which this decision would flip. ``None`` when it cannot be
    #: measured (a hand that can never win, or never lose, has no crossover).
    breakeven: float | None

    @property
    def equity(self) -> float:
        """P(win) over all completions. Pushes are excluded, as in spec 3b."""
        return self.outcomes.win

    @property
    def tie_rate(self) -> float:
        return self.outcomes.push

    def summary(self) -> str:
        be = "n/a" if self.breakeven is None else f"{self.breakeven:.2%}"
        return (
            f"{self.action.value.upper()} {self.multiplier:g}x  "
            f"[{self.player_hand}]  "
            f"win {self.equity:.2%} / push {self.tie_rate:.2%} / "
            f"lose {self.outcomes.lose:.2%}  "
            f"EV {self.ev_bet:+.3f} vs give-up {self.ev_fold:+.3f} "
            f"(advantage {self.ev_advantage:+.3f}, breakeven {be})"
        )


def enumerate_runout_outcomes(
    hole: Sequence[int], board: Sequence[int]
) -> dict[str, int]:
    """Count every (dealer hand, turn+river) pair into the five spec-9 buckets.

    Returns raw counts keyed by the bucket names in :data:`decision.ev.BUCKETS`;
    they sum to :data:`ENUMERATION_SIZE`. Counts rather than probabilities, so
    the caller can see the enumeration's size -- the same contract as
    :func:`decision.river.enumerate_dealer_outcomes`.

    The dealer hand and the runout are drawn as two *separate* combinations.
    See the module docstring for why splitting 4-card subsets instead is wrong.
    """
    deck = remaining_deck(hole, board)
    flop = list(board)

    counts = dict.fromkeys(BUCKETS, 0)
    for runout in combinations(deck, TURN_AND_RIVER):
        board5 = flop + list(runout)
        # Hoisted: the player's score depends only on the five board cards, so
        # this is computed once per runout rather than once per (runout, dealer)
        # pair -- 1,081 times instead of 1,070,190. Halves the runtime.
        player_score = best_hand_rank(hole, board5)

        remaining = [card for card in deck if card not in runout]
        for dealer in combinations(remaining, DEALER_HAND_SIZE):
            dealer_score = best_hand_rank(dealer, board5)
            qualified = dealer_qualifies(dealer_score)

            # treys: LOWER score is the STRONGER hand, so this comparison reads
            # backwards from how it looks. Player wins when their score is lower.
            if player_score < dealer_score:
                counts["win_qualified" if qualified else "win_unqualified"] += 1
            elif player_score > dealer_score:
                counts["lose_qualified" if qualified else "lose_unqualified"] += 1
            else:
                counts["push"] += 1
    return counts


def decide(
    hole: Sequence[int],
    board: Sequence[int],
    table: PayoutTable = PAYOUT_TABLE,
) -> FlopDecision:
    """Exact flop verdict for a known 2-card hand and 3-card board.

    Bets 2x when raising beats giving the hand up, checks otherwise. As on the
    river, the verdict comes from comparing the exact EVs rather than the win
    rate against the threshold -- equivalent, but immune to a degenerate
    threshold.

    Costs ~8-10s: 1,070,190 outcomes, each scoring two 7-card hands. Acceptable
    because there is no live-latency constraint here (single player against the
    house, no timer), and it is the price of an exact answer.
    """
    if len(board) != BOARD_SIZE:
        raise ValueError(
            f"flop decision needs a {BOARD_SIZE}-card board, got {len(board)}"
        )

    player_score = best_hand_rank(hole, board)
    counts = enumerate_runout_outcomes(hole, board)
    outcomes = Outcomes.from_counts(**counts)

    # Deferred by design (spec 10, locked decision 3): the Blind pays per final
    # hand class, and the final hand is what is being enumerated.
    blind = 0.0

    ev_bet = ev_of_bet(FLOP_PLAY_MULTIPLIER, outcomes, blind, table)
    ev_fold = ev_of_fold(table)

    return FlopDecision(
        action=FlopAction.BET if ev_bet > ev_fold else FlopAction.CHECK,
        multiplier=FLOP_PLAY_MULTIPLIER,
        player_score=player_score,
        player_hand=hand_name(player_score),
        blind_multiplier=blind,
        outcomes=outcomes,
        completions=sum(counts.values()),
        ev_bet=ev_bet,
        ev_fold=ev_fold,
        ev_advantage=ev_bet - ev_fold,
        breakeven=breakeven_or_none(outcomes, FLOP_PLAY_MULTIPLIER, blind, table),
    )
