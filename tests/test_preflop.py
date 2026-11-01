"""Tests for decision/preflop.py (spec 3d, canonicalisation half).

Unlike the other modules there is nothing to compute here -- but there is an
equivalence relation to get right, and a wrong one would mislabel every row of
the pre-flop table in a way no downstream test could see. So the tests are
structural: sweep all C(52,2) = 1,326 holdings and check that they partition
into exactly the 169 classes, with the multiplicities suit symmetry demands.

The sweep is cheap (1,326 holdings, no scoring), so these are all exact
assertions rather than tolerances.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations

import pytest

from decision.evaluator import full_deck, parse_cards
from decision.preflop import (
    STARTING_HAND_CLASS_COUNT,
    starting_hand_class,
    starting_hand_classes,
)
from treys import Card


def c(text: str) -> list[int]:
    return parse_cards(text)


def suit_of(card: int) -> int:
    """The suit *bit* treys assigns (1=s, 2=h, 4=d, 8=c).

    Note this is a power of two, not a 0..3 index -- treys encodes suits as bits
    so it can test flush membership with a single AND. Comparing two cards'
    ``suit_of`` values is still an exact same-suit test.
    """
    return Card.get_suit_int(card)


def expected_multiplicity(label: str) -> int:
    """How many concrete holdings this class must cover, from its own label.

    Pairs have 6 suit assignments (C(4,2)), suited hands 4 (one per suit), and
    offsuit hands 12 (4 x 3 ordered suit pairs).
    """
    if len(label) == 2:
        return 6
    return 4 if label.endswith("s") else 12


def class_sweep() -> dict[str, list[list[int]]]:
    """Every holding, grouped by the class it canonicalises to."""
    grouped: dict[str, list[list[int]]] = {}
    for holding in combinations(full_deck(), 2):
        grouped.setdefault(starting_hand_class(holding), []).append(list(holding))
    return grouped


@pytest.fixture(scope="module")
def sweep() -> dict[str, list[list[int]]]:
    return class_sweep()


# --------------------------------------------------------------------------
# The label convention
# --------------------------------------------------------------------------


def test_holdings_canonicalise_to_their_chart_labels():
    assert starting_hand_class(c("As Ks")) == "AKs"
    assert starting_hand_class(c("As Kh")) == "AKo"
    assert starting_hand_class(c("3h 3d")) == "33"
    assert starting_hand_class(c("Td 9d")) == "T9s"
    assert starting_hand_class(c("7c 2d")) == "72o"


def test_the_higher_rank_is_written_first():
    """Both orders of the same holding must give the same label."""
    assert starting_hand_class(c("Ks As")) == "AKs"
    assert starting_hand_class(c("2d 7c")) == "72o"
    # The ace is high in the label even though it is low in a wheel straight --
    # labels describe the holding, not any hand it might make.
    assert starting_hand_class(c("5h Ad")) == "A5o"


def test_suitedness_is_decided_by_the_suits_not_the_ranks():
    assert starting_hand_class(c("As Ks")) == "AKs"
    assert starting_hand_class(c("As Kh")) == "AKo"
    assert starting_hand_class(c("Kh Ks")) == "KK", "a pair is its own class"


# --------------------------------------------------------------------------
# The partition: 1,326 holdings -> 169 classes
# --------------------------------------------------------------------------


def test_every_holding_lands_in_exactly_one_of_169_classes(sweep):
    assert len(sweep) == STARTING_HAND_CLASS_COUNT
    assert sum(len(v) for v in sweep.values()) == 1326


def test_classes_cover_the_multiplicities_suit_symmetry_demands(sweep):
    """Each class must cover exactly the holdings its label implies -- no more.

    A class that swallowed too few holdings would mean two classes for one hand;
    too many would mean it swallowed a neighbouring class. Either way the table
    would have a row that describes something other than what its key says.
    """
    for label, holdings in sweep.items():
        assert len(holdings) == expected_multiplicity(label), label

    by_kind = Counter("pair" if len(label) == 2 else label[-1] for label in sweep)
    assert by_kind == Counter({"pair": 13, "s": 78, "o": 78})


def test_no_two_classes_share_a_holding(sweep):
    """The classes must partition, not merely cover -- no holding in two of them."""
    all_holdings = [tuple(h) for holdings in sweep.values() for h in holdings]
    assert len(all_holdings) == len(set(all_holdings)) == 1326


def test_a_class_ignores_the_specific_suits_but_not_the_match(sweep):
    """Every holding in one class is the same hand up to relabelling suits."""
    assert len(sweep["AKs"]) == 4
    assert len(sweep["AKo"]) == 12
    assert len(sweep["AA"]) == 6

    for holding in sweep["AKs"]:
        assert len({suit_of(h) for h in holding}) == 1, "suited means one suit"
    for holding in sweep["AKo"]:
        assert len({suit_of(h) for h in holding}) == 2, "offsuit means two suits"


# --------------------------------------------------------------------------
# The listed order the table is written in
# --------------------------------------------------------------------------


def test_the_class_list_is_complete_and_unique():
    classes = starting_hand_classes()
    assert len(classes) == STARTING_HAND_CLASS_COUNT
    assert len(set(classes)) == STARTING_HAND_CLASS_COUNT


def test_the_class_list_agrees_with_the_sweep(sweep):
    """The listed order and the canonicalisation must describe the same 169."""
    assert set(starting_hand_classes()) == set(sweep)


def test_the_class_list_runs_pairs_then_suited_then_offsuit():
    classes = starting_hand_classes()
    assert classes[:13] == ["AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22"]
    assert classes[13] == "AKs" and classes[13 + 78 - 1] == "32s"
    assert classes[13 + 78] == "AKo" and classes[-1] == "32o"


def test_the_class_list_is_the_strongest_first_within_each_group():
    classes = starting_hand_classes()
    suited = classes[13 : 13 + 78]
    assert suited[:4] == ["AKs", "AQs", "AJs", "ATs"]
    # The ace's row is the widest: every lower rank, strongest first ...
    assert suited[11] == "A2s"
    # ... and the row after it starts at King, not back at Ace.
    assert suited[12:14] == ["KQs", "KJs"]


# --------------------------------------------------------------------------
# Bad input
# --------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["As", "As Ks Qs", ""])
def test_it_rejects_a_holding_that_is_not_two_cards(text):
    with pytest.raises(ValueError, match="exactly 2 cards"):
        starting_hand_class(c(text))


def test_it_rejects_the_same_card_twice():
    card = c("As")
    with pytest.raises(ValueError, match="same card twice"):
        starting_hand_class(card + card)