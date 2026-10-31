"""Tests for decision/river.py (spec 3b).

The enumeration is exhaustive, so unlike the flop sampler there is no tolerance
to hide behind: every expected number here is either an exact fraction worked
out by hand or an exact count. The three headline cases (unbeatable nuts, an
unbeatable board, and a hand that can never win) are all cases where the answer
is knowable without running the code at all.
"""

from __future__ import annotations

from math import comb

import pytest

from decision.evaluator import best_hand_rank, full_deck, parse_cards, remaining_deck
from decision.ev import BLIND_ODDS, Outcomes
from decision.river import (
    RIVER_PLAY_MULTIPLIER,
    RiverAction,
    dealer_qualifies,
    decide,
    enumerate_dealer_outcomes,
)
from decision.evaluator import HandClass, parse_cards as cards


def c(text: str) -> list[int]:
    return parse_cards(text)


# --------------------------------------------------------------------------
# Deck helpers
# --------------------------------------------------------------------------


def test_full_deck_is_52_distinct_cards():
    deck = full_deck()
    assert len(deck) == 52
    assert len(set(deck)) == 52


def test_remaining_deck_strips_every_known_card():
    deck = remaining_deck(c("As Ks"), c("Qs Js Ts 2h 3d"))
    assert len(deck) == 52 - 2 - 5 == 45
    for known in c("As Ks Qs Js Ts 2h 3d"):
        assert known not in deck


# --------------------------------------------------------------------------
# Dealer qualification
# --------------------------------------------------------------------------


def test_dealer_qualifies_with_a_pair_or_better():
    assert dealer_qualifies(best_hand_rank(c("Ac Ad"), c("2h 5s 9d 3c 7h")))  # pair
    assert dealer_qualifies(best_hand_rank(c("Ac Ad"), c("Ah 5s 9d 3c 7h")))  # trips
    assert not dealer_qualifies(best_hand_rank(c("Ac Kd"), c("2h 5s 9d 3c 7h")))  # A-high


# --------------------------------------------------------------------------
# The enumeration itself
# --------------------------------------------------------------------------


def test_enumeration_covers_every_dealer_holding():
    counts = enumerate_dealer_outcomes(c("As Ks"), c("Qs Js Ts 2h 3d"))
    assert sum(counts.values()) == comb(45, 2) == 990


def test_the_qualification_split_is_structurally_one_sided():
    """A property of the game that falls out of the enumeration.

    You can never both beat a *qualifying* dealer and lose to a *non-qualifying*
    one, so at least one of those two buckets is always empty:

      * holding a pair or better, every non-qualifying dealer (high card) loses
        to you -> lose_unqualified is always 0;
      * holding high card only, every qualifying dealer (pair or better) beats
        you -> win_qualified is always 0.

    This is precisely why the win/push/lose triple is not enough. A high-card
    hand's wins all push the Ante, while a pair's wins all collect it -- a whole
    unit per win, on hands that a triple would describe identically.
    """
    high_card = enumerate_dealer_outcomes(c("Ah Kd"), c("Qc 9h 5s 3d 2c"))
    assert high_card["win_qualified"] == 0
    assert high_card["win_unqualified"] > 0

    pair_or_better = enumerate_dealer_outcomes(c("9h 9d"), c("Ks Qh Jd 9c 4s"))
    assert pair_or_better["win_qualified"] > 0
    assert pair_or_better["lose_unqualified"] == 0

    # And the "high card can lose to a non-qualifying dealer" half, which needs
    # a player hand weak enough for a bare high card to beat it.
    weak = enumerate_dealer_outcomes(c("7c 3d"), c("Ks Qh Jd 9c 4s"))
    assert weak["win_qualified"] == 0
    assert weak["lose_unqualified"] > 0


# --------------------------------------------------------------------------
# Analytic cases -- the numbers are known without running the code
# --------------------------------------------------------------------------


def test_royal_flush_can_never_lose_or_tie():
    """The nuts: every one of the 990 holdings is a win.

    No royal flush is possible for the dealer either, since all five spade
    honours are already in play.
    """
    d = decide(c("As Ks"), c("Qs Js Ts 2h 3d"))

    assert d.equity == 1.0
    assert d.tie_rate == 0.0
    assert d.outcomes.lose == 0.0
    assert d.player_hand == "Royal Flush"
    assert d.blind_multiplier == BLIND_ODDS[HandClass.ROYAL_FLUSH] == 500.0
    assert d.action is RiverAction.BET

    # EV is at least 1 (Ante) + 1 (Play) + 500 (Blind), plus the Ante again on
    # the qualifying-dealer wins. Never the full 502, since some dealers miss.
    assert 501.0 < d.ev_bet < 502.0
    assert d.breakeven is None, "can never lose, so there is no crossover point"


