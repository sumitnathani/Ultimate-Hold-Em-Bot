"""Pre-flop decision by lookup table (spec 3d).

Pre-flop there is no board -- only the two hole cards -- so there is nothing to
enumerate and nothing to sample at decision time. Spec 3d's answer is to move
all the work offline: a separate tool simulates every starting-hand class once,
writes the results to a JSON table, and the runtime decision becomes a
dictionary lookup.

WHAT THIS MODULE HOLDS
----------------------
Two halves that must agree on exactly one thing: what a key means.

:func:`starting_hand_class` maps an arbitrary two-card holding onto one of
:data:`STARTING_HAND_CLASS_COUNT` classes, and :func:`decide` looks that class
up in the offline table and returns the 4x-bet-or-check verdict. If the two
disagreed about the labelling, the table's rows would be silently mislabelled,
so the canonicaliser was built and tested against the generator *first*, before
any lookup existed to depend on it.

THE DECISION: BET 4x OR CHECK, AND CHECKING IS THE BASELINE
-----------------------------------------------------------
Pre-flop there is no fold -- the two actions are bet 4x and check (spec 3d), so
the bar betting has to clear is the value of *checking*, exactly as on the flop
(locked decision 1). That value cannot be computed here: it is the average of
the optimal river decision over all boards, and the boards do not exist yet.
The generator precomputes it per class and stores it as ``check_value``.

``decide`` is consequently a pure dictionary lookup -- no enumeration, no
sampling, and no variance of its own. Everything uncertain about it was already
paid for offline, and stays visible in the row it reads: ``trials``,
``boards``, and ``check_value_se``.

THE BLIND SCALAR IS WIN-CONDITIONAL, SO IT IS ONLY EXACT IN ONE PLACE
---------------------------------------------------------------------
``blind_multiplier`` in the table is ``blind_sum / wins``: the Blind profit per
unit averaged over the *winning* outcomes. That is exactly what
:func:`decision.ev.ev_of_bet` needs, because ``bucket_payoffs`` credits the
Blind on exactly those buckets and nowhere else. It is *not* the unconditional
Blind value, so it is only approximately right inside
:func:`decision.ev.breakeven_or_none`, which hypothetically varies ``p_win``
while holding the Blind fixed. Treat the reported ``breakeven`` as indicative;
the verdict does not depend on it, since it comes from comparing the two EVs.

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

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

from treys import Card

from decision.evaluator import RANKS
from decision.ev import (
    PAYOUT_TABLE,
    Outcomes,
    PayoutTable,
    breakeven_or_none,
    ev_of_bet,
)

__all__ = [
    "PREFLOP_PLAY_MULTIPLIER",
    "STARTING_HAND_CLASS_COUNT",
    "DEFAULT_TABLE_PATH",
    "PreflopAction",
    "PreflopDecision",
    "starting_hand_class",
    "starting_hand_classes",
    "load_table",
    "clear_table_cache",
    "decide",
]

#: 13 pairs + 78 suited + 78 offsuit. Named so the generator and the tests can
#: assert completeness without re-deriving the arithmetic.
STARTING_HAND_CLASS_COUNT = 169

#: Spec 3d: pre-flop is a 4x bet or a check.
PREFLOP_PLAY_MULTIPLIER = 4.0

#: The generator's output. Resolved from *this file's* location rather than the
#: process's working directory, so a decision reads the same table whatever cwd
#: the bot happens to be launched from.
DEFAULT_TABLE_PATH = (
    Path(__file__).resolve().parent.parent / "tools" / "preflop_table.json"
)

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


class PreflopAction(Enum):
    """What the decision engine wants the action layer to click."""

    BET = "bet"  # raise 4x
    CHECK = "check"


@dataclass(frozen=True)
class PreflopDecision:
    """The full reasoning behind one pre-flop decision, not just the verdict.

    Unlike :class:`decision.river.RiverDecision` and
    :class:`decision.flop.FlopDecision`, these numbers are **not exact**: the
    rates come from 2,000,000 sampled full runouts per class and ``check_value``
    from 6,000 sampled boards per class. Both sample sizes are carried on the
    object, so a caller can see the resolution behind a verdict rather than
    having to remember it from the generator's defaults.
    """

    action: PreflopAction
    multiplier: float
    #: The 169-class label this holding canonicalised to, e.g. ``"AKs"``.
    hand_class: str
    outcomes: Outcomes
    #: Blind profit per unit averaged over the *winning* outcomes, as stored by
    #: the generator. Win-conditional -- see the module docstring.
    blind_multiplier: float
    #: Full runouts sampled to produce ``outcomes``; 2,000,000 in the committed
    #: table.
    trials: int
    #: Boards sampled to produce ``ev_check``; 6,000 in the committed table.
    boards: int
    ev_bet: float
    #: The alternative actually available here -- the EV of checking, i.e. of
    #: seeing a flop and playing on from there. Never -2: folding is not an
    #: option pre-flop (locked decision 1).
    ev_check: float
    #: ``ev_bet - ev_check``. Positive means betting 4x is the better play.
    ev_advantage: float
    #: Standard error of ``ev_check`` from its board sample. This is the
    #: dominant uncertainty in the decision: the 2M-trial rate sample's own
    #: error is roughly two orders of magnitude smaller.
    check_value_se: float
    #: Win rate at which this decision would flip. ``None`` when it cannot be
    #: measured, and only indicative even when present, because the stored
    #: Blind is win-conditional -- see the module docstring.
    breakeven: float | None

    @property
    def equity(self) -> float:
        """P(win) over full runouts. Pushes are excluded, as on every street."""
        return self.outcomes.win

    @property
    def tie_rate(self) -> float:
        return self.outcomes.push

    @property
    def resolvable(self) -> bool:
        """Whether the margin clears one standard error of the baseline.

        ``False`` means the verdict sits inside the sampling noise of
        ``ev_check``, so a denser baseline pass could flip it -- which is
        precisely what the tier-2 re-measurement exists for. It is not a
        correctness flag: the verdict is still the best answer available, just
        a close one.
        """
        return abs(self.ev_advantage) > self.check_value_se

    def summary(self) -> str:
        be = "n/a" if self.breakeven is None else f"{self.breakeven:.2%}"
        noise = "" if self.resolvable else "  (within baseline noise)"
        return (
            f"{self.action.value.upper()} {self.multiplier:g}x  "
            f"[{self.hand_class}]  "
            f"win {self.equity:.2%} / push {self.tie_rate:.2%} / "
            f"lose {self.outcomes.lose:.2%}  "
            f"EV {self.ev_bet:+.3f} vs check {self.ev_check:+.3f} "
            f"(advantage {self.ev_advantage:+.3f} "
            f"+/- {self.check_value_se:.3f}, breakeven {be}){noise}"
        )


#: Parsed tables, keyed by path. The parse is ~75 KB of JSON and every decision
#: needs it, so it happens once per path per process.
_TABLE_CACHE: dict[Path, dict] = {}

_REQUIRED_ROW_KEYS = frozenset(
    {
        "counts",
        "trials",
        "wins",
        "blind_multiplier",
        "check_value",
        "boards",
        "check_value_se",
    }
)


def load_table(table_path: str | Path | None = None) -> dict:
    """Read and validate the generated table, once per path.

    **Lazy on purpose.** ``tools/generate_preflop_table.py`` imports
    :func:`starting_hand_class` from this module, so *importing* ``preflop``
    must not require the table to exist -- only *deciding* may. Reading happens
    on the first :func:`decide` call and is cached, so a long-running caller
    (the simulator, the eventual action loop) pays for the parse exactly once.
    """
    path = Path(table_path) if table_path is not None else DEFAULT_TABLE_PATH
    if path not in _TABLE_CACHE:
        with open(path, encoding="utf-8") as handle:
            table = json.load(handle)
        _validate_table(table, path)
        _TABLE_CACHE[path] = table
    return _TABLE_CACHE[path]


def clear_table_cache() -> None:
    """Drop the cached table(s). For tests that swap the file underneath."""
    _TABLE_CACHE.clear()


def _validate_table(table: dict, path: Path) -> None:
    """Fail loudly at load time rather than silently in the middle of a decision.

    A table missing a class or a field would otherwise surface as a ``KeyError``
    deep inside a decision -- or worse, as a wrong verdict. Both are far harder
    to trace than a message naming the file and the offending row.
    """
    classes = table.get("classes")
    if not isinstance(classes, dict):
        raise ValueError(f"{path}: no 'classes' mapping")

    expected = starting_hand_classes()
    known = set(expected)
    missing = [label for label in expected if label not in classes]
    extra = [label for label in classes if label not in known]
    if missing or extra:
        raise ValueError(
            f"{path}: class mismatch -- {len(missing)} missing "
            f"(e.g. {missing[:3]}), {len(extra)} unexpected (e.g. {extra[:3]})"
        )

    for label in expected:
        absent = _REQUIRED_ROW_KEYS - set(classes[label])
        if absent:
            raise ValueError(f"{path}: row {label!r} is missing {sorted(absent)}")


def decide(
    hole: Sequence[int],
    table: PayoutTable = PAYOUT_TABLE,
    *,
    table_path: str | Path | None = None,
) -> PreflopDecision:
    """Pre-flop verdict for a two-card holding: bet 4x or check (spec 3d).

    A dictionary lookup and nothing more -- see the module docstring for why
    nothing here is computed at runtime.

    ``table_path`` overrides where the generated table is read from; the
    default is :data:`DEFAULT_TABLE_PATH`. As on the flop and the river, the
    verdict comes from comparing the two EVs rather than the win rate against
    the threshold: equivalent, but immune to a degenerate threshold.
    """
    label = starting_hand_class(hole)
    row = load_table(table_path)["classes"][label]

    outcomes = Outcomes.from_counts(**row["counts"])
    blind = row["blind_multiplier"]
    ev_check = row["check_value"]
    ev_bet = ev_of_bet(PREFLOP_PLAY_MULTIPLIER, outcomes, blind, table)

    return PreflopDecision(
        action=PreflopAction.BET if ev_bet > ev_check else PreflopAction.CHECK,
        multiplier=PREFLOP_PLAY_MULTIPLIER,
        hand_class=label,
        outcomes=outcomes,
        blind_multiplier=blind,
        trials=row["trials"],
        boards=row["boards"],
        ev_bet=ev_bet,
        ev_check=ev_check,
        ev_advantage=ev_bet - ev_check,
        check_value_se=row["check_value_se"],
        breakeven=breakeven_or_none(
            outcomes, PREFLOP_PLAY_MULTIPLIER, blind, table, baseline=ev_check
        ),
    )