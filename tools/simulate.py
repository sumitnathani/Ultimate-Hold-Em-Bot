"""Bankroll simulation for the Ultimate Texas Hold'em decision engine.

Plays complete hands through ``decision/`` -- pre-flop (3d), flop (3c), river
(3b) -- and reports what a bankroll does over many of them. Offline, like the
table generator: nothing in the engine imports this.

WHAT A HAND LOOKS LIKE
----------------------
Deal two hole cards, two dealer cards and five board cards, then:

    pre-flop   bet 4x  -> showdown
               check   -> see the flop
    flop       bet 2x  -> showdown
               check   -> see the turn and river
    river      bet 1x  -> showdown
               fold    -> forfeit the Ante and Blind, -2 units

Every decision comes from the engine. Nothing here second-guesses it.

CHIPS, UNITS, AND WHAT "5,000 MAXIMUM BET" MEANS
------------------------------------------------
The engine works in **ante units** (:mod:`decision.ev`): the Ante and the Blind
are 1 unit each and the Play bet is the multiplier. Real chip figures need one
more number, so this module takes the table's maximum bet -- the largest single
wager the rules allow, which is the 4x pre-flop Play bet -- and derives the ante
from it:

    ante = max_bet / 4

With the default 5,000-chip maximum that is a 1,250-chip ante, a 2,500-chip
fold, and a 7,500-chip worst case, so the 50,000-chip bankroll is 40 antes.
Every figure is reported in units as well, because units are what the strategy
actually earns and they do not move when the ante does.

THE FLOP IS SAMPLED HERE, AND ONLY HERE
---------------------------------------
``flop.decide`` is exact and costs ~10s: 1,081 runouts, each graded over all 990
dealer hands. At that price a few hundred hands take hours, which is not a
simulation. So this module sweeps ``runouts`` sampled runouts instead of all
1,081 -- the same loop, with the same *exact* dealer enumeration inside each
runout, just fewer runouts. Pre-flop and river are untouched, and the flop's
sampling is the only approximation in the simulation.

Its cost is second-order by construction: a runout sample can only flip a flop
verdict whose margin is inside the sampling noise, and at those margins the two
actions are worth nearly the same, so the flip costs nearly nothing.
``tests/test_simulate.py`` pins the agreement against the exact decision, and
``--flop-runouts`` trades hands for precision.

TWO ESTIMATES OF THE SAME EDGE, ON PURPOSE
------------------------------------------
The realised bankroll is what a simulation is *for*, and it is also very noisy:
a single hand swings several units, so at a few thousand hands the realised mean
has a standard error larger than the edge it is trying to resolve. So every hand
also records the engine's *own* EV for the line it took (``expected_units``).
By the law of iterated expectations the mean of those is the same number with a
fraction of the variance -- a Rao-Blackwellised estimator, because the engine
already knows the conditional expectation the realised result is a draw from.

Report both. One is the bankroll, the other is the edge, and they answer
different questions: "what would 50,000 chips have done" versus "is this
strategy profitable".
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Sequence

from decision.evaluator import best_hand_rank, full_deck, remaining_deck
from decision.ev import (
    BUCKETS,
    PAYOUT_TABLE,
    Outcomes,
    PayoutTable,
    blind_multiplier_for_score,
    bucket_payoffs,
    dealer_qualifies,
    ev_of_bet,
    ev_of_fold,
)
from decision.flop import FLOP_PLAY_MULTIPLIER
from decision.preflop import (
    PREFLOP_PLAY_MULTIPLIER,
    PreflopAction,
    load_table,
    starting_hand_class,
    starting_hand_classes,
)
from decision.preflop import decide as preflop_decide
from decision.river import RIVER_PLAY_MULTIPLIER, RiverAction, optimal_ev
from decision.river import decide as river_decide

__all__ = [
    "DEFAULT_BANKROLL_CHIPS",
    "DEFAULT_MAX_BET_CHIPS",
    "DEFAULT_FLOP_RUNOUTS",
    "SimulationConfig",
    "HandResult",
    "SimulationResult",
    "TrialSummary",
    "sample_flop_sweep",
    "play_hand",
    "run_simulation",
    "run_trials",
    "analytic_ev_per_hand",
    "format_report",
]

#: Chips the bankroll starts at, and the largest single wager the rules allow.
#: The ante is derived from the latter -- see the module docstring.
DEFAULT_BANKROLL_CHIPS = 50_000.0
DEFAULT_MAX_BET_CHIPS = 5_000.0

#: Runouts sampled per flop decision. 1,081 would be exact and ~10s; this is
#: the speed/precision dial.
DEFAULT_FLOP_RUNOUTS = 32

_DEAL_SIZE = 9  # 2 hole + 2 dealer + 5 board


@dataclass(frozen=True)
class SimulationConfig:
    """Everything that fixes a simulation's shape and cost.

    ``max_bet_chips`` is the 4x Play bet, so the ante it implies is
    ``max_bet_chips / 4``; see the module docstring for why that is the reading
    of "maximum bet" this module uses.
    """

    hands: int = 2_000
    bankroll_chips: float = DEFAULT_BANKROLL_CHIPS
    max_bet_chips: float = DEFAULT_MAX_BET_CHIPS
    flop_runouts: int = DEFAULT_FLOP_RUNOUTS
    seed: int = 20261106

    @property
    def ante_chips(self) -> float:
        return self.max_bet_chips / PREFLOP_PLAY_MULTIPLIER

    @property
    def fold_cost_chips(self) -> float:
        return -ev_of_fold() * self.ante_chips

    def __post_init__(self) -> None:
        if self.hands <= 0:
            raise ValueError("hands must be positive")
        if self.max_bet_chips <= 0:
            raise ValueError("max_bet_chips must be positive")
        if self.flop_runouts <= 0:
            raise ValueError("flop_runouts must be positive")


@dataclass(frozen=True)
class HandResult:
    """One played hand: what was decided, what it paid, and what it was worth.

    ``profit_units`` is the realised result. ``expected_units`` is the engine's
    own EV for the line taken, recorded *at the decision point* -- the two are
    different draws of the same quantity, which is the whole point of carrying
    both (see the module docstring).
    """

    hand_class: str
    preflop: str
    #: ``None`` when a pre-flop 4x bet ended the hand before the flop.
    flop: str | None
    #: ``None`` unless the hand reached the river.
    river: str | None
    #: The five-bucket outcome at showdown, or ``"fold"``.
    bucket: str
    #: Play multiplier actually wagered: 4, 2, 1, or 0 when the river was folded.
    multiplier: float
    profit_units: float
    expected_units: float
    bankroll_after: float


@dataclass(frozen=True)
class SimulationResult:
    """One run: ``hands`` hands from a fresh bankroll."""

    config: SimulationConfig
    seed: int
    hands: tuple[HandResult, ...]
    #: Hand index (1-based) at which the bankroll first could not cover a fold,
    #: or ``None``. The run keeps going afterwards -- see :meth:`ruined`.
    ruin_at: int | None

    # --- the edge -------------------------------------------------------

    @property
    def net_units(self) -> float:
        return sum(h.profit_units for h in self.hands)

    @property
    def net_chips(self) -> float:
        return self.net_units * self.config.ante_chips

    @property
    def realised_units_per_hand(self) -> float:
        return self.net_units / len(self.hands)

    @property
    def realised_sd(self) -> float:
        return statistics.stdev(h.profit_units for h in self.hands)

    @property
    def realised_se(self) -> float:
        return self.realised_sd / math.sqrt(len(self.hands))

    @property
    def expected_units_per_hand(self) -> float:
        """Rao-Blackwellised EV: the mean of the engine's own per-hand EV."""
        return sum(h.expected_units for h in self.hands) / len(self.hands)

    @property
    def expected_se(self) -> float:
        values = [h.expected_units for h in self.hands]
        return statistics.stdev(values) / math.sqrt(len(values))

    # --- the bankroll ---------------------------------------------------

    @property
    def final_bankroll(self) -> float:
        return self.config.bankroll_chips + self.net_chips

    @property
    def lowest_bankroll(self) -> float:
        return min(h.bankroll_after for h in self.hands)

    @property
    def highest_bankroll(self) -> float:
        return max(h.bankroll_after for h in self.hands)

    @property
    def max_drawdown_chips(self) -> float:
        """Largest peak-to-trough fall of the bankroll, in chips."""
        peak = self.config.bankroll_chips
        worst = 0.0
        for hand in self.hands:
            peak = max(peak, hand.bankroll_after)
            worst = max(worst, peak - hand.bankroll_after)
        return worst

    @property
    def ruined(self) -> bool:
        """Whether the bankroll ever fell below one fold's cost."""
        return self.ruin_at is not None

    # --- what was played ------------------------------------------------

    def action_counts(self, street: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for hand in self.hands:
            action = getattr(hand, street)
            if action is not None:
                counts[action] = counts.get(action, 0) + 1
        return counts

    def bucket_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for hand in self.hands:
            counts[hand.bucket] = counts.get(hand.bucket, 0) + 1
        return counts


@dataclass(frozen=True)
class TrialSummary:
    """Several independent runs, so the spread is visible and not just the mean."""

    config: SimulationConfig
    results: tuple[SimulationResult, ...]

    @property
    def hands_each(self) -> int:
        return self.config.hands

    @property
    def total_hands(self) -> int:
        return sum(len(r.hands) for r in self.results)

    @property
    def pooled_units_per_hand(self) -> float:
        return sum(r.net_units for r in self.results) / self.total_hands

    @property
    def pooled_expected_units_per_hand(self) -> float:
        pooled = [h.expected_units for r in self.results for h in r.hands]
        return sum(pooled) / len(pooled)

    @property
    def pooled_expected_se(self) -> float:
        pooled = [h.expected_units for r in self.results for h in r.hands]
        return statistics.stdev(pooled) / math.sqrt(len(pooled))

    @property
    def ruin_count(self) -> int:
        return sum(1 for r in self.results if r.ruined)

    @property
    def final_bankrolls(self) -> list[float]:
        return [r.final_bankroll for r in self.results]


# ---------------------------------------------------------------------------
# The one approximated street
# ---------------------------------------------------------------------------


def sample_flop_sweep(
    hole: Sequence[int],
    board: Sequence[int],
    rng: random.Random,
    runouts: int,
    table: PayoutTable = PAYOUT_TABLE,
) -> tuple[float, float, Outcomes, float]:
    """``flop.enumerate_flop_outcomes`` over ``runouts`` sampled runouts.

    The loop is the flop's own, runout-outer and dealer-inner, with the exact
    C(45,2) = 990 dealer enumeration inside each runout -- only the *runouts*
    are sampled. Returns ``(ev_bet_2x, ev_check, outcomes, blind_multiplier)``.

    Kept here rather than in ``flop.py`` because it is explicitly approximate
    and ``flop.py``'s contract is explicitly exact; the two are bound together
    by ``tests/test_simulate.py::test_the_sampled_flop_agrees_with_the_exact_one``
    rather than by sharing a body that would have to be one or the other.
    """
    deck = remaining_deck(hole, board)
    counts = dict.fromkeys(BUCKETS, 0)
    blind_sum = 0.0
    check_sum = 0.0

    for _ in range(runouts):
        turn, river = rng.sample(deck, 2)
        board5 = list(board) + [turn, river]
        player_score = best_hand_rank(hole, board5)
        blind = blind_multiplier_for_score(player_score, table)
        dealer_deck = [card for card in deck if card != turn and card != river]

        runout_counts = dict.fromkeys(BUCKETS, 0)
        for dealer in combinations(dealer_deck, 2):
            dealer_score = best_hand_rank(dealer, board5)
            qualified = dealer_qualifies(dealer_score)

            # treys: LOWER score is the STRONGER hand, so this reads backwards
            # from how it looks. The player wins when their score is lower.
            if player_score < dealer_score:
                bucket = "win_qualified" if qualified else "win_unqualified"
                blind_sum += blind
            elif player_score > dealer_score:
                bucket = "lose_qualified" if qualified else "lose_unqualified"
            else:
                bucket = "push"

            runout_counts[bucket] += 1
            counts[bucket] += 1

        # What checking this flop is worth: the turn and river arrive and the
        # hand is then played as well as it can be. Same quantity flop.py
        # averages, over fewer runouts.
        check_sum += optimal_ev(
            Outcomes.from_counts(**runout_counts), blind, table
        )

    outcomes = Outcomes.from_counts(**counts)
    wins = counts["win_qualified"] + counts["win_unqualified"]
    blind_multiplier = blind_sum / wins if wins else 0.0
    return (
        ev_of_bet(FLOP_PLAY_MULTIPLIER, outcomes, blind_multiplier, table),
        check_sum / runouts,
        outcomes,
        blind_multiplier,
    )


# ---------------------------------------------------------------------------
# One hand
# ---------------------------------------------------------------------------


def _showdown(
    hole: Sequence[int],
    dealer: Sequence[int],
    board: Sequence[int],
    table: PayoutTable = PAYOUT_TABLE,
) -> tuple[str, float]:
    """The five-bucket outcome and the Blind multiplier for our final hand."""
    player_score = best_hand_rank(hole, board)
    dealer_score = best_hand_rank(dealer, board)
    qualified = dealer_qualifies(dealer_score)

    if player_score < dealer_score:
        bucket = "win_qualified" if qualified else "win_unqualified"
    elif player_score > dealer_score:
        bucket = "lose_qualified" if qualified else "lose_unqualified"
    else:
        bucket = "push"

    return bucket, blind_multiplier_for_score(player_score, table)


def play_hand(
    rng: random.Random,
    bankroll: float,
    config: SimulationConfig,
    table: PayoutTable = PAYOUT_TABLE,
) -> HandResult:
    """Play one hand from deal to payout, recording both result and EV."""
    cards = rng.sample(full_deck(), _DEAL_SIZE)
    hole, dealer, board = cards[:2], cards[2:4], cards[4:]
    hand_class = starting_hand_class(hole)

    preflop = preflop_decide(hole, table)
    flop_action: str | None = None
    river_action: str | None = None

    if preflop.action is PreflopAction.BET:
        # 4x ends the hand: no further decisions are available.
        multiplier = PREFLOP_PLAY_MULTIPLIER
        expected = preflop.ev_bet

    else:
        ev_bet, ev_check, _outcomes, _blind = sample_flop_sweep(
            hole, board[:3], rng, config.flop_runouts, table
        )
        if ev_bet > ev_check:
            flop_action = "bet"
            multiplier = FLOP_PLAY_MULTIPLIER
            expected = ev_bet
        else:
            flop_action = "check"
            river = river_decide(hole, board, table)
            if river.action is RiverAction.BET:
                river_action = "bet"
                multiplier = RIVER_PLAY_MULTIPLIER
                expected = river.ev_bet
            else:
                river_action = "fold"
                multiplier = 0.0
                expected = river.ev_fold

    if multiplier == 0.0:
        bucket = "fold"
        profit_units = ev_of_fold()
    else:
        bucket, blind = _showdown(hole, dealer, board, table)
        profit_units = bucket_payoffs(multiplier, blind, table)[bucket]

    return HandResult(
        hand_class=hand_class,
        preflop=preflop.action.value,
        flop=flop_action,
        river=river_action,
        bucket=bucket,
        multiplier=multiplier,
        profit_units=profit_units,
        expected_units=expected,
        bankroll_after=bankroll + profit_units * config.ante_chips,
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def run_simulation(config: SimulationConfig, seed: int | None = None) -> SimulationResult:
    """Play ``config.hands`` hands from ``config.bankroll_chips``."""
    seed = config.seed if seed is None else seed
    rng = random.Random(seed)

    bankroll = config.bankroll_chips
    ruin_at: int | None = None
    results: list[HandResult] = []

    for index in range(1, config.hands + 1):
        hand = play_hand(rng, bankroll, config)
        bankroll = hand.bankroll_after
        results.append(hand)
        # Ruin is "cannot cover the next fold". The run deliberately continues:
        # stopping would truncate the EV estimate with the worst hands missing,
        # which is exactly the bias a ruined run is most exposed to.
        if ruin_at is None and bankroll < config.fold_cost_chips:
            ruin_at = index

    return SimulationResult(
        config=config, seed=seed, hands=tuple(results), ruin_at=ruin_at
    )


def run_trials(config: SimulationConfig, trials: int) -> TrialSummary:
    """``trials`` independent runs, each from a fresh bankroll, seeds derived
    from the config's so a whole batch is reproducible from one number."""
    if trials <= 0:
        raise ValueError("trials must be positive")
    results = tuple(
        run_simulation(config, seed=config.seed + 1_000_003 * index)
        for index in range(trials)
    )
    return TrialSummary(config=config, results=results)


# ---------------------------------------------------------------------------
# The edge, without simulating it
# ---------------------------------------------------------------------------


def analytic_ev_per_hand(table: PayoutTable = PAYOUT_TABLE) -> float:
    """Ex-ante EV per hand under the pre-flop table's own model, exactly.

    Weighs each of the 169 classes by how often it is dealt -- 6 holdings for a
    pair, 4 suited, 12 offsuit, over 1,326 -- and takes the better of the two
    pre-flop actions for each. No sampling: this is what the table says a hand
    is worth before a single card is turned.

    It is a **lower bound** on the strategy the simulator plays, by exactly the
    F term. The table's ``check_value`` prices "check pre-flop, check the flop,
    play the river", while the simulator bets the flop whenever that is better,
    so the simulated edge should sit at or above this number.
    """
    rows = load_table()["classes"]
    total = 0.0
    for label in starting_hand_classes():
        row = rows[label]
        outcomes = Outcomes.from_counts(**row["counts"])
        ev_bet = ev_of_bet(
            PREFLOP_PLAY_MULTIPLIER, outcomes, row["blind_multiplier"], table
        )
        weight = 6 if len(label) == 2 else (4 if label.endswith("s") else 12)
        total += weight * max(ev_bet, row["check_value"])
    return total / 1326


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _pct(value: float) -> str:
    return f"{value:+.3%}"


def format_report(summary: TrialSummary) -> str:
    config = summary.config
    lines: list[str] = []
    add = lines.append

    add("=" * 74)
    add("ULTIMATE TEXAS HOLD'EM -- BANKROLL SIMULATION")
    add("=" * 74)
    add("")
    add(f"  hands per trial     {config.hands:,}")
    add(f"  trials              {len(summary.results)}")
    add(f"  total hands         {summary.total_hands:,}")
    add(f"  starting bankroll   {config.bankroll_chips:,.0f} chips")
    add(f"  ante / blind        {config.ante_chips:,.0f} chips each")
    add(f"  max bet (4x play)   {config.max_bet_chips:,.0f} chips")
    add(f"  worst case / hand   {config.fold_cost_chips:,.0f} chips (a fold)")
    add(f"  flop runouts        {config.flop_runouts} of 1,081 (sampled)")
    add(f"  base seed           {config.seed}")
    add("")

    add("-" * 74)
    add("THE EDGE")
    add("-" * 74)
    pooled_units = summary.pooled_units_per_hand
    pooled_expected = summary.pooled_expected_units_per_hand
    expected_se = summary.pooled_expected_se
    analytic = analytic_ev_per_hand()
    add("")
    add(f"  analytic EV/hand (table)      {analytic:+.4f} units"
        f"   = {_pct(analytic)} of the ante")
    add(f"  simulated EV/hand (R-B)       {pooled_expected:+.4f} units"
        f"   +/- {expected_se:.4f}   = {_pct(pooled_expected)} of the ante")
    add(f"  realised P/L/hand             {pooled_units:+.4f} units"
        f"   = {_pct(pooled_units)} of the ante")
    add("")

    realised_sd = statistics.stdev(
        h.profit_units for r in summary.results for h in r.hands
    )
    realised_se = realised_sd / math.sqrt(summary.total_hands)
    add(f"  realised SD/hand              {realised_sd:.4f} units")
    add(f"  realised SE/hand              {realised_se:.4f} units"
        f"   (95% CI {pooled_units - 1.96*realised_se:+.4f} to "
        f"{pooled_units + 1.96*realised_se:+.4f})")
    add(f"  realised SE is {realised_se / max(abs(analytic), 1e-9):.1f}x the edge"
        f" -- why the R-B estimate above is the one to trust")
    add("")

    add("-" * 74)
    add("THE BANKROLL")
    add("-" * 74)
    add("")
    finals = summary.final_bankrolls
    net = [f - config.bankroll_chips for f in finals]
    add(f"  final bankroll        mean {statistics.mean(finals):,.0f}"
        f"   min {min(finals):,.0f}   max {max(finals):,.0f} chips")
    add(f"  net per trial         mean {statistics.mean(net):+,.0f}"
        f"   min {min(net):+,.0f}   max {max(net):+,.0f} chips")
    add(f"  profitable trials     {sum(1 for n in net if n > 0)} of {len(net)}")
    add(f"  ruined trials         {summary.ruin_count} of {len(summary.results)}"
        f"   (bankroll below one fold, {config.fold_cost_chips:,.0f} chips)")
    add("")
    for index, result in enumerate(summary.results):
        ruin = f"ruin at hand {result.ruin_at:,}" if result.ruined else "never ruined"
        add(f"  trial {index + 1:<3} seed {result.seed:<10}"
            f" final {result.final_bankroll:>10,.0f}"
            f"   low {result.lowest_bankroll:>10,.0f}"
            f"   maxDD {result.max_drawdown_chips:>9,.0f}   {ruin}")
    add("")

    add("-" * 74)
    add("WHAT WAS PLAYED (pooled)")
    add("-" * 74)
    add("")
    total = summary.total_hands
    for street in ("preflop", "flop", "river"):
        counts = {}
        for result in summary.results:
            for action, count in result.action_counts(street).items():
                counts[action] = counts.get(action, 0) + count
        rendered = "   ".join(
            f"{action} {count:,} ({count / total:.1%})"
            for action, count in sorted(counts.items())
        )
        add(f"  {street:<9} {rendered}")
    add("")
    buckets: dict[str, int] = {}
    for result in summary.results:
        for bucket, count in result.bucket_counts().items():
            buckets[bucket] = buckets.get(bucket, 0) + count
    for bucket in list(BUCKETS) + ["fold"]:
        if bucket in buckets:
            add(f"  {bucket:<18} {buckets[bucket]:>9,}  ({buckets[bucket] / total:.1%})")
    add("")
    add("=" * 74)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hands", type=int, default=SimulationConfig.hands)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument(
        "--bankroll", type=float, default=DEFAULT_BANKROLL_CHIPS, help="chips"
    )
    parser.add_argument(
        "--max-bet", type=float, default=DEFAULT_MAX_BET_CHIPS, help="chips"
    )
    parser.add_argument("--flop-runouts", type=int, default=DEFAULT_FLOP_RUNOUTS)
    parser.add_argument("--seed", type=int, default=SimulationConfig.seed)
    parser.add_argument("--json", type=Path, help="also write raw per-trial metrics")
    args = parser.parse_args(argv)

    config = SimulationConfig(
        hands=args.hands,
        bankroll_chips=args.bankroll,
        max_bet_chips=args.max_bet,
        flop_runouts=args.flop_runouts,
        seed=args.seed,
    )
    summary = run_trials(config, args.trials)
    print(format_report(summary))

    if args.json:
        payload = {
            "config": {
                "hands": config.hands,
                "bankroll_chips": config.bankroll_chips,
                "ante_chips": config.ante_chips,
                "max_bet_chips": config.max_bet_chips,
                "flop_runouts": config.flop_runouts,
                "seed": config.seed,
            },
            "analytic_ev_per_hand": analytic_ev_per_hand(),
            "pooled_expected_units_per_hand": summary.pooled_expected_units_per_hand,
            "pooled_realised_units_per_hand": summary.pooled_units_per_hand,
            "trials": [
                {
                    "seed": r.seed,
                    "final_bankroll": r.final_bankroll,
                    "net_chips": r.net_chips,
                    "lowest_bankroll": r.lowest_bankroll,
                    "max_drawdown_chips": r.max_drawdown_chips,
                    "ruin_at": r.ruin_at,
                    "realised_units_per_hand": r.realised_units_per_hand,
                    "expected_units_per_hand": r.expected_units_per_hand,
                }
                for r in summary.results
            ],
        }
        args.json.write_text(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
