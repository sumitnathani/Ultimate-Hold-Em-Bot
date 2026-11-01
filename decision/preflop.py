"""Pre-flop decision by lookup table (spec 3d).

Pre-flop there is no board -- only the two hole cards -- so there is nothing to
enumerate and nothing to sample at decision time. Spec 3d's answer is to move
all the work offline: a separate tool simulates every starting-hand class once,
writes the results to a JSON table, and the runtime decision becomes a
dictionary lookup.

WHAT THIS MODULE HOLDS SO FAR
-----------------------------
Only the canonicalisation half of that: mapping an arbitrary two-card holding
onto one of :data:`STARTING_HAND_CLASS_COUNT` classes. That is the part the
offline generator and the runtime lookup must agree on *exactly* -- if they
disagree about what a key means, the table's rows are silently mislabelled --
so it is built and tested first. ``decide()`` lands once the table it reads
exists, since it cannot be meaningfully tested before then.

SUIT SYMMETRY: C(52, 2) = 1,326 HOLDINGS, 169 CLASSES
------------------------------------------------------
Which two suits you hold does not change how the hand plays; only whether the
two cards *share* a suit does. So the 1,326 distinct holdings collapse into 169:

    13 pairs      two cards of one rank
    78 suited     two different ranks in the same suit   (4 holdings each)
    78 offsuit    two different ranks in other suits     (12 holdings each)

A pair is never "suited": a deck holds one card per rank *and* suit, so two
cards of the same rank must differ in suit. That is why pairs form their own
class instead of joining the suited or offsuit ones.

THE LABEL CONVENTION: ``"AKs"``, ``"72o"``, ``"33"``
-----------------------------------------------------
The higher rank is written first, and a suffix says whether the suits match:
``s`` for suited, ``o`` for offsuit. Pairs carry no suffix, because every pair
is the same class however its suits fall. Rank characters come from
:data:`decision.evaluator.RANKS`, which is also the order ``treys`` numbers
ranks in, so the label ordering and the score ordering cannot drift apart.

These labels are the table's keys. ``"AKs"`` and ``"KsAs"`` are one key, and so
are ``"As Kh"`` and ``"Ah Ks"`` -- see :func:`starting_hand_class`.
"""

from __future__ import annotations

from typing import Sequence

from treys import Card

from decision.evaluator import RANKS

__all__ = [
    "STARTING_HAND_CLASS_COUNT",
    "starting_hand_class",
    "starting_hand_classes",
]

#: 13 pairs + 78 suited + 78 offsuit. Named so the generator and the tests can
#: assert completeness without re-deriving the arithmetic.
STARTING_HAND_CLASS_COUNT = 169

_SUITED = "s"
_OFFSUIT = "o"


def starting_hand_class(hole: Sequence[int]) -> str:
    """Canonical class label for a two-card holding.

    ``"As Ks"`` -> ``"AKs"``, ``"7c 2d"`` -> ``"72o"``, ``"3h 3d"`` -> ``"33"``.

    Order-insensitive and suit-insensitive, which is the whole point: it is the
    equivalence relation that makes the 1,326 holdings addressable as 169 table
    rows. Both cards must be treys ints (see
    :func:`decision.evaluator.parse_cards`).

    Raises ``ValueError`` for anything that is not exactly two distinct cards --
    a one-card "hand" has no class, and repeating a card is a caller bug that
    would otherwise canonicalise into a plausible-looking label.
    """
    if len(hole) != 2:
        raise ValueError(f"a starting hand is exactly 2 cards, got {len(hole)}")
    first, second = hole
    if first == second:
        raise ValueError("a starting hand cannot contain the same card twice")

    # Highest rank first, so the label matches how the class is written down.
    high, low = sorted((first, second), key=Card.get_rank_int, reverse=True)
    high_char, low_char = RANKS[Card.get_rank_int(high)], RANKS[Card.get_rank_int(low)]

    if high_char == low_char:  # a pair: same rank, necessarily different suits
        return high_char + low_char

    suited = Card.get_suit_int(high) == Card.get_suit_int(low)
    return high_char + low_char + (_SUITED if suited else _OFFSUIT)


def starting_hand_classes() -> list[str]:
    """Every class label, in a fixed order: pairs, then suited, then offsuit.

    Each group runs from the strongest holding down (``AA``, ``KK``, ... then
    ``AKs``, ``AQs``, ...), so the list is readable as a hand chart and stable
    for the generator, which writes the table in this order. A table whose row
    order changes between runs is a table nobody can diff.
    """
    descending = RANKS[::-1]  # "AKQJT98765432"
    classes = [rank + rank for rank in descending]
    for suffix in (_SUITED, _OFFSUIT):
        for index, high in enumerate(descending):
            classes.extend(high + low + suffix for low in descending[index + 1 :])
    return classes