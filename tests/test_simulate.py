"""Tests for tools/simulate.py.

The simulator is the only place in the project that *spends* the engine's
answers, so what needs testing is the accounting: that a hand's recorded profit
is the payout the rules actually specify, that the bankroll is the running sum
of those profits, and that a seed fixes the whole run.

Plus one test that binds the simulation's one approximation -- the sampled flop
sweep -- to the exact ``flop.decide`` it stands in for. That one is expensive
(~10s per exact flop), so it uses three flops and is module-scoped.
"""

from __future__ import annotations

import random

import pytest

from decision.evaluator import parse_cards
from decision.ev import PAYOUT_TABLE, bucket_payoffs, ev_of_fold
from decision.flop import FLOP_PLAY_MULTIPLIER, FlopAction, decide as flop_decide
from decision.preflop import PREFLOP_PLAY_MULTIPLIER
from tools.simulate import (
    DEFAULT_MAX_BET_CHIPS,
    SimulationConfig,
    _showdown,
    analytic_ev_per_hand,
    play_hand,
    run_simulation,
    run_trials,
    sample_flop_sweep,
)


def c(text: str) -> list[int]:
    return parse_cards(text)


def small_config(**overrides) -> SimulationConfig:
    """A config whose runs finish in a second or two."""
    settings = dict(hands=40, flop_runouts=8, seed=1234)
    settings.update(overrides)
    return SimulationConfig(**settings)


# --------------------------------------------------------------------------
# The chip model
# --------------------------------------------------------------------------


def test_the_ante_is_a_quarter_of_the_maximum_bet():
    """The 4x pre-flop Play bet *is* the table maximum, so the ante is 1/4 of it."""
    config = SimulationConfig(max_bet_chips=DEFAULT_MAX_BET_CHIPS)
    assert config.ante_chips == DEFAULT_MAX_BET_CHIPS / PREFLOP_PLAY_MULTIPLIER
    assert config.ante_chips == 1250.0
    # A fold forfeits the Ante and the Blind: two antes.
    assert config.fold_cost_chips == 2500.0


@pytest.mark.parametrize(
    "overrides",
    [{"hands": 0}, {"max_bet_chips": 0}, {"flop_runouts": 0}],
)
def test_it_rejects_a_degenerate_config(overrides):
    with pytest.raises(ValueError):
        SimulationConfig(**overrides)


# --------------------------------------------------------------------------
# The showdown buckets
# --------------------------------------------------------------------------


def test_the_showdown_buckets_a_royal_flush_against_a_qualifying_pair():
    """A royal beats a pair, the pair qualifies, and the Blind pays 500:1."""
    bucket, blind = _showdown(c("As Ks"), c("2h 2d"), c("Qs Js Ts 2c 3d"))
    assert bucket == "win_qualified"
    assert blind == 500.0


def test_the_showdown_buckets_a_loss_to_a_non_qualifying_dealer():
    """Dealer wins on high cards only, so the Ante pushes but the Play loses."""
    bucket, _blind = _showdown(c("Th 7d"), c("Jh 8d"), c("2c 3d 4h 9s Kc"))
    assert bucket == "lose_unqualified"


def test_the_showdown_buckets_a_tie():
    bucket, _blind = _showdown(c("Ah Kh"), c("Ad Kd"), c("2c 3d 4h 9s Kc"))
    assert bucket == "push"


# --------------------------------------------------------------------------
# A played hand
# --------------------------------------------------------------------------


def test_a_played_hand_records_a_payout_the_rules_allow():
    """Whatever line it took, the profit must be a payout spec 9 defines."""
    rng = random.Random(5)
    config = small_config()
    for _ in range(15):
        hand = play_hand(rng, config.bankroll_chips, config)

        if hand.bucket == "fold":
            assert hand.multiplier == 0.0
            assert hand.profit_units == pytest.approx(ev_of_fold())
            continue

        # The Blind for our final hand is unknown from here, but every bucket's
        # payoff is affine in it, so the profit must sit inside the range the
        # paytable can produce for this multiplier and bucket.
        for blind in (0.0, 1.0, 1.5, 3.0, 10.0, 50.0, 500.0):
            payoffs = bucket_payoffs(hand.multiplier, blind, PAYOUT_TABLE)
            if hand.profit_units == pytest.approx(payoffs[hand.bucket]):
                break
        else:
            raise AssertionError(
                f"profit {hand.profit_units} is not a payoff for "
                f"{hand.multiplier}x / {hand.bucket}"
            )


def test_a_hand_that_bets_preflop_has_no_flop_decision():
    """4x ends the hand -- there is nothing left to decide."""
    rng = random.Random(11)
    config = small_config()
    seen_preflop_bet = False
    for _ in range(60):
        hand = play_hand(rng, config.bankroll_chips, config)
        if hand.preflop == "bet":
            seen_preflop_bet = True
            assert hand.flop is None
            assert hand.river is None
            assert hand.multiplier == PREFLOP_PLAY_MULTIPLIER
        elif hand.flop == "bet":
            assert hand.river is None
        else:
            assert hand.flop == "check"
    assert seen_preflop_bet, "60 hands with no 4x bet is implausible"


def test_the_expected_units_are_the_engines_own_ev():
    """Every hand records an EV, and it is never below the fold cost."""
    rng = random.Random(17)
    config = small_config()
    for _ in range(30):
        hand = play_hand(rng, config.bankroll_chips, config)
        assert hand.expected_units >= ev_of_fold() - 1e-9


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def test_the_bankroll_is_the_running_sum_of_the_hands():
    config = small_config()
    result = run_simulation(config)
    running = config.bankroll_chips
    for hand in result.hands:
        running += hand.profit_units * config.ante_chips
        assert hand.bankroll_after == pytest.approx(running)


