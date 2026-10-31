"""Tests for decision/evaluator.py (spec 3a).

The point of these tests is to pin down the treys convention (lower score =
stronger hand) and to prove the C(7,5) brute force agrees with treys' own
native 7-card evaluation. If the convention were ever inverted, the river
enumeration would silently invert every decision rather than crash -- which is
exactly the failure mode worth spending tests on.
"""

from __future__ import annotations

import random

import pytest
from treys import Card, Evaluator

from decision.evaluator import (
    BEST_POSSIBLE_SCORE,
    WORST_POSSIBLE_SCORE,
    HandClass,
    best_hand_rank,
    describe,
    five_card_score,
    hand_class,
    hand_name,
    parse_cards,
)

NATIVE = Evaluator()


def score(hole: str, board: str) -> int:
    return best_hand_rank(parse_cards(hole), parse_cards(board))


# --------------------------------------------------------------------------
# The convention itself
# --------------------------------------------------------------------------


def test_lower_score_is_stronger_and_royal_flush_is_the_floor():
    royal = score("As Ks", "Qs Js Ts")
    worst = score("7c 5d", "4h 3s 2c")

    assert royal == BEST_POSSIBLE_SCORE == 1
    assert worst == WORST_POSSIBLE_SCORE == 7462
    assert royal < worst


def test_full_house_correctly_outranks_a_flush():
    """Explicitly called out in the build spec as the classic mix-up."""
    full_house = score("Kc Kd", "Kh 2s 2d")
    flush = score("Ac 9c", "7c 5c 3c")

    assert full_house < flush, "full house must score lower (i.e. beat) a flush"
    assert hand_class(full_house) is HandClass.FULL_HOUSE
    assert hand_class(flush) is HandClass.FLUSH


def test_hand_classes_are_strictly_ordered_by_score():
    """Walk the whole ladder top to bottom and assert monotonic ordering."""
    ladder = [
        (HandClass.ROYAL_FLUSH, score("As Ks", "Qs Js Ts")),
        (HandClass.STRAIGHT_FLUSH, score("9h 8h", "7h 6h 5h")),
        (HandClass.FOUR_OF_A_KIND, score("Ac Ad", "Ah As 2d")),
        (HandClass.FULL_HOUSE, score("Kc Kd", "Kh 2s 2d")),
        (HandClass.FLUSH, score("Ac 9c", "7c 5c 3c")),
        (HandClass.STRAIGHT, score("9c 8d", "7h 6s 5c")),
        (HandClass.THREE_OF_A_KIND, score("Qc Qd", "Qh 8s 2d")),
        (HandClass.TWO_PAIR, score("Jc Jd", "8h 8s 2d")),
        (HandClass.PAIR, score("Tc Td", "8h 5s 2d")),
        (HandClass.HIGH_CARD, score("Ac Kd", "8h 5s 2d")),
    ]

    for expected_class, s in ladder:
        assert hand_class(s) is expected_class, f"{hand_name(s)} != {expected_class.name}"

    scores = [s for _, s in ladder]
    assert scores == sorted(scores), "scores must strictly increase down the ladder"
    assert len(set(scores)) == len(scores)


# --------------------------------------------------------------------------
# Specific 7-card hands
# --------------------------------------------------------------------------


def test_specific_seven_card_hands():
    # Royal flush made entirely from the board's suit.
    assert describe(parse_cards("As Ks"), parse_cards("Qs Js Ts 2h 3d")) == "Royal Flush (score 1)"

    # Quads plus a pair on board: quads is the best five, not the full house.
    assert hand_class(score("Ac Ad", "Ah As Kd Kc")) is HandClass.FOUR_OF_A_KIND

    # Board pairs twice, hole pairs the board's top card -> full house.
    assert hand_class(score("7c 7d", "7h 2c 2d Ks Qh")) is HandClass.FULL_HOUSE

    # Straight flush, not a royal: the 8-high end of the same suit run.
    assert hand_class(score("8h 9h", "Th Jh Qh 2c 3d")) is HandClass.STRAIGHT_FLUSH

    # Ace-low ("wheel") straight must be a straight, and must lose to a 6-high
    # straight -- the ace is low here, not high.
    wheel = score("Ah 2d", "3c 4s 5h Kd Qc")
    six_high = score("6h 2d", "3c 4s 5h Kd Qc")
    assert hand_class(wheel) is HandClass.STRAIGHT
    assert wheel > six_high, "A-2-3-4-5 is the weakest straight, below 2-3-4-5-6"


def test_best_five_of_seven_is_chosen_not_the_first_five():
    """A made flush on board must lose to the hole cards' full house."""
    board = "2h 2s 2d 9c 9h"
    quads = score("2c 7d", board)
    assert hand_class(quads) is HandClass.FOUR_OF_A_KIND

    # Hole cards that are irrelevant to the best five must not change it:
    # the royal flush is already entirely on the board.
    royal_on_board = "As Ks Qs Js Ts"
    assert score("2c 3d", royal_on_board) == 1
    assert score("7h 8h", royal_on_board) == 1
    assert score("2c 3d", royal_on_board) == score("7h 8h", royal_on_board)


def test_ties_produce_identical_scores():
    """Equal ranks in different suits must tie exactly (UTH pushes on a tie)."""
    a = five_card_score(parse_cards("Ac Ad Kc Kd 2h"))
    b = five_card_score(parse_cards("As Ah Ks Kh 2c"))
    assert a == b

    assert score("As Ks", "Qs Js Ts 2h 3d") == score("Ah Kh", "Qh Jh Th 2c 3d")


# --------------------------------------------------------------------------
# The brute force agrees with treys' native evaluator
# --------------------------------------------------------------------------


def test_brute_force_matches_treys_native_seven_card_evaluation():
    """Randomised cross-check of the 21-subset loop against treys itself.

    This is the load-bearing test for spec 3a: if the subset enumeration ever
    picked the wrong side of the comparison, this would catch it across a wide
    spread of hand types instead of only the hand-written cases above.
    """
    rng = random.Random(20261029)
    deck = [Card.new(r + s) for r in "23456789TJQKA" for s in "shdc"]

    for _ in range(2000):
        cards = rng.sample(deck, 7)
        hole, board = cards[:2], cards[2:]

        assert best_hand_rank(hole, board) == NATIVE.evaluate(list(hole), list(board))


def test_exhaustive_five_card_scores_are_valid_range():
    """Every 5-card subset score must land inside treys' documented range."""
    deck = [Card.new(r + s) for r in "23456789TJQKA" for s in "shdc"]
    for i in range(0, 48, 7):  # a cheap spread, not an exhaustive C(52,5) sweep
        s = five_card_score(deck[i : i + 5])
        assert BEST_POSSIBLE_SCORE <= s <= WORST_POSSIBLE_SCORE


# --------------------------------------------------------------------------
# Input handling
# --------------------------------------------------------------------------


def test_supports_five_and_six_card_inputs():
    """Flop (2+3) and turn (2+4) states must evaluate, not just the river."""
    assert hand_class(score("As Ks", "Qs Js Ts")) is HandClass.ROYAL_FLUSH
    assert hand_class(score("As Ks", "Qs Js Ts 2h")) is HandClass.ROYAL_FLUSH


def test_rejects_fewer_than_five_cards():
    with pytest.raises(ValueError, match="at least 5 cards"):
        best_hand_rank(parse_cards("As Ks"), [])

    with pytest.raises(ValueError, match="exactly 5 cards"):
        five_card_score(parse_cards("As Ks Qs Js"))


def test_parse_cards_rejects_malformed_input():
    with pytest.raises(KeyError):
        parse_cards("Xs")
