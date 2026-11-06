"""Tests for decision/preflop.py (spec 3d).

Two halves, tested for different things.

The **canonicaliser** has nothing to compute, but it has an equivalence
relation to get right, and a wrong one would mislabel every row of the table in
a way no downstream test could see. Those tests are structural: sweep all
C(52,2) = 1,326 holdings and check they partition into exactly the 169 classes
with the multiplicities suit symmetry demands.

**decide()** is a lookup, so its tests cover the two things a lookup can get
wrong -- reading the wrong row (every class is decided and must report its own
label), and disagreeing with the row it read (the verdict must be that row's
own EV comparison). Plus the loader's own contract: lazy, cached, and loud
about a malformed table.

Both halves are cheap -- 1,326 canonicalisations and 169 dictionary reads -- so
these are exact assertions rather than tolerances.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from itertools import combinations

import pytest

from decision import preflop
from decision.evaluator import full_deck, parse_cards
from decision.preflop import (
    DEFAULT_TABLE_PATH,
    PREFLOP_PLAY_MULTIPLIER,
    STARTING_HAND_CLASS_COUNT,
    PreflopAction,
    PreflopDecision,
    clear_table_cache,
    decide,
    load_table,
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


# --------------------------------------------------------------------------
# decide(): the lookup (spec 3d)
# --------------------------------------------------------------------------


def holding_for(label: str) -> list[int]:
    """A concrete two-card holding that canonicalises to ``label``.

    Pairs get one suit each, suited hands share a suit, offsuit hands do not.
    The round trip is asserted in
    :func:`test_every_class_decides_and_reports_its_own_label`, so a label list
    that drifted could not quietly test the wrong row.
    """
    high, low = label[0], label[1]
    if len(label) == 2:
        return c(f"{high}s {low}h")
    return c(f"{high}s {low}{'s' if label.endswith('s') else 'h'}")


@pytest.fixture(autouse=True)
def _fresh_table_cache():
    """The loader caches by path; keep tests from seeing each other's tables."""
    clear_table_cache()
    yield
    clear_table_cache()


@pytest.fixture(scope="module")
def decisions() -> dict[str, PreflopDecision]:
    """One decision per class. A dictionary read each, so: milliseconds."""
    return {label: decide(holding_for(label)) for label in starting_hand_classes()}


def test_every_class_decides_and_reports_its_own_label(decisions):
    assert len(decisions) == STARTING_HAND_CLASS_COUNT
    for label, decision in decisions.items():
        assert starting_hand_class(holding_for(label)) == label
        assert decision.hand_class == label


def test_the_verdict_is_the_stored_ev_comparison(decisions):
    """BET exactly when betting beats checking -- no separate rule to drift."""
    for label, decision in decisions.items():
        expected = (
            PreflopAction.BET
            if decision.ev_bet > decision.ev_check
            else PreflopAction.CHECK
        )
        assert decision.action is expected, label
        assert decision.ev_advantage == pytest.approx(
            decision.ev_bet - decision.ev_check
        )
        assert decision.multiplier == PREFLOP_PLAY_MULTIPLIER


def test_the_lookup_reproduces_the_row_it_read(decisions):
    """decide() must add no maths of its own beyond the EV comparison."""
    rows = load_table()["classes"]
    for label, decision in decisions.items():
        row = rows[label]
        assert decision.ev_check == pytest.approx(row["check_value"])
        assert decision.blind_multiplier == pytest.approx(row["blind_multiplier"])
        assert decision.check_value_se == pytest.approx(row["check_value_se"])
        assert decision.trials == row["trials"]
        assert decision.boards == row["boards"]
        assert decision.outcomes.total == pytest.approx(1.0)
        assert math.isfinite(decision.ev_bet)
        assert math.isfinite(decision.ev_check)


def test_both_actions_actually_occur(decisions):
    """A table that made everything check (or everything bet) would be a bug the
    per-class assertions above could not see."""
    counts = Counter(d.action for d in decisions.values())
    assert counts[PreflopAction.BET] > 0
    assert counts[PreflopAction.CHECK] > 0


def test_the_resolvable_flag_tracks_the_margin_against_the_baseline_se(decisions):
    for decision in decisions.values():
        assert decision.resolvable == (
            abs(decision.ev_advantage) > decision.check_value_se
        )


def test_every_decision_summarises_without_error(decisions):
    for decision in decisions.values():
        assert decision.hand_class in decision.summary()


# --- reference verdicts (anchors against the committed table) ---


def test_reference_verdicts():
    """The extremes must land where the hand chart says they do."""
    assert decide(c("As Ah")).action is PreflopAction.BET
    assert decide(c("7c 2d")).action is PreflopAction.CHECK
    assert decide(c("3h 2d")).action is PreflopAction.CHECK


def test_the_pairs_bet_down_to_threes_and_deuces_check(decisions):
    """Where the pair range ends is a fact about *this* table, not a rule of
    poker -- anchored so a regenerated table cannot move it unnoticed."""
    for label in ["AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33"]:
        assert decisions[label].action is PreflopAction.BET, label
    assert decisions["22"].action is PreflopAction.CHECK


def test_a_holding_decides_the_same_however_its_suits_fall():
    """The whole point of the 169 classes: which suits you hold must not matter."""
    suited = [c("As Ks"), c("Ah Kh"), c("Ad Kd"), c("Ac Kc")]
    assert {decide(h).hand_class for h in suited} == {"AKs"}
    assert len({decide(h).action for h in suited}) == 1

    offsuit = [c("As Kh"), c("Ah Ks"), c("Ad Kc"), c("Ac Kd")]
    assert {decide(h).hand_class for h in offsuit} == {"AKo"}
    assert len({decide(h).action for h in offsuit}) == 1


# --------------------------------------------------------------------------
# The table loader: lazy, cached, and loud about a bad table
# --------------------------------------------------------------------------


def test_the_default_path_is_the_committed_table():
    assert DEFAULT_TABLE_PATH.is_file()
    assert DEFAULT_TABLE_PATH.name == "preflop_table.json"


def test_the_table_is_not_read_until_a_decision_is_made(monkeypatch, tmp_path):
    """Importing preflop must not need the table.

    The generator imports :func:`starting_hand_class` from this module and is
    what *creates* the table, so a load at import time would break the very run
    that produces it -- and would do so only on a clean checkout, which is the
    worst moment to find out.
    """
    monkeypatch.setattr(preflop, "DEFAULT_TABLE_PATH", tmp_path / "absent.json")

    assert starting_hand_class(c("As Ks")) == "AKs"
    assert preflop._TABLE_CACHE == {}

    with pytest.raises(FileNotFoundError):
        decide(c("As Ks"))


def test_the_table_is_parsed_once_per_path():
    assert load_table() is load_table()


def test_a_missing_table_raises_rather_than_deciding_on_nothing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_table(tmp_path / "nope.json")


def test_it_rejects_a_table_with_a_class_missing(tmp_path):
    table = json.loads(DEFAULT_TABLE_PATH.read_text())
    del table["classes"]["AA"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(table))
    with pytest.raises(ValueError, match="class mismatch"):
        load_table(bad)


def test_it_rejects_a_row_with_a_field_missing(tmp_path):
    table = json.loads(DEFAULT_TABLE_PATH.read_text())
    del table["classes"]["AA"]["check_value"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(table))
    with pytest.raises(ValueError, match="missing"):
        load_table(bad)