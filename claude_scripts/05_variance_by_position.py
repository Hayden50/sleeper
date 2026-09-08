"""
requests.txt #4: High variance players / team consistency, by position.

For each team's *current starters*, looks at each player's actual game-by-
game fantasy scoring from last season (2025) and computes:
  - mean points per game played
  - population stdev of points per game played
  - coefficient of variation (CV = stdev / mean) - a scale-free volatility
    score, so a boom/bust RB and a boom/bust TE can be compared even though
    TEs score fewer points on average. Higher CV = more boom/bust.

These are rolled up to a team-by-position average CV, so you can see e.g.
"team X's RBs are volatile, team Y's are steady" side by side.

Notes / assumptions:
- Uses last season's (2025) actual per-game results, not this season's
  projections - projections are a forecast of the mean, they don't tell you
  about week-to-week spread. A player's role/health can obviously change
  year to year; this is the best available signal, not a guarantee.
- "Played" = Sleeper recorded a fantasy-points value for that player that
  week at all (see load_game_log in common.py - Sleeper's own "gms_active"
  flag turns out to be unreliable and can't be used for this). Weeks a
  player didn't play (bye, injury/IR, healthy inactive) are excluded from
  their game log rather than counted as a 0, since a 0-from-not-playing
  would inflate volatility for a reason that has nothing to do with their
  boom/bust profile on the field. A real, legitimately low/zero-point game
  they actually played in is still counted - only DNPs are dropped.
- Rookies and anyone with 0-1 games played last season have no meaningful
  CV and are called out separately rather than silently dropped or given a
  misleading number.
- Uses this league's current PPR scoring column against last year's actual
  stats, so the points themselves aren't literally what happened in 2025
  Sleeper standings, just this league's scoring rules applied to real box
  scores.

Output: outputs/variance_by_position.txt
"""

from __future__ import annotations

from collections import defaultdict

from common import (
    consistency_stats,
    get_client,
    load_config,
    load_game_log,
    load_players,
    points_field,
    required_positions,
    starter_slots,
    team_name_lookup,
    write_output,
)

POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"]
PREV_SEASON_WEEKS = range(1, 19)  # up to 18; extra weeks simply have no data


def main():
    client = get_client()
    config_teams = team_name_lookup(load_config())

    league = client.get_league()
    roster_positions = league["roster_positions"]
    positions = required_positions(roster_positions)
    pts_field = points_field(league["scoring_settings"])

    state = client.get_nfl_state()
    prev_season = state["previous_season"]

    rosters = client.get_rosters()
    players = load_players(client)
    game_log = load_game_log(client, prev_season, PREV_SEASON_WEEKS, positions, pts_field)

    team_rows = []
    league_cvs_by_position = defaultdict(list)

    for roster in rosters:
        owner_id = roster.get("owner_id")
        team_name = config_teams.get(owner_id, owner_id or "UNCLAIMED")

        by_position = defaultdict(list)  # pos -> [(name, stats_dict), ...]
        for _, pid in starter_slots(roster, roster_positions):
            info = players.get(pid, {})
            pos = info.get("position") or "?"
            name = info.get("full_name") or pid
            stats = consistency_stats(game_log.get(pid, []))
            by_position[pos].append((name, stats))
            if stats["cv"] is not None:
                league_cvs_by_position[pos].append(stats["cv"])

        position_avg_cv = {}
        for pos, entries in by_position.items():
            cvs = [s["cv"] for _, s in entries if s["cv"] is not None]
            position_avg_cv[pos] = sum(cvs) / len(cvs) if cvs else None

        # Team average weights by how many players actually had a CV, not
        # by position, so a position with more starters (RB/WR via FLEX)
        # naturally counts more toward the team's overall volatility.
        flat_cvs = [
            s["cv"] for entries in by_position.values() for _, s in entries if s["cv"] is not None
        ]
        team_avg_cv = sum(flat_cvs) / len(flat_cvs) if flat_cvs else None

        team_rows.append((team_avg_cv, team_name, by_position, position_avg_cv))

    # Most consistent (lowest avg CV) first; teams with no data sort last.
    team_rows.sort(key=lambda r: (r[0] is None, r[0]))

    all_positions = sorted(
        {pos for _, _, by_position, _ in team_rows for pos in by_position},
        key=lambda p: POSITION_ORDER.index(p) if p in POSITION_ORDER else len(POSITION_ORDER),
    )

    lines = []
    lines.append(f"STARTER CONSISTENCY BY POSITION (based on {prev_season} actual game logs)")
    lines.append("Coefficient of variation (CV = stdev / mean) of each starter's points per game played.")
    lines.append("Lower CV = more consistent week to week. Higher CV = more boom/bust.")
    lines.append("Teams sorted most consistent (lowest average starter CV) to least.")
    lines.append("")

    header = f"  {'TEAM':<20} {'AVG CV':>8} " + " ".join(f"{pos:>8}" for pos in all_positions)
    lines.append(header)
    for team_avg_cv, team_name, _, position_avg_cv in team_rows:
        avg_str = f"{team_avg_cv:.2f}" if team_avg_cv is not None else "n/a"
        row = f"  {team_name:<20} {avg_str:>8} " + " ".join(
            f"{position_avg_cv.get(pos):.2f}" if position_avg_cv.get(pos) is not None else "    n/a"
            for pos in all_positions
        )
        lines.append(row)

    lines.append("")
    lines.append("LEAGUE AVERAGE CV BY POSITION (across all teams' starters)")
    for pos in all_positions:
        cvs = league_cvs_by_position.get(pos, [])
        avg = sum(cvs) / len(cvs) if cvs else None
        lines.append(f"  {pos:<6} {avg:.2f}" if avg is not None else f"  {pos:<6} n/a")

    lines.append("")
    lines.append("PER-TEAM STARTER DETAIL (games played, mean pts, stdev, CV)")
    for team_avg_cv, team_name, by_position, position_avg_cv in team_rows:
        avg_str = f"{team_avg_cv:.2f}" if team_avg_cv is not None else "n/a"
        lines.append("")
        lines.append(f"{team_name} (avg starter CV: {avg_str})")
        for pos in all_positions:
            entries = by_position.get(pos)
            if not entries:
                continue
            pos_avg = position_avg_cv.get(pos)
            pos_avg_str = f"{pos_avg:.2f}" if pos_avg is not None else "n/a"
            lines.append(f"  {pos} (avg CV: {pos_avg_str})")
            for name, stats in sorted(
                entries, key=lambda e: (e[1]["cv"] is None, -(e[1]["cv"] or 0))
            ):
                if stats["cv"] is not None:
                    lines.append(
                        f"      {name:<25} games={stats['games']:>2}  "
                        f"mean={stats['mean']:6.1f}  stdev={stats['stdev']:6.1f}  cv={stats['cv']:.2f}"
                    )
                else:
                    lines.append(
                        f"      {name:<25} games={stats['games']:>2}  "
                        f"(not enough {prev_season} data for a CV - rookie or missed the season)"
                    )

    path = write_output("variance_by_position.txt", "\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
