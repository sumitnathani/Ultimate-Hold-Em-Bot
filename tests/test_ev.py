"""Tests for decision/ev.py (spec 3e, payout table from spec 9).

Two things matter most here:

1. The bucket payoffs are a line-by-line transcription of spec 9, so they are
   asserted against hand-written expected numbers rather than against anything
   derived from the code under test.
2. The breakeven is *not* 50%, and the reason is the fold baseline rather than
   the non-qualify Ante rule. Both halves of that claim are tested, and the
   second one is measured rather than asserted.
"""

from __future__ import annotations

import pytest

from decision.evaluator import HandClass
from decision.ev import (
    BLIND_ODDS,
    FOLD_COST,
    PAYOUT_TABLE,
    Outcomes,
    PayoutTable,
    blind_multiplier_for,
    blind_multiplier_for_score,
    breakeven_win_rate,
    bucket_payoffs,
    ev_advantage,
    ev_of_bet,
    ev_of_fold,
    outcomes_from_win_rate,
    should_bet,
)
from decision.evaluator import parse_cards, best_hand_rank


# --------------------------------------------------------------------------
# Spec 9, transcribed by hand
# --------------------------------------------------------------------------


def test_blind_odds_match_spec_9_exactly():
    assert BLIND_ODDS == {
        HandClass.ROYAL_FLUSH: 500.0,
        HandClass.STRAIGHT_FLUSH: 50.0,
        HandClass.FOUR_OF_A_KIND: 10.0,
        HandClass.FULL_HOUSE: 3.0,
        HandClass.FLUSH: 1.5,  # the "3:2"
        HandClass.STRAIGHT: 1.0,
        HandClass.THREE_OF_A_KIND: 0.0,
        HandClass.TWO_PAIR: 0.0,
        HandClass.PAIR: 0.0,
        HandClass.HIGH_CARD: 0.0,
    }


def test_bucket_payoffs_match_spec_9():
    """Hand-written expectations, per spec 9's two rule blocks."""
    for multiplier, expected in [
        (1, {"win_qualified": 2.0, "win_unqualified": 1.0, "push": 0.0,
             "lose_qualified": -3.0, "lose_unqualified": -2.0}),
        (2, {"win_qualified": 3.0, "win_unqualified": 2.0, "push": 0.0,
             "lose_qualified": -4.0, "lose_unqualified": -3.0}),
        (4, {"win_qualified": 5.0, "win_unqualified": 4.0, "push": 0.0,
             "lose_qualified": -6.0, "lose_unqualified": -5.0}),
    ]:
        assert bucket_payoffs(multiplier) == expected


def test_qualification_touches_the_ante_and_nothing_else():
    """Win/lose payoffs must differ between qualify and not by exactly 1 unit.

    That single unit is the Ante. If Play or Blind ever leaked into the
    qualification split, this difference would not be exactly 1.
    """
    for multiplier in (1, 2, 4):
        payoffs = bucket_payoffs(multiplier)
        assert payoffs["win_qualified"] - payoffs["win_unqualified"] == pytest.approx(1.0)
        assert payoffs["lose_unqualified"] - payoffs["lose_qualified"] == pytest.approx(1.0)


def test_blind_multiplier_is_credited_on_wins_only():
    """A flush at the river: the 1.5x Blind is added to wins, lost on a loss."""
    payoffs = bucket_payoffs(1, blind_multiplier=1.5)
    assert payoffs["win_qualified"] == pytest.approx(1 + 1 + 1.5)
    assert payoffs["win_unqualified"] == pytest.approx(0 + 1 + 1.5)
    # Losing still costs the Blind stake whatever your hand class was.
    assert payoffs["lose_qualified"] == pytest.approx(-3.0)
    assert payoffs["lose_unqualified"] == pytest.approx(-2.0)
    assert payoffs["push"] == pytest.approx(0.0)


def test_blind_multiplier_for_score_follows_the_evaluator():
    royal = best_hand_rank(parse_cards("As Ks"), parse_cards("Qs Js Ts 2h 3d"))
    flush = best_hand_rank(parse_cards("Ac 9c"), parse_cards("7c 5c 3c 2h 9d"))
    pair = best_hand_rank(parse_cards("Tc Td"), parse_cards("8h 5s 2d 3c 9d"))

    assert blind_multiplier_for_score(royal) == 500.0
    assert blind_multiplier_for_score(flush) == 1.5
    assert blind_multiplier_for_score(pair) == 0.0  # "Trips or lower -> Push"
    assert blind_multiplier_for(HandClass.STRAIGHT) == 1.0


# --------------------------------------------------------------------------
# EV arithmetic
# --------------------------------------------------------------------------


