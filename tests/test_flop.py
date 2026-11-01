"""Tests for decision/flop.py (spec 3c, exact enumeration).

Like the river tests, the enumeration is exhaustive so there is no tolerance to
hide behind and no seed to pin. Unlike the river, however, one test here *is*
deliberately statistical -- ``test_the_enumeration_agrees_with_independent_
monte_carlo`` -- because it is the specific check that caught a real bias bug in
this module's first implementation, and it should stay able to catch it again.

Runtime note: every ``decide()`` costs ~8.5s (1,070,190 outcomes, two 7-card
hand evaluations each). The three expensive cases are therefore computed once in
module-scoped fixtures and shared; do not convert them to per-test calls.
"""

from __future__ import annotations

import math
import random
from math import comb

import pytest

from decision.evaluator import best_hand_rank, parse_cards, remaining_deck
from decision.ev import bucket_payoffs, ev_of_fold
from decision.flop import (
    DEALER_HAND_SIZE,
    ENUMERATION_SIZE,
    FLOP_PLAY_MULTIPLIER,
    TURN_AND_RIVER,
    FlopAction,
    decide,
)


def c(text: str) -> list[int]:
    return parse_cards(text)


#: (hole, board, label). Three cases: the nuts, a marginal made pair, and a hand
#: that should check. `pair` and `weak` deliberately share a board so that
#: "stronger holding -> higher equity" is a like-for-like comparison.
CASES = {
    "royal": ("Js Ts", "As Ks Qs"),
    "pair": ("9h 9d", "Ks Qh Jd"),
    "weak": ("7c 2d", "Ks Qh Jd"),
}


@pytest.fixture(scope="module")
def decisions():
    """All three cases, decided once (~26s) and shared across every test."""
    return {name: decide(c(hole), c(board)) for name, (hole, board) in CASES.items()}


# --------------------------------------------------------------------------
# Enumeration completeness
# --------------------------------------------------------------------------


def test_enumeration_size_is_the_product_of_the_two_draws():
    """The unknowns are two independent draws, not one 4-card draw.

    C(47,2) dealer hands x C(45,2) turn+river pairs = 1,070,190. Enumerating
    C(47,4) = 178,365 instead would cover only a sixth of the outcome space and
    assign the dealer/runout roles by deck order -- the bug this module shipped
    with once already (see the module docstring and the Monte Carlo test below).
    """
    assert comb(47, DEALER_HAND_SIZE) * comb(45, TURN_AND_RIVER) == ENUMERATION_SIZE


def test_every_completion_is_counted(decisions):
    for name, d in decisions.items():
        assert d.completions == ENUMERATION_SIZE, name
        assert d.outcomes.total == pytest.approx(1.0), name


# --------------------------------------------------------------------------
# The bug guard
# --------------------------------------------------------------------------


def test_the_enumeration_agrees_with_independent_monte_carlo(decisions):
    """An independent sampler must reproduce the enumerated rates.

    This is the check that caught the C(47,4)-and-split bug, and it is here on
    purpose. That version assigned the dealer the two lowest-ranked cards of
    every 4-card subset, which pushed this hand's push rate from ~14.5% to ~55%
    -- roughly 40 standard errors out. The enumeration and the sampler share no
    code, so agreement is real evidence and not a tautology.

    Sampling here draws the dealer hand and the runout as two separate random
    draws, which is exactly the structure the enumeration has to mirror.
    """
    hole, board = c("7c 2d"), c("Ks Qh Jd")
    assert CASES["weak"] == ("7c 2d", "Ks Qh Jd")

    deck = remaining_deck(hole, board)
    rng = random.Random(20240531)
    n = 50_000
    wins = pushes = 0
    for _ in range(n):
        dealer = rng.sample(deck, DEALER_HAND_SIZE)
        rest = [card for card in deck if card not in dealer]
        runout = rng.sample(rest, TURN_AND_RIVER)
        board5 = list(board) + runout

        player_score = best_hand_rank(hole, board5)
        dealer_score = best_hand_rank(dealer, board5)
        if player_score < dealer_score:
            wins += 1
        elif player_score == dealer_score:
            pushes += 1

    d = decisions["weak"]
    for label, observed, expected in (
        ("win rate", wins / n, d.equity),
        ("push rate", pushes / n, d.tie_rate),
    ):
        se = math.sqrt(expected * (1.0 - expected) / n)
        assert abs(observed - expected) <= 5 * se, (
            f"{label}: sampled {observed:.4f} vs enumerated {expected:.4f} "
            f"(se {se:.5f}, {(observed - expected) / se:+.1f} sigma)"
        )


