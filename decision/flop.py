"""Exact flop decision by enumeration (spec 3c).

Three board cards are known, so the unknowns are the dealer's two hole cards
*and* the turn and river. This module enumerates every combination of them and
counts exactly how often the hand wins, pushes and loses.

HOW BIG THE ENUMERATION IS, AND WHY
-----------------------------------
The unknowns split into two independent draws, not one:

    turn + river          C(47, 2) = 1,081   from the 47 cards left
    dealer's hole cards   C(45, 2) =   990   from the 45 left after that
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
It is not. It was written during an earlier session, produced a 55% push rate
on a hand whose true push rate is 14%, and was caught by cross-checking against
independent Monte Carlo -- see ``test_the_enumeration_agrees_with_independent_
monte_carlo``, which exists to keep it caught. The fix is to draw the runout and
the dealer hand as the two separate draws they actually are, which is what
:func:`enumerate_flop_outcomes` does.

Ordering the loops runout-first is a genuine ~2x optimisation, not a
correctness trick: the player's score depends only on the five board cards, so
hoisting it out of the inner loop computes it 1,081 times instead of 1,070,190.

THE VERDICT IS BET 2x OR CHECK, AND CHECKING IS THE BASELINE
------------------------------------------------------------
There is no fold on the flop (spec 3c); the two actions are bet 2x and check.
So the hand is not "raise or give up", it is "raise now or keep playing", and
the bar betting has to clear is the value of *checking* -- not the value of
folding.

Checking the flop buys exactly one thing: the turn and river arrive, and the
hand is then played as well as it can be. That is the river's optimal decision,
which :func:`decision.river.optimal_ev` already defines exactly for any known
board. So the value of checking is the average of that quantity over every
runout, and this module computes it directly, in the same pass that counts the
outcomes: 1,081 runouts, each one grading its own 990 dealer hands and pricing
its own river. Averaging per runout is the same as averaging over all 1,070,190
pairs, because every runout owns exactly 990 of them.

The consequence is that ``ev_check`` is never below -2 and is usually well
above it: folding is still available on the river, which makes -2 the *floor*
of checking's value rather than its value. An earlier revision of this module
compared ``ev_bet`` against the flat ``ev_of_fold()`` baseline instead, which
made betting look better than it is by exactly the gap between the two -- a
one-directional bias toward betting 2x, and the reason this was fixed rather
than carried in the notes.

THE BLIND IS PRICED HERE, AS AN EXPECTED MULTIPLIER
---------------------------------------------------
On the river the player's final hand class is known, so the Blind payout is a
lookup (:func:`decision.ev.blind_multiplier_for_score`). On the flop the final
hand is one of the things being enumerated, so there is no single multiplier to
look up -- but there is no need to give up and pass 0.0 either, because the
enumeration already knows the player's final hand for every outcome it visits.

What is needed is the *total* Blind profit across all 1,070,190 outcomes:
:attr:`FlopSweep.blind_sum` accumulates it, weighting each runout's win count by
that runout's Blind payout. Dividing by the total number of wins gives an
effective multiplier that reproduces that total exactly, since

    sum(payoff with the Blind priced) = sum(payoff without it) + wins x effective

and wins x effective = blind_sum by construction. That makes the effective
multiplier an exact device rather than an approximation: it is a weighted
average, weighted by how often each final hand actually wins, and it is derived
from the same single pass, so it cannot drift from the outcomes beside it.
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
)
from decision.river import optimal_ev

__all__ = [
    "FLOP_PLAY_MULTIPLIER",
    "BOARD_SIZE",
    "DEALER_HAND_SIZE",
    "TURN_AND_RIVER",
    "RUNOUT_COUNT",
    "ENUMERATION_SIZE",
    "FlopAction",
    "FlopSweep",
    "FlopDecision",
    "enumerate_flop_outcomes",
    "decide",
]

#: Spec 3c: the flop is a 2x bet or a check.
FLOP_PLAY_MULTIPLIER = 2.0
BOARD_SIZE = 3
DEALER_HAND_SIZE = 2
TURN_AND_RIVER = 2
#: C(47, 2): how many turn+river pairs there are once hole and flop are known.
#: Also the divisor that turns the per-runout sums into expectations.
RUNOUT_COUNT = 1_081
#: C(47,2) * C(45,2). Named so tests can assert the enumeration is complete
#: without re-deriving the arithmetic.
ENUMERATION_SIZE = 1_070_190


class FlopAction(Enum):
    """What the decision engine wants the action layer to click."""

    BET = "bet"  # raise 2x
    CHECK = "check"


@dataclass(frozen=True)
class FlopSweep:
    """Everything one full pass over the 1,070,190 outcomes yields.

    The counts and the two sums are produced together, in a single pass, on
    purpose. Pricing the Blind and the value of checking both need the player's
    final hand per runout, which only the enumeration knows; computing them
    anywhere else would mean a second pass that could quietly disagree with the
    first. Derived quantities are properties here for the same reason: there is
    one place to read them from, not three that can drift apart.
    """

    #: Raw counts keyed by :data:`decision.ev.BUCKETS`; they sum to
    #: :data:`ENUMERATION_SIZE`.
    counts: dict[str, int]
    #: Number of turn+river pairs swept; always :data:`RUNOUT_COUNT`.
    runouts: int
    #: Total Blind profit over every winning outcome, in units. Each runout
    #: contributes (its wins) x (that runout's Blind payout).
    blind_sum: float
    #: EV of checking, summed over runouts. Divide by ``runouts`` to average it.
    check_sum: float

    @property
    def outcomes(self) -> Outcomes:
        return Outcomes.from_counts(**self.counts)

    @property
    def wins(self) -> int:
        return self.counts["win_qualified"] + self.counts["win_unqualified"]

    @property
    def effective_blind_multiplier(self) -> float:
        """Blind profit per unit averaged over the winning outcomes.

        Exact, not an estimate -- see the module docstring. Zero when nothing
        wins, and zero when the hands that do win never pay on the Blind.
        """
        return self.blind_sum / self.wins if self.wins else 0.0

    @property
    def ev_check(self) -> float:
        """EV of checking this flop: the average optimal river decision."""
        return self.check_sum / self.runouts


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
    #: Blind profit per unit, averaged over the winning outcomes. An exact
    #: expectation rather than a lookup, because the final hand varies with the
    #: runout -- see :attr:`FlopSweep.effective_blind_multiplier`.
    blind_multiplier: float
    outcomes: Outcomes
    #: Number of outcomes enumerated; always ENUMERATION_SIZE = 1,070,190.
    completions: int
    ev_bet: float
    #: The alternative actually available here -- the EV of checking, i.e. of
    #: playing the turn and river optimally. Always at least -2, since folding
    #: remains available on the river.
    ev_check: float
    #: ``ev_bet - ev_check``. Positive means betting 2x is the better play.
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
            f"EV {self.ev_bet:+.3f} vs check {self.ev_check:+.3f} "
            f"(advantage {self.ev_advantage:+.3f}, breakeven {be})"
        )


def enumerate_flop_outcomes(
    hole: Sequence[int], board: Sequence[int], table: PayoutTable = PAYOUT_TABLE
) -> FlopSweep:
    """Sweep every (turn+river, dealer hand) pair into the five spec-9 buckets.

    Returns a :class:`FlopSweep`: the raw counts plus the two accumulators that
    pricing the Blind and the value of checking need. Everything comes out of
    one traversal -- see the class docstring for why that is not just an
    optimisation.

    The runout and the dealer hand are drawn as two *separate* combinations.
    See the module docstring for why splitting 4-card subsets instead is wrong.
    """
    deck = remaining_deck(hole, board)
    flop = list(board)

    counts = dict.fromkeys(BUCKETS, 0)
    blind_sum = 0.0
    check_sum = 0.0
    runouts = 0

    for runout in combinations(deck, TURN_AND_RIVER):
        board5 = flop + list(runout)
        # Hoisted: the player's final score depends only on the five board
        # cards, so this is computed once per runout rather than once per
        # (runout, dealer) pair -- 1,081 times instead of 1,070,190.
        player_score = best_hand_rank(hole, board5)
        player_blind = blind_multiplier_for_score(player_score, table)

        remaining = [card for card in deck if card not in runout]
        runout_counts = dict.fromkeys(BUCKETS, 0)
        for dealer in combinations(remaining, DEALER_HAND_SIZE):
            dealer_score = best_hand_rank(dealer, board5)
            qualified = dealer_qualifies(dealer_score)

            # treys: LOWER score is the STRONGER hand, so this comparison reads
            # backwards from how it looks. Player wins when their score is lower.
            if player_score < dealer_score:
                runout_counts["win_qualified" if qualified else "win_unqualified"] += 1
            elif player_score > dealer_score:
                runout_counts["lose_qualified" if qualified else "lose_unqualified"] += 1
            else:
                runout_counts["push"] += 1

        for bucket in BUCKETS:
            counts[bucket] += runout_counts[bucket]

        # The Blind pays per final hand class, so it is worth this runout's
        # multiplier on each of this runout's wins -- and 0 on a tie or a loss,
        # which is why only the win buckets are counted. bucket_payoffs() credits
        # the multiplier on exactly those same two buckets, so the effective
        # multiplier below reproduces this total exactly.
        wins = runout_counts["win_qualified"] + runout_counts["win_unqualified"]
        blind_sum += wins * player_blind

        # Checking the flop is worth a known board plus an optimal river. The
        # dealer's holdings are already counted, so the river verdict here is
        # free -- and exact, unlike the sampled rates spec 3c originally wanted.
        check_sum += optimal_ev(Outcomes.from_counts(**runout_counts), player_blind, table)
        runouts += 1

    return FlopSweep(
        counts=counts, runouts=runouts, blind_sum=blind_sum, check_sum=check_sum
    )


def decide(
    hole: Sequence[int],
    board: Sequence[int],
    table: PayoutTable = PAYOUT_TABLE,
) -> FlopDecision:
    """Exact flop verdict for a known 2-card hand and 3-card board.

    Bets 2x when raising beats checking, checks otherwise. As on the river, the
    verdict comes from comparing the exact EVs rather than the win rate against
    the threshold -- equivalent, but immune to a degenerate threshold.

    Costs ~8-10s: 1,070,190 outcomes, each scoring two 7-card hands. Acceptable
    because there is no live-latency constraint here (single player against the
    house, no timer), and it is the price of an exact answer.
    """
    if len(board) != BOARD_SIZE:
        raise ValueError(
            f"flop decision needs a {BOARD_SIZE}-card board, got {len(board)}"
        )

    player_score = best_hand_rank(hole, board)
    sweep = enumerate_flop_outcomes(hole, board, table)

    outcomes = sweep.outcomes
    blind = sweep.effective_blind_multiplier
    ev_check = sweep.ev_check
    ev_bet = ev_of_bet(FLOP_PLAY_MULTIPLIER, outcomes, blind, table)

    return FlopDecision(
        action=FlopAction.BET if ev_bet > ev_check else FlopAction.CHECK,
        multiplier=FLOP_PLAY_MULTIPLIER,
        player_score=player_score,
        player_hand=hand_name(player_score),
        blind_multiplier=blind,
        outcomes=outcomes,
        completions=sum(sweep.counts.values()),
        ev_bet=ev_bet,
        ev_check=ev_check,
        ev_advantage=ev_bet - ev_check,
        breakeven=breakeven_or_none(
            outcomes, FLOP_PLAY_MULTIPLIER, blind, table, baseline=ev_check
        ),
    )
