"""Tests for tools/generate_preflop_table.py (spec 3d).

The generator's real run is ~3.5h, so these exercise it at toy sample sizes: a
few thousand trials and a few dozen boards. What is being tested here is not the
accuracy of the numbers -- that is what the sample sizes buy -- but the things a
long unattended run can get silently wrong: the class a row belongs to, whether
a resumed run reproduces a from-scratch one, and whether an interrupted write
can corrupt the table.
"""

from __future__ import annotations

import json
from itertools import combinations

import pytest

from decision.evaluator import full_deck, parse_cards
from decision.preflop import STARTING_HAND_CLASS_COUNT, starting_hand_class
from decision.ev import BUCKETS, ev_of_fold
from tools.generate_preflop_table import (
    class_seed,
    load_table,
    main,
    representative_holdings,
    sample_check_value,
    sample_rates,
)

#: Toy settings, small enough that the whole file runs in seconds.
TRIALS = 3_000
BOARDS = 60


def c(text: str) -> list[int]:
    return parse_cards(text)


@pytest.fixture(scope="module")
def representatives() -> dict[str, list[int]]:
    return representative_holdings()


# --------------------------------------------------------------------------
# Representatives: one concrete holding per class, found by sweeping
# --------------------------------------------------------------------------


def test_there_is_exactly_one_representative_per_class(representatives):
    assert len(representatives) == STARTING_HAND_CLASS_COUNT


def test_every_representative_canonicalises_back_to_its_own_key(representatives):
    """The sweep's guarantee, restated: the key and the cards must agree."""
    for label, holding in representatives.items():
        assert starting_hand_class(holding) == label
        assert len(holding) == 2
        assert holding[0] != holding[1]
        assert set(holding) <= set(full_deck())


def test_the_representatives_are_the_first_holding_the_sweep_meets(representatives):
    """Deterministic, so a row can always be traced back to the cards that made it."""
    for label, holding in representatives.items():
        for candidate in combinations(full_deck(), 2):
            if starting_hand_class(candidate) == label:
                assert list(candidate) == holding, label
                break
        else:  # pragma: no cover - the sweep already proved every class is hit
            raise AssertionError(f"the sweep never produced {label}")


# --------------------------------------------------------------------------
# Seeding: reproducible per class, and independent of the run's shape
# --------------------------------------------------------------------------


def test_a_class_seed_is_stable_and_distinct():
    assert class_seed(7, "AKs", "rates") == class_seed(7, "AKs", "rates")
    # Different classes and different loops must not collide, or the two loops
    # would draw identical streams and the "independent samples" claim is false.
    seeds = {
        class_seed(7, label, loop)
        for label in ("AKs", "AKo", "AA", "72o")
        for loop in ("rates", "baseline")
    }
    assert len(seeds) == 8
    # Consecutive labels must not get consecutive seeds (seed + index would).
    assert class_seed(7, "AKs", "rates") - class_seed(7, "AQs", "rates") != 1


def test_a_class_measures_the_same_alone_as_in_a_batch(tmp_path):
    """The property checkpointing and resume depend on.

    With one shared RNG stream, measuring ``AKs`` after ``AA`` would give a
    different answer than measuring it alone -- so a resumed table would not
    equal a from-scratch one.
    """
    solo, batched = tmp_path / "solo.json", tmp_path / "batched.json"
    common = ["--seed", "11", "--trials", str(TRIALS), "--boards", str(BOARDS)]

    main(["--output", str(solo), "--classes", "AKs", *common, "--quiet"])
    main(["--output", str(batched), "--classes", "AA", "AKs", "72o", *common, "--quiet"])

    assert (
        load_table(solo)["classes"]["AKs"] == load_table(batched)["classes"]["AKs"]
    )


# --------------------------------------------------------------------------
# The two loops
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["AA", "AKs", "72o"])
def test_the_rates_loop_accounts_for_every_trial(label, representatives):
    measured = sample_rates(representatives[label], TRIALS, class_seed(0, label, "rates"))
    assert sum(measured["counts"].values()) == TRIALS
    assert sorted(measured["counts"]) == sorted(BUCKETS)
    assert measured["wins"] == (
        measured["counts"]["win_qualified"] + measured["counts"]["win_unqualified"]
    )
    # The Blind multiplier is a payout average, so it must sit inside the
    # paytable: never negative, never past the 500:1 royal.
    assert 0.0 <= measured["blind_multiplier"] <= 500.0


