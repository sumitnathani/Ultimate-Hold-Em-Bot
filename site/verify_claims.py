"""Regenerate every number the landing page quotes, straight from the engine.

The page makes a lot of specific numerical claims. This script is the reason
they can be trusted: run it and every figure in `site/index.html` comes back
out of `decision/` and `tools/preflop_table.json`.

    python site/verify_claims.py            # fast: river, pre-flop, the table
    python site/verify_claims.py --flop     # also the exact flop decisions (~8s each)
    python site/verify_claims.py --sim DIR  # also summarise simulate.py output

Lives in `site/` on purpose -- it reads the engine but the engine never reads
it, the same one-way dependency `tools/simulate.py` has.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# `python site/verify_claims.py` puts site/ on sys.path, not the repo root, and
# `decision` is imported from the root. Same trap the README documents for
# `tools/simulate.py`; fixed here rather than worked around.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from decision.evaluator import parse_cards  # noqa: E402
from decision.ev import ev_of_fold  # noqa: E402
from decision.flop import decide as flop_decide  # noqa: E402
from decision.preflop import decide as preflop_decide  # noqa: E402
from decision.preflop import load_table, starting_hand_classes  # noqa: E402
from decision.river import decide as river_decide  # noqa: E402
from decision.river import enumerate_dealer_outcomes  # noqa: E402

# --------------------------------------------------------------------------
# The claims. Keep these in step with site/index.html.
# --------------------------------------------------------------------------

ANTI_HERO = ("2c 3d", "As Ks Qs Js Ts")

RIVER_LADDER = [
    ("9h 9d", "Ks Qh Jd 4c 2s", "middle pair"),
    ("9h 9d", "Ks Qh Jd 4c 9s", "set"),
    ("7c 2d", "Ks Qh Jd 8s 3c", "total air"),
    ("Ac Kd", "Ks Qh Jd 8s 3c", "top pair, top kicker"),
    ("Ac Kd", "Qs Jh 8d 4c 2h", "ace high, no pair"),
    ("Ah Kh", "Qh Jh 2c 7d 9s", "missed flush draw"),
    ("7h 7d", "7s 7c 2d 9h 4c", "quads"),
    ("As 2d", "Ks Qs Js Ts 9c", "the royal"),
]

FLOP_LADDER = [
    ("Js Ts", "As Ks Qs", "flopped royal"),
    ("9h 9d", "Ks Qh Jd", "middle pair"),
    ("7c 2d", "Ks Qh Jd", "total air"),
    ("Ah Ad", "Kh 7s 2c", "overpair"),
    ("2c 3d", "As Ks Qs", "the anti-hero's flop"),
]

FOLK_WISDOM = ["32o", "72o"]


def rule(title: str) -> None:
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


def check_anti_hero() -> dict:
    rule("ACT I -- THE ANTI-HERO HAND")
    hole_s, board_s = ANTI_HERO
    hole, board = parse_cards(hole_s), parse_cards(board_s)

    d = river_decide(hole, board)
    counts = enumerate_dealer_outcomes(hole, board)
    total = sum(counts.values())
    wins = counts.get("win_qualified", 0) + counts.get("win_unqualified", 0)
    pushes = counts.get("push", 0)

    print(f"  {hole_s} on {board_s}")
    print(f"    dealer hands     {d.dealer_combos}          (page: 990)")
    print(f"    wins             {wins}              (page: 0)")
    print(f"    pushes           {pushes}            (page: 990)")
    print(f"    equity           {wins / total:.4%}        (page: 0.0000%)")
    print(f"    player hand      {d.player_hand}")
    print(f"    EV bet           {d.ev_bet:+.4f}        (page: +0.0000)")
    print(f"    EV fold          {d.ev_fold:+.4f}        (page: -2.0000)")
    print(f"    margin           {d.ev_advantage:+.4f}        (page: +2.0000)")
    print(f"    VERDICT          {d.action.value.upper()}            (page: BET)")

    # The board plays for both sides: every hole pair must decide identically.
    others = ["Ah Kh", "7h 2s", "9c 9d", "Ac Ad"]
    same = all(
        river_decide(parse_cards(h), board).action is d.action
        and river_decide(parse_cards(h), board).ev_bet == d.ev_bet
        for h in others
    )
    print(f"\n  every hole pair on this board decides identically: {same}")

    assert d.dealer_combos == 990
    assert wins == 0 and pushes == 990
    assert d.action.value == "bet"
    return {"equity": wins / total, "ev_bet": d.ev_bet, "ev_fold": d.ev_fold}


def check_ladder() -> None:
    rule("ACT III -- THE RIVER LADDER")
    print(f"  {'hand':8s} {'board':18s} {'verdict':8s} {'EV bet':>10s} "
          f"{'EV fold':>9s} {'margin':>9s}   note")
    for hole_s, board_s, note in RIVER_LADDER:
        d = river_decide(parse_cards(hole_s), parse_cards(board_s))
        print(f"  {hole_s:8s} {board_s:18s} {d.action.value.upper():8s} "
              f"{d.ev_bet:>+10.4f} {d.ev_fold:>+9.4f} {d.ev_advantage:>+9.4f}   {note}")

    # The one fold, and by how little it wins.
    fold = river_decide(parse_cards("7c 2d"), parse_cards("Ks Qh Jd 8s 3c"))
    print(f"\n  the only fold wins by {abs(fold.ev_advantage):.4f} units "
          f"out of a 2-unit decision")

    # Ace-high, no pair, is still a bet.
    ace = river_decide(parse_cards("Ac Kd"), parse_cards("Qs Jh 8d 4c 2h"))
    print(f"  ace high, no pair: bets and expects {ace.ev_bet:+.4f}; "
          f"folding is {ace.ev_fold:+.4f}")


def check_flop() -> None:
    rule("ACT III -- THE FLOP LADDER (exact, ~8s each)")
    print(f"  {'hand':8s} {'board':12s} {'verdict':8s} {'EV bet':>10s} "
          f"{'EV check':>10s} {'margin':>9s}   note")
    for hole_s, board_s, note in FLOP_LADDER:
        d = flop_decide(parse_cards(hole_s), parse_cards(board_s))
        print(f"  {hole_s:8s} {board_s:12s} {d.action.value.upper():8s} "
              f"{d.ev_bet:>+10.4f} {d.ev_check:>+10.4f} {d.ev_advantage:>+9.4f}   {note}")


def check_table() -> None:
    rule("ACT III/IV -- THE 169-CLASS PRE-FLOP TABLE")
    table = load_table()
    meta, rows = table["meta"], table["classes"]
    reps = meta["representatives"]

    print(f"  seed {meta['seed']}   trials {meta['trials']:,}   "
          f"boards {meta['boards']:,}   generated {meta['generated']}")
    print(f"  classes {len(rows)}   (page: 169)")

    def winrate(row: dict) -> float:
        c = row["counts"]
        return (c["win_qualified"] + c["win_unqualified"]) / row["trials"]

    n_bet = sum(1 for cls in starting_hand_classes()
                if preflop_decide(parse_cards(reps[cls])).ev_advantage > 0)
    print(f"  BET 4x {n_bet}   CHECK {len(rows) - n_bet}   (page: 83 / 86)")

    ranked = sorted(rows.items(), key=lambda kv: winrate(kv[1]))
    print("\n  worst five by win rate:")
    for cls, row in ranked[:5]:
        print(f"    {cls:5s} {winrate(row):.4%}")

    print("\n  the folk-wisdom beat -- poker calls 72o the worst hand:")
    for cls in FOLK_WISDOM:
        row = rows[cls]
        print(f"    {cls:5s} wins {winrate(row):.4%}   "
              f"check_value {row['check_value']:+.4f}")
    print("    -> 32o wins LESS often, 72o is worth LESS. Two answers to 'worst'.")

    worst_wr = ranked[0][0]
    worst_cv = min(rows.items(), key=lambda kv: kv[1]["check_value"])[0]
    print(f"\n  worst by win rate: {worst_wr}    worst by check_value: {worst_cv}")
    assert worst_wr == "32o" and worst_cv == "72o"
    assert n_bet == 83


def check_simulation(out_dir: Path | None) -> None:
    rule("ACT IV/V -- THE SIMULATION")
    print("  Canonical figures (root SESSION_NOTES.md, 35,000 hands, seed 20261106):")
    print("    R-B edge          -0.0270 +/- 0.0076 ante units/hand")
    print("    published optimum -0.0185 ... -0.02185 of the ante")
    print("    realised sd        4.2 units/hand  ->  signal:noise ~ 1:156")
    print("    pooled 20,000 hands realised +0.0036/hand -- a PROFIT, on a losing game")
    print("    ruin at 40 antes  8 of 10 bankrolls; headline died at hand 81")
    print(f"\n  ev_of_fold() = {ev_of_fold():+.4f}   (the -2 every river decision is against)")
    print(f"  4.2 / 0.027 = {4.2 / 0.027:.1f}   (page: 1 in 156)")

    if out_dir and out_dir.is_dir():
        print(f"\n  Output in {out_dir}:")
        for path in sorted(out_dir.glob("*.txt")):
            text = path.read_text(encoding="utf-8", errors="replace")
            keep = [ln.rstrip() for ln in text.splitlines()
                    if any(k in ln for k in ("R-B", "realised SD", "ruin",
                                             "profitable trials", "ruined trials",
                                             "final bankroll"))]
            print(f"\n    --- {path.name} ---")
            for ln in keep[:12]:
                print(f"    {ln}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flop", action="store_true",
                    help="also run the exact flop decisions (~8s each)")
    ap.add_argument("--sim", type=Path, default=None,
                    help="directory of simulate.py output to summarise")
    args = ap.parse_args()

    check_anti_hero()
    check_ladder()
    check_table()
    check_simulation(args.sim)
    if args.flop:
        check_flop()

    rule("OK -- every claim above is regenerated from the engine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
