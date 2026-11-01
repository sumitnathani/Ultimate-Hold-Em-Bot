"""Tests for decision/flop.py (spec 3c, exact enumeration).

Like the river tests, the enumeration is exhaustive so there is no tolerance to
hide behind and no seed to pin. Unlike the river, however, one test here *is*
deliberately statistical -- ``test_the_enumeration_agrees_with_independent_
monte_carlo`` -- because it is the specific check that caught a real bias bug in
this module's first implementation, and it should stay able to catch it again.

Two things get their own section, because both are places this module was
wrong once:

* the **baseline**. The flop's alternative is checking, not folding, and the
  difference is worth real money. ``test_the_check_baseline_and_the_blind_come_
  back_out_of_the_river`` recomputes the baseline from ``river.decide`` alone --
  no shared code with the sweep -- so the fused version has to agree.
* the **Blind**. It is priced as an exact expectation over the player's final
  hand class rather than a lookup, which only works if the effective multiplier
  is weighted by wins. The same test recomputes that weighting from the river's
  own per-runout values; see also ``test_the_effective_blind_reproduces_the_
  total_blind_profit`` for the identity it rests on.

Runtime note: every ``decide()`` costs ~8.3s (1,070,190 outcomes, two 7-card
hand evaluations each) and the river-recomputation test costs another ~8s. All
of it is done once in module-scoped fixtures; do not convert them to per-test
calls.
"""

from __future__ import annotations

import math
import random
from itertools import combinations
from math import comb

import pytest

from decision.evaluator import best_hand_rank, parse_cards, remaining_deck
from decision.ev import ev_of_bet, ev_of_fold
from decision.flop import (
    DEALER_HAND_SIZE,
    ENUMERATION_SIZE,
    FLOP_PLAY_MULTIPLIER,
    RUNOUT_COUNT,
    TURN_AND_RIVER,
    FlopAction,
    decide,
    enumerate_flop_outcomes,
)
from decision.river import RiverAction, decide as decide_river


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
    """All three cases, decided once (~25s) and shared across every test."""
    return {name: decide(c(hole), c(board)) for name, (hole, board) in CASES.items()}


@pytest.fixture(scope="module")
def weak_sweep():
    """The raw enumeration for the checking case, to check it against decide()."""
    hole, board = CASES["weak"]
    return enumerate_flop_outcomes(c(hole), c(board))


# --------------------------------------------------------------------------
# Enumeration completeness
# --------------------------------------------------------------------------


def test_enumeration_size_is_the_product_of_the_two_draws():
    """The unknowns are two independent draws, not one 4-card draw.

    C(47,2) runouts x C(45,2) dealer hands = 1,070,190. Enumerating
    C(47,4) = 178,365 instead would cover only a sixth of the outcome space and
    assign the dealer/runout roles by deck order -- the bug this module shipped
    with once already (see the module docstring and the Monte Carlo test below).
    """
    assert comb(47, TURN_AND_RIVER) == RUNOUT_COUNT
    assert comb(47, TURN_AND_RIVER) * comb(45, DEALER_HAND_SIZE) == ENUMERATION_SIZE


def test_every_completion_is_counted(decisions):
    for name, d in decisions.items():
        assert d.completions == ENUMERATION_SIZE, name
        assert d.outcomes.total == pytest.approx(1.0), name