def test_a_better_hand_wins_at_least_as_often(representatives):
    """A coarse ordering check -- AA must out-win 72o by a mile, not by a coin."""
    aa = sample_rates(representatives["AA"], 20_000, class_seed(0, "AA", "rates"))
    weak = sample_rates(representatives["72o"], 20_000, class_seed(0, "72o", "rates"))
    assert aa["wins"] / aa["trials"] > 0.75
    assert weak["wins"] / weak["trials"] < 0.45


@pytest.mark.parametrize("label", ["AA", "72o"])
def test_checking_can_never_be_worse_than_folding(label, representatives):
    """The baseline has a floor, and it is -2: folding stays available on the river.

    If this ever fails, the board-averaged baseline is pricing something other
    than "check and then play the river optimally".
    """
    measured = sample_check_value(representatives[label], BOARDS, class_seed(0, label, "baseline"))
    assert measured["check_value"] >= ev_of_fold()
    # And it cannot exceed a hand that wins the maximum on every board.
    assert measured["check_value"] <= 503.0
    assert measured["boards"] == BOARDS
    assert measured["check_value_se"] >= 0.0


# --------------------------------------------------------------------------
# Checkpointing and resume
# --------------------------------------------------------------------------


def test_a_second_run_does_no_work(tmp_path, capsys):
    out = tmp_path / "t.json"
    argv = [
        "--output", str(out), "--classes", "AA", "AKs",
        "--trials", str(TRIALS), "--boards", str(BOARDS),
    ]
    main([*argv, "--quiet"])
    first = load_table(out)

    main([*argv, "--quiet"])
    assert load_table(out) == first
    assert "2 measured, 0 already current" in capsys.readouterr().out

    main([*argv, "--quiet"])
    assert "0 measured, 2 already current" in capsys.readouterr().out


def test_a_completed_class_survives_an_interrupted_run(tmp_path):
    """A run killed mid-way must leave the classes it finished intact."""
    partial = tmp_path / "t.json"
    partial.write_text(
        json.dumps(
            {
                "meta": {"version": 1},
                "classes": {"AA": {"trials": TRIALS, "counts": dict.fromkeys(BUCKETS, 1)}},
            }
        ),
        encoding="utf-8",
    )
    main(
        [
            "--output", str(partial), "--classes", "AA", "AKs",
            "--trials", str(TRIALS), "--boards", str(BOARDS), "--quiet",
        ]
    )
    table = load_table(partial)
    assert table["classes"]["AA"]["counts"] == dict.fromkeys(BUCKETS, 1)  # untouched
    assert "AA" not in table["classes"]["AA"]  # no nesting crept in
    assert "classes" not in table["meta"]
    assert sum(table["classes"]["AKs"]["counts"].values()) == TRIALS


def test_a_denser_baseline_run_keeps_the_rates(tmp_path):
    """Tier 2 re-measures the baseline without redoing 2,000,000 trials."""
    out = tmp_path / "t.json"
    main(
        [
            "--output", str(out), "--classes", "AKs", "--trials", str(TRIALS),
            "--boards", str(BOARDS), "--quiet",
        ]
    )
    before = load_table(out)["classes"]["AKs"]

    main(
        [
            "--output", str(out), "--classes", "AKs", "--baseline-only",
            "--boards", str(BOARDS * 2), "--quiet",
        ]
    )
    after = load_table(out)["classes"]["AKs"]

    assert after["counts"] == before["counts"]
    assert after["blind_multiplier"] == before["blind_multiplier"]
    assert after["boards"] == BOARDS * 2


def test_the_table_records_the_cards_behind_every_row(tmp_path):
    out = tmp_path / "t.json"
    main(["--output", str(out), "--classes", "AKs", "--trials", "10", "--boards", "3", "--quiet"])
    reps = load_table(out)["meta"]["representatives"]
    assert len(reps) == STARTING_HAND_CLASS_COUNT
    assert starting_hand_class(c(reps["AKs"])) == "AKs"
    assert starting_hand_class(c(reps["72o"])) == "72o"


# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------


def test_it_refuses_a_label_that_is_not_a_starting_hand(tmp_path):
    with pytest.raises(SystemExit, match="not starting-hand classes"):
        main(["--output", str(tmp_path / "t.json"), "--classes", "AKx", "--quiet"])


def test_it_refuses_two_conflicting_loops(tmp_path):
    with pytest.raises(SystemExit, match="mutually exclusive"):
        main(["--output", str(tmp_path / "t.json"), "--rates-only", "--baseline-only"])


def test_it_refuses_a_table_from_another_schema_version(tmp_path):
    stale = tmp_path / "t.json"
    stale.write_text(json.dumps({"meta": {"version": 99}, "classes": {}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="schema version"):
        main(["--output", str(stale), "--classes", "AA", "--quiet"])