def test_the_flop_path_does_not_sample():
    """Guards the design decision, not the arithmetic (spec 3c, as corrected).

    Spec 3c called for Monte Carlo here; the exact enumeration replaced it with
    the project owner's sign-off. No RNG should reappear on this path without
    that being revisited deliberately.
    """
    import decision.flop as flop

    assert not {"random", "sample", "seed", "choice", "shuffle"} & vars(flop).keys()


# --------------------------------------------------------------------------
# Analytic cases
# --------------------------------------------------------------------------


def test_royal_flush_flopped_can_never_lose_or_tie(decisions):
    """Js Ts on As Ks Qs is already the nuts, with two cards still to come.

    All five spade honours are in play, so no dealer can make a royal flush to
    tie or beat it, and the turn and river cannot improve anyone past it. Every
    one of the 1,070,190 outcomes is a win, and it is a win whatever the dealer
    holds -- so the verdict is BET and the EV is bounded by the two win buckets:
    2 units (Ante push + Play) when the dealer misses, 3 when they qualify.
    """
    d = decisions["royal"]

    assert d.equity == 1.0
    assert d.tie_rate == 0.0
    assert d.outcomes.lose == 0.0
    assert d.player_hand == "Royal Flush"
    assert d.action is FlopAction.BET
    assert d.completions == ENUMERATION_SIZE

    assert ev_of_fold() == -2.0
    assert 2.0 < d.ev_bet < 3.0
    assert d.breakeven is None, "can never lose, so there is no crossover point"


def test_a_marginal_pair_bets_and_a_high_card_hand_checks(decisions):
    """The two halves of the decision, on the same board."""
    pair, weak = decisions["pair"], decisions["weak"]

    assert pair.player_hand == "Pair"
    assert pair.equity > pair.breakeven > 0.0
    assert pair.action is FlopAction.BET

    assert weak.player_hand == "High Card"
    assert weak.equity < weak.breakeven
    assert weak.action is FlopAction.CHECK
    assert weak.ev_bet < ev_of_fold()


def test_a_stronger_holding_has_higher_equity_on_the_same_flop(decisions):
    """Sanity: on an identical board, the better hand must score better."""
    pair, weak = decisions["pair"], decisions["weak"]
    assert pair.equity > weak.equity
    assert pair.ev_bet > weak.ev_bet


# --------------------------------------------------------------------------
# Structure that differs from the river, deliberately
# --------------------------------------------------------------------------


def test_losing_to_a_non_qualifying_dealer_is_possible_here(decisions):
    """The river's tidy "one of these buckets is always empty" rule does not hold.

    On the river the player's hand is fixed, so a player holding a pair can
    never lose to a non-qualifying (high card) dealer -- see the river tests.
    On the flop the player's final hand is one of the things being enumerated,
    so it varies: sometimes the player ends on a high card that a non-qualifying
    dealer's high card beats. That is why the five-bucket split matters *more*
    here, not less.
    """
    assert decisions["weak"].outcomes.lose_unqualified > 0.0


def test_the_blind_is_not_yet_priced(decisions):
    """Deferred by design (spec 10, locked decision 3), and 0.0 is not neutral.

    The Blind pays per the player's *final* hand class, which the flop
    enumeration does not resolve to a single value. Leaving it at 0.0 can only
    understate the value of betting, so the screen errs toward checking.
    """
    for name, d in decisions.items():
        assert d.blind_multiplier == 0.0, name

    # With the Blind unpriced, every win pays exactly the Ante+Play line and
    # nothing else -- which is the property the deferral is relying on.
    payoffs = bucket_payoffs(FLOP_PLAY_MULTIPLIER, 0.0)
    assert payoffs["win_qualified"] == 1.0 + FLOP_PLAY_MULTIPLIER
    assert payoffs["win_unqualified"] == FLOP_PLAY_MULTIPLIER
    assert payoffs["push"] == 0.0


# --------------------------------------------------------------------------
# Internal consistency
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["royal", "pair", "weak"])
def test_the_verdict_always_agrees_with_the_breakeven_threshold(decisions, name):
    """Spec 3c frames the decision as equity vs threshold; it must match.

    The verdict is computed from the exact EV and the threshold is the root of
    that same EV, so the two framings have to agree on every hand where the
    threshold is measurable at all.
    """
    d = decisions[name]
    if d.breakeven is None:
        assert d.action is FlopAction.BET
        return
    assert (d.equity > d.breakeven) is (d.action is FlopAction.BET)


def test_decide_rejects_an_incomplete_board():
    with pytest.raises(ValueError, match="3-card board"):
        decide(c("Ah Kd"), c("Qc 9h"))
    with pytest.raises(ValueError, match="3-card board"):
        decide(c("Ah Kd"), c("Qc 9h 5s 3d 2c"))