def test_folding_costs_the_ante_and_the_blind():
    assert FOLD_COST == 2.0
    assert ev_of_fold() == -2.0


def test_ev_matches_a_hand_computed_example():
    """Worked by hand, and cross-checked against the closed form.

    Closed form, with w = P(win), l = P(lose), Q = P(win and qualified),
    L = P(lose and qualified):

        EV = (m + B) * w - (m + 1) * l + Q - L

    Both routes must agree; if the bucket sum and the algebra ever diverge,
    one of them has drifted.
    """
    o = Outcomes(
        win_qualified=0.30,
        win_unqualified=0.20,
        push=0.05,
        lose_qualified=0.35,
        lose_unqualified=0.10,
    )
    assert o.total == pytest.approx(1.0)

    # Bucket sum: 0.30*2 + 0.20*1 + 0.05*0 - 0.35*3 - 0.10*2
    assert ev_of_bet(1, o) == pytest.approx(0.6 + 0.2 - 1.05 - 0.2)
    assert ev_of_bet(1, o) == pytest.approx(-0.45)

    # Closed form: (1+0)*0.5 - (1+1)*0.45 + 0.30 - 0.35
    assert ev_of_bet(1, o) == pytest.approx(0.5 - 0.9 + 0.30 - 0.35)


def test_ev_is_linear_in_win_rate():
    """Doubling the win mass must not change the per-unit slope."""
    kw = dict(tie_rate=0.02, qualify_on_win=0.8, qualify_on_lose=0.95)
    base = ev_of_bet(1, outcomes_from_win_rate(0.30, **kw))
    step = ev_of_bet(1, outcomes_from_win_rate(0.31, **kw))
    step2 = ev_of_bet(1, outcomes_from_win_rate(0.32, **kw))
    assert (step - base) == pytest.approx(step2 - step)


def test_should_bet_agrees_with_the_sign_of_ev_advantage():
    good = Outcomes(win_qualified=0.45, win_unqualified=0.20, push=0.02,
                    lose_qualified=0.28, lose_unqualified=0.05)
    bad = Outcomes(win_qualified=0.05, win_unqualified=0.05, push=0.02,
                   lose_qualified=0.60, lose_unqualified=0.28)

    assert ev_advantage(1, good) > 0 and should_bet(1, good)
    assert ev_advantage(1, bad) < 0 and not should_bet(1, bad)


def test_a_coin_flip_river_hand_is_a_clear_raise():
    """~50% to win on the river: raising is not close, because folding burns 2."""
    o = Outcomes(win_qualified=0.42, win_unqualified=0.08, push=0.02,
                 lose_qualified=0.43, lose_unqualified=0.05)
    assert should_bet(1, o)
    assert ev_advantage(1, o) > 1.0


# --------------------------------------------------------------------------
# The breakeven threshold
# --------------------------------------------------------------------------

# Representative river-ish numbers. The conditional qualify rates are the ones
# river.py will measure exactly; the asymmetry (dealer much likelier to have
# qualified when they beat you) is the whole reason the split exists.
RIVER_LIKE = dict(tie_rate=0.02, qualify_on_win=0.80, qualify_on_lose=0.95)


def test_breakeven_is_not_fifty_percent():
    """The headline claim from the build spec, made concrete.

    Folding forfeits the Ante AND the Blind -- 2 units -- so raising starts 2
    units down and only has to climb back to -2, not to 0. That is what drags
    the threshold from ~50% down to ~19%, and it is why "counting pushes as
    neutral" around a naive 50% line would be badly wrong.
    """
    threshold = breakeven_win_rate(1, **RIVER_LIKE)

    assert threshold == pytest.approx(0.1876, abs=1e-3)
    assert threshold < 0.25
    assert threshold != pytest.approx(0.50)

    # Closed form for the same quantity:
    #   w* = (FOLD + (m + 1 + q_lose)(1 - t)) / (2m + B + 1 + q_win + q_lose)
    expected = (-2.0 + (1 + 1 + 0.95) * (1 - 0.02)) / (2 + 0 + 1 + 0.80 + 0.95)
    assert threshold == pytest.approx(expected)


def test_breakeven_agrees_with_the_ev_it_is_the_root_of():
    """Just below the threshold raising loses to folding; just above, it wins."""
    threshold = breakeven_win_rate(1, **RIVER_LIKE)

    def adv(p_win):
        return ev_advantage(1, outcomes_from_win_rate(p_win, **RIVER_LIKE))

    assert adv(threshold) == pytest.approx(0.0, abs=1e-9)
    assert adv(threshold - 0.01) < 0
    assert adv(threshold + 0.01) > 0