def test_the_sweep_and_the_decision_describe_the_same_enumeration(decisions, weak_sweep):
    """The public enumeration and decide() must not be two different stories.

    ``decide`` reads the counts and both accumulators out of the sweep, so this
    checks the plumbing the whole module rests on: the by-products of the pass
    (the Blind total, the checking total) really are the ones the verdict was
    computed from.
    """
    d = decisions["weak"]
    assert CASES["weak"] == ("7c 2d", "Ks Qh Jd")

    assert weak_sweep.runouts == RUNOUT_COUNT
    assert sum(weak_sweep.counts.values()) == ENUMERATION_SIZE
    assert weak_sweep.outcomes == d.outcomes
    assert weak_sweep.effective_blind_multiplier == pytest.approx(d.blind_multiplier)
    assert weak_sweep.ev_check == pytest.approx(d.ev_check)
    assert weak_sweep.wins == weak_sweep.counts["win_qualified"] + weak_sweep.counts[
        "win_unqualified"
    ]


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
    holds -- so the win buckets are the only ones with mass, the verdict is BET,
    and the margin is analytic.
    """
    d = decisions["royal"]

    assert d.equity == 1.0
    assert d.tie_rate == 0.0
    assert d.outcomes.lose == 0.0
    assert d.player_hand == "Royal Flush"
    assert d.action is FlopAction.BET
    assert d.completions == ENUMERATION_SIZE

    # The always-royal final hand makes the Blind an exact lookup after all:
    # every runout's weighted contribution is the same 500, so the average of
    # them is 500 too. This is the one case where the expected multiplier and
    # the river's looked-up multiplier must agree exactly.
    assert d.blind_multiplier == 500.0

    # Payoffs(2x, B=500) are 503 qualified / 502 not, so EV = 502 + Q.
    # Payoffs(1x, B=500) are 502/501, so the optimal river is 501 + Q, and
    # checking is worth that because betting always beats folding here.
    assert d.ev_bet == pytest.approx(502.0 + d.outcomes.win_qualified)
    assert d.ev_check == pytest.approx(501.0 + d.outcomes.win_qualified)

    # And so the margin is exactly the extra 1x Play bet: one unit won on every
    # outcome, lost on none, because the hand never loses.
    assert d.ev_advantage == pytest.approx(1.0)
    assert d.breakeven is None, "can never lose, so there is no crossover point"


def test_a_marginal_pair_bets_and_a_high_card_hand_checks(decisions):
    """The two halves of the decision, on the same board.

    Note what the high-card case is compared against: checking, not folding.
    It bets badly (-2.454) *and* it checks badly (-1.651), because giving up
    two units is worse than seeing two more cards -- but checking is what it
    would actually be giving up, so checking is what the bet has to beat.
    """
    pair, weak = decisions["pair"], decisions["weak"]

    assert pair.player_hand == "Pair"
    assert pair.equity > pair.breakeven > 0.0
    assert pair.action is FlopAction.BET

    assert weak.player_hand == "High Card"
    assert weak.equity < weak.breakeven
    assert weak.action is FlopAction.CHECK
    assert weak.ev_bet < weak.ev_check


def test_a_stronger_holding_has_higher_equity_on_the_same_flop(decisions):
    """Sanity: on an identical board, the better hand must score better."""
    pair, weak = decisions["pair"], decisions["weak"]
    assert pair.equity > weak.equity
    assert pair.ev_bet > weak.ev_bet


# --------------------------------------------------------------------------
# The baseline: checking, not folding
# --------------------------------------------------------------------------


def test_the_check_baseline_and_the_blind_come_back_out_of_the_river(decisions):
    """Recompute both of the flop's fused by-products from river.decide alone.

    This is the independent route to the two numbers ``decide`` fuses into its
    single pass, and it shares no code with the sweep: it plays every runout out
    to a full five-card board and hands it to the river, exactly as a player who
    checked the flop would experience it. If the fused version ever drifts --
    wrong divisor, wrong runout weighting, a Blind credited from the wrong hand
    -- this is what catches it.

    Two quantities, each read off the river's own public verdict:

    * the **baseline**. ``max`` picks folding on a tie, so the river's value is
      its ``ev_bet`` when it bets and its ``ev_fold`` when it folds; that is the
      same definition ``river.optimal_ev`` carries, reached through the verdict
      rather than the helper.
    * the **Blind**. The river resolves the player's final hand class directly,
      so its ``blind_multiplier`` is the per-runout value the flop has to
      average -- weighted by that runout's *wins*, which the river also reports
      as a probability over its ``dealer_combos`` holdings.

    The flop's arithmetic is the same arithmetic; the flop just cannot do it in
    one lookup, because its final hand is not known until the runout is.
    """
    hole, board = c(CASES["pair"][0]), c(CASES["pair"][1])
    deck = remaining_deck(hole, board)

    total_ev = 0.0
    total_wins = 0.0
    total_blind = 0.0
    n = 0
    for runout in combinations(deck, TURN_AND_RIVER):
        river = decide_river(hole, list(board) + list(runout))
        total_ev += river.ev_bet if river.action is RiverAction.BET else river.ev_fold

        wins = river.outcomes.win * river.dealer_combos
        total_wins += wins
        total_blind += wins * river.blind_multiplier
        n += 1

    assert n == RUNOUT_COUNT
    d = decisions["pair"]
    assert d.ev_check == pytest.approx(total_ev / n)
    assert total_wins > 0.0, "otherwise the Blind check proves nothing"
    assert d.blind_multiplier == pytest.approx(total_blind / total_wins)


def test_checking_is_never_worse_than_folding(decisions):
    """The baseline has a floor, and it is -2 rather than -2 by accident.

    Checking keeps the turn and river alive, and folding is still available on
    the river, so the value of checking can never drop below what folding would
    have cost -- and in general sits strictly above it. This is the inequality
    the old flat-``ev_of_fold`` baseline got wrong: it treated the floor as if
    it were the value.
    """
    for name, d in decisions.items():
        assert d.ev_check >= ev_of_fold(), name
    # Both non-royal cases climb off the floor, which is why the distinction
    # costs money rather than being pedantry.
    for name in ("pair", "weak"):
        assert decisions[name].ev_check > ev_of_fold(), name


def test_the_old_flat_baseline_overstated_the_margin(decisions):
    """What the fix changed, stated as an inequality rather than a verdict.

    Measured against folding, the pair's bet looks comfortably good; measured
    against the alternative it actually has, the margin shrinks by exactly the
    amount the old baseline was too pessimistic about. Betting wins either way
    -- that is why the verdicts did not move -- but the size of the edge did.
    """
    pair = decisions["pair"]
    margin_vs_folding = pair.ev_bet - ev_of_fold()

    assert pair.ev_advantage == pytest.approx(pair.ev_bet - pair.ev_check)
    assert pair.ev_advantage < margin_vs_folding
    assert margin_vs_folding - pair.ev_advantage == pytest.approx(
        pair.ev_check - ev_of_fold()
    )
    # Both are still solidly positive: the correction shrank the edge, it did
    # not reverse it.
    assert pair.ev_advantage > 0.0


# --------------------------------------------------------------------------
# The Blind, priced as an expectation
# --------------------------------------------------------------------------


def test_the_blind_is_priced_as_an_expected_multiplier(decisions):
    """Three regimes, all exact -- and 0.0 only where it is genuinely zero.

    The Blind pays per the player's *final* hand class, which varies with the
    runout, so there is no single multiplier to look up. The expectation is
    weighted by how often each final hand wins, not by how often it occurs:
    a hand that wins 500:1 on one runout in 1,081 does not get diluted by the
    1,080 runouts where it lost, it gets diluted by the wins that paid nothing.
    """
    royal, pair, weak = (decisions[n] for n in ("royal", "pair", "weak"))

    # Every runout is a royal flush, so the average is exactly the lookup.
    assert royal.blind_multiplier == 500.0
    # 7c2d on K Q J cannot make a straight or better from two cards: the only
    # paying classes are unreachable, so this is exactly zero rather than
    # approximately.
    assert weak.blind_multiplier == 0.0
    # A pair of nines can make straights (9-T-J-Q-K) and quads, which pay, but
    # the great majority of its wins are pairs and two pairs, which do not --
    # so the weighted average sits well below the 1.5 a flush would pay.
    assert 0.0 < pair.blind_multiplier < 1.0


def test_the_effective_blind_reproduces_the_total_blind_profit(decisions):
    """Why a single weighted multiplier is exact rather than a fudge.

    Bucket payoffs credit the Blind on the two win buckets only, so pricing any
    multiplier ``B`` adds ``(win rate) x B`` to the EV. Setting
    ``B = (total Blind profit) / (number of wins)`` therefore reproduces the
    total exactly -- which is what the sweep accumulated per runout, where the
    multiplier is not constant.
    """
    pair = decisions["pair"]
    unbiased = ev_of_bet(FLOP_PLAY_MULTIPLIER, pair.outcomes, 0.0)
    biased = ev_of_bet(FLOP_PLAY_MULTIPLIER, pair.outcomes, pair.blind_multiplier)

    assert biased - unbiased == pytest.approx(pair.outcomes.win * pair.blind_multiplier)
    assert pair.blind_multiplier > 0.0, "otherwise this test proves nothing"
    assert pair.ev_bet == pytest.approx(biased)


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


# --------------------------------------------------------------------------
# Internal consistency
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["royal", "pair", "weak"])
def test_the_verdict_always_agrees_with_the_breakeven_threshold(decisions, name):
    """Spec 3c frames the decision as equity vs threshold; it must match.

    The verdict is computed from the exact EV and the threshold is the root of
    that same EV -- against the *checking* baseline, which is the point: a
    threshold solved against folding would be a different number and would
    disagree with the verdict on any hand sitting between the two.
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