def test_a_run_is_reproducible_from_its_seed():
    config = small_config()
    assert run_simulation(config, seed=7) == run_simulation(config, seed=7)


def test_different_seeds_give_different_runs():
    config = small_config()
    assert run_simulation(config, seed=7) != run_simulation(config, seed=8)


def test_it_plays_exactly_the_configured_number_of_hands():
    config = small_config(hands=37)
    result = run_simulation(config)
    assert len(result.hands) == 37
    assert result.net_chips == pytest.approx(
        result.net_units * config.ante_chips
    )


def test_ruin_is_detected_and_the_run_continues():
    """A bankroll that cannot cover a fold is ruined -- but the run keeps going,
    because truncating there would drop exactly the worst hands."""
    config = small_config(hands=200, bankroll_chips=1_000.0)
    result = run_simulation(config)
    assert result.ruined
    assert result.ruin_at is not None
    assert result.lowest_bankroll < config.fold_cost_chips
    assert len(result.hands) == 200, "the run must not stop at ruin"


def test_a_deep_bankroll_is_never_ruined():
    config = small_config(hands=100, bankroll_chips=10_000_000.0)
    assert not run_simulation(config).ruined


def test_trials_are_independent_runs_with_derived_seeds():
    config = small_config(hands=20)
    summary = run_trials(config, 3)
    assert len(summary.results) == 3
    assert len({r.seed for r in summary.results}) == 3
    assert summary.total_hands == 60


# --------------------------------------------------------------------------
# The analytic edge
# --------------------------------------------------------------------------


def test_the_analytic_edge_is_a_per_hand_figure_in_a_sane_range():
    """It is the table's own verdict on a hand before any card is seen: a loss,
    but nowhere near the -2 of folding everything."""
    ev = analytic_ev_per_hand()
    assert ev_of_fold() < ev < 0.0


def test_the_analytic_edge_reproduces_a_manual_weighting():
    """Recompute it the long way and check the helper agrees."""
    from decision.ev import Outcomes, ev_of_bet
    from decision.preflop import load_table, starting_hand_classes

    rows = load_table()["classes"]
    total = 0.0
    for label in starting_hand_classes():
        row = rows[label]
        bet = ev_of_bet(
            PREFLOP_PLAY_MULTIPLIER,
            Outcomes.from_counts(**row["counts"]),
            row["blind_multiplier"],
        )
        weight = 6 if len(label) == 2 else (4 if label.endswith("s") else 12)
        total += weight * max(bet, row["check_value"])
    assert analytic_ev_per_hand() == pytest.approx(total / 1326)


# --------------------------------------------------------------------------
# The one approximation, bound to the exact decision it stands in for
# --------------------------------------------------------------------------

#: Three real flops. Each costs ~10s to decide exactly, so this is the whole
#: reason the agreement test is this small. They are picked to span the two
#: ways a flop can be hard: one flush-heavy board with a live royal (the
#: heavy-tailed case), one near the bet/check boundary, and one decisive check.
_FLOP_CASES = [
    (c("Ah Kh"), c("Qh 8s 3d")),
    (c("9h 9d"), c("Ks Qh Jd")),
    (c("7c 2d"), c("Ks Qh Jd")),
]

#: Runouts per sampled sweep in the agreement test. 64 is 6% of the 1,081, so a
#: royal runout lands in the sample about one time in seventeen.
_AGREEMENT_RUNOUTS = 64


@pytest.fixture(scope="module")
def exact_flops():
    return [flop_decide(hole, board) for hole, board in _FLOP_CASES]


@pytest.mark.parametrize("index", range(len(_FLOP_CASES)))
def test_the_sampled_flop_agrees_with_the_exact_one(exact_flops, index):
    """The simulation's only approximation, held against the real thing.

    Not an equality assertion -- the sampled sweep is *meant* to differ -- and
    the quantity it asserts on is the **margin**, not ``ev_check``.

    That choice is the whole content of this test. ``ev_check`` is not merely
    noisy, it is heavy-tailed: ``Ah Kh`` on ``Qh 8s 3d`` can run out a royal,
    which pays 500:1 on the Blind and so is worth ~500 units on one runout in
    1,081. At 64 runouts the sample almost always misses it, so the sampled
    ``ev_check`` sits ~0.44 below the exact one and its sd across seeds is 3.3
    -- any ``abs=`` bound wide enough to hold would assert nothing. The
    royal moves ``ev_bet`` and ``ev_check`` *together* (both are computed from
    the same runouts), which is why the margin is not heavy-tailed: measured sd
    0.064 at 64 runouts, max error 0.127 over 10 seeds. The margin is also the
    only thing the simulation actually spends -- it picks the action, and the
    action's EV cost is the margin -- so it is the quantity worth binding.
    """
    hole, board = _FLOP_CASES[index]
    exact = exact_flops[index]

    ev_bet, ev_check, outcomes, blind = sample_flop_sweep(
        hole, board, random.Random(20261106), _AGREEMENT_RUNOUTS
    )

    assert outcomes.total == pytest.approx(1.0)
    assert blind >= 0.0

    # ~4x the measured sd, and above the worst of 10 seeds: loose enough not to
    # flake, tight enough that a real bias could not hide inside it.
    margin = exact.ev_bet - exact.ev_check
    assert (ev_bet - ev_check) == pytest.approx(margin, abs=0.25)

    if abs(margin) > 0.5:
        sampled = FlopAction.BET if ev_bet > ev_check else FlopAction.CHECK
        assert sampled is exact.action, (
            f"a decisive flop ({margin:+.2f}) must not flip"
        )