def test_a_board_royal_makes_every_holding_a_push():
    """The board is the nuts, so every dealer holding plays the same hand.

    The verdict is still BET: a guaranteed push is worth 0, while folding
    forfeits the two units already posted. This is the cleanest demonstration
    that the decision is not "will I win" but "is folding worse".
    """
    d = decide(c("2c 3d"), c("As Ks Qs Js Ts"))

    assert d.tie_rate == 1.0
    assert d.equity == 0.0
    assert d.outcomes.lose == 0.0
    assert d.ev_bet == pytest.approx(0.0)
    assert d.ev_fold == pytest.approx(-2.0)
    assert d.action is RiverAction.BET


def test_quads_losing_only_to_the_last_remaining_kicker_card():
    """Worked out by hand: hole 2c2d, board 2h2s3c3d3h.

    All four 2s are in play, so the player has quad twos. The dealer's best
    hand otherwise is the board's full house (threes full of twos), which quad
    twos beat. The dealer therefore wins if and only if they hold the last 3 --
    exactly 44 of the 990 holdings. Nothing ties.

    Every dealer holding is a full house or better, so the dealer always
    qualifies, and the Blind is the quads 10:1.
    """
    d = decide(c("2c 2d"), c("2h 2s 3c 3d 3h"))

    assert d.dealer_combos == 990
    assert d.outcomes.lose_qualified == pytest.approx(44 / 990)
    assert d.outcomes.lose_unqualified == 0.0
    assert d.equity == pytest.approx(946 / 990)
    assert d.tie_rate == 0.0
    assert d.blind_multiplier == 10.0
    assert d.action is RiverAction.BET

    # (946/990)(1+1+10) - (44/990)(1+1+1) = (11352 - 132)/990 = 34/3
    assert d.ev_bet == pytest.approx(34 / 3)
    assert d.ev_advantage == pytest.approx(34 / 3 + 2)


def test_playing_the_board_can_never_win():
    """Hole 2c3d on a K Q J 9 4 board: the player holds the board's high card.

    The dealer can only ever equal or beat K-Q-J-9-4, so the player never wins.
    A tie happens only when the dealer improves nothing at all, which needs the
    dealer to hold one deuce and one trey (the only ranks below the board's 4):
    3 remaining deuces x 3 remaining treys = 9 holdings out of 990.
    """
    d = decide(c("2c 3d"), c("Ks Qh Jd 9c 4s"))

    assert d.equity == 0.0
    assert d.tie_rate == pytest.approx(9 / 990)
    assert d.action is RiverAction.FOLD
    assert d.ev_bet < d.ev_fold
    assert d.breakeven is None, "can never win, so there is no crossover point"


def test_folding_is_correct_when_the_win_rate_is_far_below_the_threshold():
    """A hopeless river hand folds; the exact EV says so by a wide margin."""
    d = decide(c("7c 2d"), c("As Kh Qd 9c 4s"))
    assert d.equity < 0.10
    assert d.action is RiverAction.FOLD


# --------------------------------------------------------------------------
# Internal consistency
# --------------------------------------------------------------------------


def test_counts_and_probabilities_agree():
    hole, board = c("Ah Kd"), c("Qc 9h 5s 3d 2c")
    counts = enumerate_dealer_outcomes(hole, board)
    outcomes = Outcomes.from_counts(**counts)

    for bucket, count in counts.items():
        assert getattr(outcomes, bucket) == pytest.approx(count / 990)
    assert outcomes.total == pytest.approx(1.0)


@pytest.mark.parametrize(
    "hole,board",
    [
        ("Ah Kd", "Qc 9h 5s 3d 2c"),
        ("9h 9d", "Ks Qh Jd 9c 4s"),
        ("Ac 9c", "7c 5c 3c 2h 9d"),
        ("8h 9h", "Th Jh Qh 2c 3d"),
        ("Tc Td", "8h 5s 2d 3c 9d"),
    ],
)
def test_the_verdict_always_agrees_with_the_breakeven_threshold(hole, board):
    """Spec 3b frames the decision as equity vs threshold; it must match.

    The verdict is computed from the exact EV, and the threshold is the root of
    that same EV, so the two framings have to give identical answers on every
    hand where the threshold is measurable at all.
    """
    d = decide(c(hole), c(board))
    assert d.breakeven is not None
    assert (d.equity > d.breakeven) is (d.action is RiverAction.BET)


def test_decide_rejects_an_incomplete_board():
    with pytest.raises(ValueError, match="full 5-card board"):
        decide(c("Ah Kd"), c("Qc 9h 5s 3d"))


def test_decision_is_reproducible():
    """No sampling anywhere in this path -- identical inputs, identical output."""
    a = decide(c("Ah Kd"), c("Qc 9h 5s 3d 2c"))
    b = decide(c("Ah Kd"), c("Qc 9h 5s 3d 2c"))
    assert a == b
