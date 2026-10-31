"""Hand ranking for the Ultimate Texas Hold'em decision engine (spec 3a).

This module is the foundation everything else stands on: the river enumeration,
the flop Monte Carlo, and the pre-flop table generator all reduce to "how strong
is this 7-card holding?", so the ranking convention has to be nailed down once,
here, and never re-derived downstream.

THE TREYS CONVENTION (this is the thing that trips people up)
------------------------------------------------------------
``treys`` scores a hand with a single integer, and **LOWER IS BETTER**.

    1     = royal flush   (the strongest possible 5-card hand)
    7462  = 7-5-4-3-2 offsuit (the weakest possible 5-card hand)

So a *comparison* reads: ``score_a < score_b`` means hand A beats hand B, and
``score_a == score_b`` means the two hands tie (which in Ultimate Texas Hold'em
is a push, not a win for either side). Every module in ``decision/`` inherits
this convention -- when you see ``min(...)`` over scores, that is "best hand",
not "worst hand".

Only 5-card hands have a defined score. For a 7-card holding (2 hole + 5 board)
we brute-force all C(7,5) = 21 five-card subsets and keep the lowest score, per
spec 3a. The function generalises to any 5..7 card input, which is what lets the
flop sampler evaluate the 5-card flop state as well as 7-card runouts.
"""

from __future__ import annotations

from enum import IntEnum
from itertools import combinations
from typing import Iterable, Sequence

from treys import Card, Evaluator

__all__ = [
    "HandClass",
    "BEST_POSSIBLE_SCORE",
    "WORST_POSSIBLE_SCORE",
    "parse_cards",
    "five_card_score",
    "best_hand_rank",
    "hand_class",
    "hand_name",
    "describe",
]

# One shared evaluator. treys builds a large lookup table in __init__, so
# constructing this per-call would dominate the runtime of the Monte Carlo
# loops. Treat it as a module-level singleton.
_EVALUATOR = Evaluator()

# treys' score range, documented here so downstream modules can write
# assertions against named constants instead of magic numbers.
BEST_POSSIBLE_SCORE = 1  # royal flush
WORST_POSSIBLE_SCORE = 7462  # 7-5-4-3-2 offsuit


class HandClass(IntEnum):
    """treys' 0..9 hand categories, in descending strength.

    Note the ordering is *descending* strength with *ascending* integer value,
    matching treys' rank-class numbering (0 is the best). Do not confuse this
    with the score: a HandClass of 3 (full house) is stronger than a HandClass
    of 4 (flush), but the full house's *score* is the lower number.
    """

    ROYAL_FLUSH = 0
    STRAIGHT_FLUSH = 1
    FOUR_OF_A_KIND = 2
    FULL_HOUSE = 3
    FLUSH = 4
    STRAIGHT = 5
    THREE_OF_A_KIND = 6
    TWO_PAIR = 7
    PAIR = 8
    HIGH_CARD = 9


def parse_cards(text: str | Iterable[str]) -> list[int]:
    """Turn ``"As Ks"`` (or ``["As", "Ks"]``) into treys card integers.

    Convenience for callers and tests that would rather not import treys just
    to build a card list. ``Card.new`` raises ``KeyError`` on anything that is
    not a rank+suit string, which is the behaviour we want -- silently skipping
    a malformed card would corrupt an enumeration without any visible symptom.
    """
    tokens = text.split() if isinstance(text, str) else list(text)
    return [Card.new(tok) for tok in tokens]


def five_card_score(cards: Sequence[int]) -> int:
    """Score exactly five cards. Lower is better (see module docstring)."""
    if len(cards) != 5:
        raise ValueError(f"five_card_score needs exactly 5 cards, got {len(cards)}")
    return _EVALUATOR.evaluate(list(cards), [])


def best_hand_rank(hole: Sequence[int], board: Sequence[int]) -> int:
    """Best 5-card score available from ``hole + board``.

    Lower score = stronger hand. ``hole`` and ``board`` are treys card ints
    (see :func:`parse_cards`); together they must total 5 to 7 cards.

    For the full 7-card case this is the spec-3a brute force: enumerate all
    C(7,5) = 21 subsets and keep the minimum score. ``treys`` can do this
    internally in one call, but the spec asks for the explicit subset loop, and
    keeping it explicit means the 5-card flop case (2 hole + 3 board) and the
    6-card turn case flow through the identical code path with no special
    casing.

    Raises ``ValueError`` if fewer than 5 cards are supplied -- there is no
    meaningful hand rank for a pre-flop holding, and quietly returning a
    sentinel would let a caller silently treat "no hand yet" as "worst hand".
    """
    cards = list(hole) + list(board)
    if len(cards) < 5:
        raise ValueError(
            f"best_hand_rank needs at least 5 cards (hole + board), got {len(cards)}"
        )

    best = None
    for combo in combinations(cards, 5):
        score = _EVALUATOR.evaluate(list(combo), [])
        if best is None or score < best:
            best = score
    # combinations() over >=5 cards always yields at least one tuple, so `best`
    # is guaranteed to be an int here.
    return best  # type: ignore[return-value]


def hand_class(score: int) -> HandClass:
    """Map a treys score to its :class:`HandClass` category."""
    return HandClass(_EVALUATOR.get_rank_class(score))


def hand_name(score: int) -> str:
    """Human-readable name for a treys score, e.g. ``"Full House"``."""
    return _EVALUATOR.class_to_string(_EVALUATOR.get_rank_class(score))


def describe(hole: Sequence[int], board: Sequence[int]) -> str:
    """Debug helper: ``"Full House (score 190)"`` for a holding."""
    score = best_hand_rank(hole, board)
    return f"{hand_name(score)} (score {score})"