def test_breakeven_scales_the_right_way_with_the_multiplier():
    """A bigger Play bet wins more when it wins and loses more when it loses."""
    one_x = breakeven_win_rate(1, **RIVER_LIKE)
    two_x = breakeven_win_rate(2, **RIVER_LIKE)
    four_x = breakeven_win_rate(4, **RIVER_LIKE)

    assert one_x < two_x < four_x < 0.5


def test_nonqualify_ante_push_barely_moves_the_breakeven():
    """Measure the size of the rule the spec says "shifts" the threshold.

    Turning the rule off reconstructs a naive game where the Ante always
    resolves 1:1. The two masses it moves -- wins against a weak dealer (Ante
    stops paying) and losses to a weak dealer (Ante comes back) -- nearly
    cancel, so the rule is worth only a few hundredths of a percentage point.

    This is deliberately an assertion that the effect is SMALL. The reason the
    threshold is nowhere near 50% is the 2-unit cost of folding, not this rule;
    the spec's parenthetical credits the wrong mechanism.
    """
    with_rule = breakeven_win_rate(1, **RIVER_LIKE)
    without_rule = breakeven_win_rate(
        1, table=PayoutTable(ante_pushes_when_dealer_misses=False), **RIVER_LIKE
    )

    assert without_rule == pytest.approx(0.188, abs=1e-3)
    assert abs(with_rule - without_rule) < 0.005, "rule should be near-negligible"
    # The push protects the loss side slightly more than it taxes the win side,
    # so it nudges the threshold *down*.
    assert with_rule < without_rule


def test_breakeven_rises_when_folding_is_cheaper():
    """Sanity check on the mechanism: cheaper folds demand better hands.

    If folding cost 0 (the "play bet in isolation" framing the spec warns
    against), the threshold should climb to roughly a coin flip.
    """
    naive = PayoutTable(ante_stake=0.0, blind_stake=0.0)
    assert breakeven_win_rate(1, table=naive, **RIVER_LIKE) == pytest.approx(0.5, abs=0.02)


def test_breakeven_collapses_to_zero_when_raising_always_beats_folding():
    """Guard 1: if raising beats folding even at a 0% win rate, threshold is 0.

    A negative ``ante_odds`` makes *losing* pay as well, so this table has
    raising profitable no matter what -- there is no interior breakeven, and 0
    ("any hand at all") is the correct answer rather than a bogus root.
    """
    upside_down = PayoutTable(ante_odds=-5.0)
    assert breakeven_win_rate(1, table=upside_down, **RIVER_LIKE) == 0.0


def test_breakeven_fails_loudly_when_raising_can_never_win():
    """Guard 2: a table where raising loses at every possible win rate.

    This branch needs a deliberately perverse table, and the numbers are chosen
    only to reach it: a negative ``ante_odds`` cannot drag the win payoff below
    folding's cost on its own, because it also makes losses pay. Satisfying both
    ``EV(0% wins) < -2`` and ``EV(98% wins) < -2`` therefore needs a large
    positive ante combined with a hugely negative Play bet (here EV is -2.3 at
    both ends). The table is nonsense, but the guard is not dead code, and this
    keeps it that way.
    """
    absurd = PayoutTable(ante_odds=24.0, play_odds=-21.5)
    with pytest.raises(ValueError, match="no breakeven"):
        breakeven_win_rate(1, table=absurd, **RIVER_LIKE)


def test_a_richer_blind_lowers_the_breakeven():
    """Mechanism check on the payout table, the part the spec calls easy to invert.

    A flush's 1.5x Blind is pure upside on a hand you were raising anyway, so
    pricing it in must make raising attractive at a *worse* win rate.
    """
    without = breakeven_win_rate(1, **RIVER_LIKE)
    with_flush_blind = breakeven_win_rate(1, blind_multiplier=1.5, **RIVER_LIKE)
    assert with_flush_blind < without


# --------------------------------------------------------------------------
# Input handling
# --------------------------------------------------------------------------


def test_from_counts_normalises():
    o = Outcomes.from_counts(
        win_qualified=450, win_unqualified=90, push=20,
        lose_qualified=380, lose_unqualified=50,
    )
    assert o.total == pytest.approx(1.0)
    assert o.win_qualified == pytest.approx(450 / 990)
    assert o.win == pytest.approx(540 / 990)


def test_outcomes_rejects_a_win_rate_that_overflows_the_tie_rate():
    with pytest.raises(ValueError, match="leaves no room"):
        outcomes_from_win_rate(0.99, tie_rate=0.02, qualify_on_win=0.8, qualify_on_lose=0.95)


def test_normalised_rejects_zero_mass():
    with pytest.raises(ValueError, match="zero total mass"):
        Outcomes().normalized()
