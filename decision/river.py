"""Exact river decision by enumeration (spec 3b).

All five board cards are known, so the only unknown is the dealer's two hole
cards. There are C(45, 2) = 990 of those and no more, so this module simply
enumerates every one of them and counts exactly how often the hand wins, pushes
and loses. No sampling, no variance, no standard error -- the answer is exact.

That makes this the cheapest and most trustworthy of the three decision
functions, and it is where the EV math in :mod:`decision.ev` gets validated end
to end before the flop sampler (which *is* approximate) is allowed to depend on
it. Runtime is a few milliseconds.
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
    blind_multiplier_for_score,
    breakeven_or_none,
    dealer_qualifies,
    ev_of_bet,
    ev_of_fold,
)

__all__ = [
    "RIVER_PLAY_MULTIPLIER",
    "BOARD_SIZE",
    "RiverAction",
    "RiverDecision",
    "enumerate_dealer_outcomes",
    "optimal_ev",
    "decide",
]

#: Spec 3b: the river is a 1x bet or a fold.
RIVER_PLAY_MULTIPLIER = 1.0
BOARD_SIZE = 5


class RiverAction(Enum):
    """What the decision engine wants the action layer to click."""

    BET = "bet"  # raise 1x
    FOLD = "fold"


@dataclass(frozen=True)
class RiverDecision:
    """The full reasoning behind one river decision, not just the verdict.

    Everything here is exact (the enumeration is exhaustive), so any field can
    be used as ground truth when checking the flop sampler later.
    """

    action: RiverAction
    multiplier: float
    player_score: int
    player_hand: str
    blind_multiplier: float
    outcomes: Outcomes
    dealer_combos: int
    ev_bet: float
    ev_fold: float
    ev_advantage: float
    #: Win rate at which this decision would flip. ``None`` when it cannot be
    #: measured -- see :func:`breakeven_or_none`.
    breakeven: float | None

    @property
    def equity(self) -> float:
        """P(win). Pushes are excluded, exactly as spec 3b describes."""
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
            f"EV {self.ev_bet:+.3f} vs fold {self.ev_fold:+.3f} "
            f"(advantage {self.ev_advantage:+.3f}, breakeven {be})"
        )


def enumerate_dealer_outcomes(
    hole: Sequence[int], board: Sequence[int]
) -> dict[str, int]:
    """Count every C(45,2) dealer holding into the five spec-9 buckets.

    Returns raw combo counts keyed by the bucket names in
    :data:`decision.ev.BUCKETS`; they sum to 990. Counts rather than
    probabilities so the caller can see the enumeration's size.
    """
    player_score = best_hand_rank(hole, board)
    deck = remaining_deck(hole, board)

    counts = dict.fromkeys(BUCKETS, 0)
    for dealer in combinations(deck, 2):
        dealer_score = best_hand_rank(dealer, board)
        qualified = dealer_qualifies(dealer_score)

        # treys: LOWER score is the STRONGER hand, so the comparison reads
        # backwards from how it looks. Player wins when their score is lower.
        if player_score < dealer_score:
            counts["win_qualified" if qualified else "win_unqualified"] += 1
        elif player_score > dealer_score:
            counts["lose_qualified" if qualified else "lose_unqualified"] += 1
        else:
            counts["push"] += 1
    return counts


def optimal_ev(
    outcomes: Outcomes,
    blind_multiplier: float = 0.0,
    table: PayoutTable = PAYOUT_TABLE,
) -> float:
    """EV of playing this board's river optimally: the better of bet 1x and fold.

    The *definition* of the river decision, in one place, so the flop (3c) can
    price what checking is worth without restating it. Checking the flop buys
    exactly this and nothing more: the turn and river arrive, and the hand is
    then played as well as it can be.

    :func:`decide` reaches its verdict by comparing the same two EVs directly
    rather than calling through here. That is equivalent: ``max`` picks fold on
    a tie, and at a tie the two EVs are equal, so the value is the same either
    way.
    """
    return max(
        ev_of_bet(RIVER_PLAY_MULTIPLIER, outcomes, blind_multiplier, table),
        ev_of_fold(table),
    )


def decide(
    hole: Sequence[int],
    board: Sequence[int],
    table: PayoutTable = PAYOUT_TABLE,
) -> RiverDecision:
    """Exact river verdict for a known 2-card hand and 5-card board.

    Bets 1x when raising beats folding, folds otherwise. The verdict comes from
    comparing the exact EVs rather than from the win rate against the threshold,
    because the two are equivalent but the EV comparison cannot be thrown off by
    a degenerate threshold.
    """
    if len(board) != BOARD_SIZE:
        raise ValueError(
            f"river decision needs a full {BOARD_SIZE}-card board, got {len(board)}"
        )

    player_score = best_hand_rank(hole, board)
    counts = enumerate_dealer_outcomes(hole, board)
    outcomes = Outcomes.from_counts(**counts)

    # The Blind is a property of OUR final hand, which is fully known here --
    # this is the one street where the multiplier is exact rather than assumed.
    blind = blind_multiplier_for_score(player_score, table)

    ev_bet = ev_of_bet(RIVER_PLAY_MULTIPLIER, outcomes, blind, table)
    ev_fold = ev_of_fold(table)

    return RiverDecision(
        action=RiverAction.BET if ev_bet > ev_fold else RiverAction.FOLD,
        multiplier=RIVER_PLAY_MULTIPLIER,
        player_score=player_score,
        player_hand=hand_name(player_score),
        blind_multiplier=blind,
        outcomes=outcomes,
        dealer_combos=sum(counts.values()),
        ev_bet=ev_bet,
        ev_fold=ev_fold,
        ev_advantage=ev_bet - ev_fold,
        breakeven=breakeven_or_none(
            outcomes, RIVER_PLAY_MULTIPLIER, blind, table
        ),
    )
