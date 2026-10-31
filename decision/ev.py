"""Shared expected-value and breakeven math (spec 3e, payout table from spec 9).

Every street's decision -- river (3b), flop (3c), pre-flop (3d) -- reduces to
the same question: *given how often this hand wins, pushes and loses, is raising
better than giving the hand up?* That math lives here exactly once.

UNITS
-----
Everything is in **ante units**: the Ante and the Blind are 1 unit each, and the
Play bet is ``multiplier`` units (4 pre-flop, 2 on the flop, 1 on the river).
An EV of ``-0.45`` means "this decision costs 0.45 antes on average".

WHY THE OUTCOME BREAKDOWN HAS FIVE BUCKETS, NOT THREE
-----------------------------------------------------
Spec 9 makes the Ante resolve differently depending on whether the dealer
qualified (pair or better). So a plain ``(p_win, p_push, p_lose)`` triple is not
enough to price a hand: a win against a *qualifying* dealer collects the Ante,
while a win against a *non-qualifying* dealer pushes it. Those are different
amounts of money, so the win and lose buckets each split in two:

    win_qualified      you beat a dealer who had a pair or better
    win_unqualified    you beat a dealer who missed qualification
    push               tie -- Ante, Play and Blind all push (0 either way)
    lose_qualified     a qualifying dealer beat you
    lose_unqualified   a non-qualifying dealer beat you

:class:`Outcomes` carries those five probabilities. Callers get them for free:
``river.py`` sees them directly from its enumeration, ``flop.py`` from its
samples, and the pre-flop table stores them per starting-hand class.

THE PAYOUT MODEL (spec 9, "don't let anyone infer variations")
--------------------------------------------------------------
Dealer QUALIFIES (pair or better):
    you win   -> Ante +1, Play +m, Blind +B
    you lose  -> Ante -1, Play -m, Blind -1
    tie       -> all three push

Dealer does NOT qualify:
    Ante      -> ALWAYS pushes, win lose or tie. Qualification touches the Ante
                 and nothing else.
    Play      -> still compared normally, exactly as if the dealer had qualified
    Blind     -> still compared normally, exactly as if the dealer had qualified

The Blind only ever *pays* (B > 0) when you beat or tie the dealer AND your hand
is a Straight or better; below a Straight it pushes, so B = 0. On a loss the
Blind is lost like any other wager. B is therefore only ever applied to the two
win buckets -- see :func:`bucket_payoffs`.

WHY THE BREAKEVEN IS NOT 50%
----------------------------
The threshold is the win rate at which raising stops beating *folding*, and
folding forfeits the Ante **and** the Blind -- 2 units, not 0. So raising starts
2 units in the hole and only has to climb back to -2, not to 0. That is the
dominant reason the threshold sits near 19% rather than 50%.

The non-qualify Ante push is a real but much smaller second-order effect: it
helps you when a weak dealer beats you (Ante comes back) and costs you when you
beat a weak dealer (Ante no longer pays). Those two masses very nearly cancel,
which is why the rule shifts the threshold by well under a percentage point
rather than by the tens of points the phrase "not 50%" might suggest. See
``test_nonqualify_ante_push_barely_moves_the_breakeven``, which measures it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from decision.evaluator import HandClass, hand_class

__all__ = [
    "ANTE_STAKE",
    "BLIND_STAKE",
    "FOLD_COST",
    "BLIND_ODDS",
    "BUCKETS",
    "PayoutTable",
    "PAYOUT_TABLE",
    "Outcomes",
    "blind_multiplier_for",
    "blind_multiplier_for_score",
    "bucket_payoffs",
    "ev_of_bet",
    "ev_of_fold",
    "ev_advantage",
    "should_bet",
    "outcomes_from_win_rate",
    "breakeven_win_rate",
]

ANTE_STAKE = 1.0
BLIND_STAKE = 1.0
#: What folding costs: the Ante and the Blind are both already committed and
#: both are forfeited. This is the baseline every breakeven is measured against.
FOLD_COST = ANTE_STAKE + BLIND_STAKE

#: Blind payouts, spec 9. Profit per unit staked, so 1.5 is the "3:2" flush.
#: Everything below a Straight pushes, i.e. returns the stake with 0 profit.
BLIND_ODDS: dict[HandClass, float] = {
    HandClass.ROYAL_FLUSH: 500.0,
    HandClass.STRAIGHT_FLUSH: 50.0,
    HandClass.FOUR_OF_A_KIND: 10.0,
    HandClass.FULL_HOUSE: 3.0,
    HandClass.FLUSH: 1.5,
    HandClass.STRAIGHT: 1.0,
    HandClass.THREE_OF_A_KIND: 0.0,
    HandClass.TWO_PAIR: 0.0,
    HandClass.PAIR: 0.0,
    HandClass.HIGH_CARD: 0.0,
}

#: The five outcome buckets, in a fixed order so EV sums are deterministic.
BUCKETS = (
    "win_qualified",
    "win_unqualified",
    "push",
    "lose_qualified",
    "lose_unqualified",
)


@dataclass(frozen=True)
class PayoutTable:
    """The spec-9 payout structure, as data.

    Every field is a knob so tests can price counterfactual rule sets through
    the *same* code path rather than a hand-rolled second formula -- in
    particular ``ante_pushes_when_dealer_misses=False`` reconstructs a naive
    "ante always resolves 1:1" game, which is how the size of the non-qualify
    rule gets measured rather than asserted.
    """

    ante_stake: float = ANTE_STAKE
    blind_stake: float = BLIND_STAKE
    ante_odds: float = 1.0
    play_odds: float = 1.0
    blind_odds: Mapping[HandClass, float] = field(
        default_factory=lambda: dict(BLIND_ODDS)
    )
    ante_pushes_when_dealer_misses: bool = True


PAYOUT_TABLE = PayoutTable()


@dataclass(frozen=True)
class Outcomes:
    """How often each of the five spec-9 outcomes occurs.

    Values are probabilities summing to 1. Use :meth:`from_counts` when you have
    raw tallies (``river.py`` counts combos, ``flop.py`` counts samples) or
    :meth:`normalized` if you are not sure.
    """

    win_qualified: float = 0.0
    win_unqualified: float = 0.0
    push: float = 0.0
    lose_qualified: float = 0.0
    lose_unqualified: float = 0.0

    @property
    def win(self) -> float:
        return self.win_qualified + self.win_unqualified

    @property
    def lose(self) -> float:
        return self.lose_qualified + self.lose_unqualified

    @property
    def total(self) -> float:
        return self.win + self.push + self.lose

    def normalized(self) -> "Outcomes":
        """Scale to sum to 1. Raises if there is nothing to scale."""
        total = self.total
        if total <= 0.0:
            raise ValueError("cannot normalise an Outcomes with zero total mass")
        return Outcomes(*(getattr(self, b) / total for b in BUCKETS))

    @classmethod
    def from_counts(
        cls,
        *,
        win_qualified: float = 0.0,
        win_unqualified: float = 0.0,
        push: float = 0.0,
        lose_qualified: float = 0.0,
        lose_unqualified: float = 0.0,
    ) -> "Outcomes":
        """Build from raw counts (combo tallies, sample tallies) and normalise."""
        return cls(
            win_qualified=win_qualified,
            win_unqualified=win_unqualified,
            push=push,
            lose_qualified=lose_qualified,
            lose_unqualified=lose_unqualified,
        ).normalized()


def blind_multiplier_for(
    cls: HandClass, table: PayoutTable = PAYOUT_TABLE
) -> float:
    """Blind profit per unit for a hand class (0 below a Straight)."""
    return table.blind_odds[cls]


def blind_multiplier_for_score(score: int, table: PayoutTable = PAYOUT_TABLE) -> float:
    """Blind profit per unit for a treys score. Convenience for river.py."""
    return blind_multiplier_for(hand_class(score), table)


def bucket_payoffs(
    multiplier: float,
    blind_multiplier: float = 0.0,
    table: PayoutTable = PAYOUT_TABLE,
) -> dict[str, float]:
    """Net units won or lost in each outcome bucket, straight from spec 9.

    Reading this function against spec 9 line by line is the whole point: if a
    payout ever looks wrong, this is the only place to look.

    ``blind_multiplier`` is the Blind payout for *your* final hand class. It is
    only ever credited on the win buckets, because the Blind pays only when you
    beat or tie the dealer -- a tie pushes it, and a loss loses it.
    """
    ante = table.ante_odds
    play = multiplier * table.play_odds
    blind = blind_multiplier

    # Qualification affects the Ante and nothing else (spec 9). With the rule
    # off, the Ante resolves 1:1 against a non-qualifying dealer like any other
    # bet -- that counterfactual is what makes the rule's effect measurable.
    if table.ante_pushes_when_dealer_misses:
        ante_if_win_unqualified = 0.0
        ante_if_lose_unqualified = 0.0
    else:
        ante_if_win_unqualified = ante
        ante_if_lose_unqualified = -ante

    return {
        "win_qualified": ante + play + blind,
        "win_unqualified": ante_if_win_unqualified + play + blind,
        "push": 0.0,
        "lose_qualified": -ante - play - table.blind_stake,
        "lose_unqualified": ante_if_lose_unqualified - play - table.blind_stake,
    }


def ev_of_bet(
    multiplier: float,
    outcomes: Outcomes,
    blind_multiplier: float = 0.0,
    table: PayoutTable = PAYOUT_TABLE,
) -> float:
    """Expected value, in ante units, of raising ``multiplier`` units now.

    This is the EV of the *hand*, not of the Play bet in isolation: it includes
    the Ante and Blind resolving, because folding gives those up and that is what
    the decision is actually about.
    """
    payoffs = bucket_payoffs(multiplier, blind_multiplier, table)
    return sum(getattr(outcomes, bucket) * payoffs[bucket] for bucket in BUCKETS)


def ev_of_fold(table: PayoutTable = PAYOUT_TABLE) -> float:
    """EV of folding: the Ante and Blind are both forfeited."""
    return -(table.ante_stake + table.blind_stake)


def ev_advantage(
    multiplier: float,
    outcomes: Outcomes,
    blind_multiplier: float = 0.0,
    table: PayoutTable = PAYOUT_TABLE,
) -> float:
    """EV(raise) - EV(fold). Positive means raising is the better play."""
    return ev_of_bet(multiplier, outcomes, blind_multiplier, table) - ev_of_fold(table)


def should_bet(
    multiplier: float,
    outcomes: Outcomes,
    blind_multiplier: float = 0.0,
    table: PayoutTable = PAYOUT_TABLE,
) -> bool:
    """True when raising beats folding. Ties go to folding (see module notes)."""
    return ev_advantage(multiplier, outcomes, blind_multiplier, table) > 0.0


def outcomes_from_win_rate(
    p_win: float,
    *,
    tie_rate: float,
    qualify_on_win: float,
    qualify_on_lose: float,
) -> Outcomes:
    """Expand a win rate into the five buckets.

    ``tie_rate`` is held fixed, and the remaining mass splits into wins and
    losses. ``qualify_on_win`` / ``qualify_on_lose`` are the conditional
    probabilities that the dealer qualified, given the outcome -- these are
    measured per street by the callers, not assumed, because the dealer is much
    likelier to have qualified when they beat you than when you beat them.
    """
    if not 0.0 <= p_win <= 1.0 - tie_rate:
        raise ValueError(
            f"p_win={p_win} leaves no room for a tie_rate of {tie_rate}"
        )
    p_lose = 1.0 - tie_rate - p_win
    return Outcomes(
        win_qualified=p_win * qualify_on_win,
        win_unqualified=p_win * (1.0 - qualify_on_win),
        push=tie_rate,
        lose_qualified=p_lose * qualify_on_lose,
        lose_unqualified=p_lose * (1.0 - qualify_on_lose),
    )


def breakeven_win_rate(
    multiplier: float,
    *,
    tie_rate: float,
    qualify_on_win: float,
    qualify_on_lose: float,
    blind_multiplier: float = 0.0,
    table: PayoutTable = PAYOUT_TABLE,
) -> float:
    """Win rate at which raising ``multiplier`` exactly matches folding.

    Below this, folding is the better play; above it, raise. It is emphatically
    **not** 50% -- see the module docstring for why folding's 2-unit cost
    dominates.

    Solved numerically against :func:`ev_of_bet` rather than by a rearranged
    closed form, deliberately: the threshold can then never drift out of sync
    with the EV it is supposed to be the root of. EV is linear (so strictly
    monotone) in ``p_win`` with the tie rate held fixed, so bisection is exact
    to float precision.
    """
    target = ev_of_fold(table)

    def ev_at(p_win: float) -> float:
        return ev_of_bet(
            multiplier,
            outcomes_from_win_rate(
                p_win,
                tie_rate=tie_rate,
                qualify_on_win=qualify_on_win,
                qualify_on_lose=qualify_on_lose,
            ),
            blind_multiplier,
            table,
        )

    lo, hi = 0.0, 1.0 - tie_rate
    if ev_at(lo) >= target:
        return lo  # raising beats folding even at a 0% win rate
    if ev_at(hi) <= target:
        raise ValueError(
            "no breakeven in [0, 1 - tie_rate]: raising never beats folding, "
            "which means the payout table is misconfigured"
        )

    for _ in range(100):
        mid = (lo + hi) / 2.0
        if ev_at(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
