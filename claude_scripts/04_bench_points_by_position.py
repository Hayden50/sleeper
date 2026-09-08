"""
requests.txt #3: Depth per position (bench points).

For each team, sums each bench player's full-season projected points
(same weekly projections as 01_season_projections.py) and groups the total
by position, so you can see where a team's depth actually is.

"Bench" = roster players minus starters, taxi squad, and IR (same
definition as 02_avg_age_by_team.py).

Output: outputs/bench_points_by_position.txt
"""

from __future__ import annotations

from collections import defaultdict

from common import (
    get_client,
    get_weekly_points,
    load_config,
    load_players,
    points_field,
    required_positions,
    starter_slots,
    team_name_lookup,
    write_output,
)

POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"]


def main():
    client = get_client()
    config_teams = team_name_lookup(load_config())

    league = client.get_league()
    season = league["season"]
    playoff_week_start = league["settings"]["playoff_week_start"]
    weeks = range(1, playoff_week_start)
    roster_positions = league["roster_positions"]
    positions = required_positions(roster_positions)
    pts_field = points_field(league["scoring_settings"])

    rosters = client.get_rosters()
    players = load_players(client)

    _, season_totals = get_weekly_points(client, season, weeks, positions, pts_field)

    team_rows = []
    league_by_position = defaultdict(float)

    for roster in rosters:
        owner_id = roster.get("owner_id")
        team_name = config_teams.get(owner_id, owner_id or "UNCLAIMED")

        starter_ids = {pid for _, pid in starter_slots(roster, roster_positions)}
        taxi = set(roster.get("taxi") or [])
        reserve = set(roster.get("reserve") or [])
        all_players = roster.get("players") or []
        bench_ids = [
            pid for pid in all_players
            if pid not in starter_ids and pid not in taxi and pid not in reserve
        ]

        by_position = defaultdict(float)
        players_by_position = defaultdict(list)
        for pid in bench_ids:
            info = players.get(pid, {})
            pos = info.get("position") or "?"
            proj = season_totals.get(pid, 0.0)
            by_position[pos] += proj
            league_by_position[pos] += proj
            players_by_position[pos].append((proj, info.get("full_name") or pid))

        bench_total = sum(by_position.values())
        team_rows.append((bench_total, team_name, by_position, players_by_position))

    team_rows.sort(key=lambda r: r[0], reverse=True)

    all_positions = sorted(
        {pos for _, _, by_position, _ in team_rows for pos in by_position},
        key=lambda p: POSITION_ORDER.index(p) if p in POSITION_ORDER else len(POSITION_ORDER),
    )

    lines = []
    lines.append(f"BENCH PROJECTED POINTS BY POSITION ({season}, weeks 1-{playoff_week_start - 1})")
    lines.append("Bench = roster players minus starters, taxi squad, and IR.")
    lines.append("")

    header = f"  {'TEAM':<20} {'TOTAL':>8} " + " ".join(f"{pos:>8}" for pos in all_positions)
    lines.append(header)
    for bench_total, team_name, by_position, _ in team_rows:
        row = f"  {team_name:<20} {bench_total:8.1f} " + " ".join(
            f"{by_position.get(pos, 0.0):8.1f}" for pos in all_positions
        )
        lines.append(row)

    lines.append("")
    lines.append("LEAGUE AVERAGE BENCH POINTS BY POSITION")
    n_teams = len(team_rows)
    for pos in all_positions:
        lines.append(f"  {pos:<6} {league_by_position[pos] / n_teams:8.1f}")

    lines.append("")
    lines.append("PER-TEAM BENCH BREAKDOWN (players behind each position, high to low)")
    for bench_total, team_name, by_position, players_by_position in team_rows:
        lines.append("")
        lines.append(f"{team_name} (bench total: {bench_total:.1f} pts)")
        for pos in all_positions:
            plist = sorted(players_by_position.get(pos, []), reverse=True)
            if not plist:
                continue
            lines.append(f"  {pos} ({by_position.get(pos, 0.0):.1f} pts)")
            for proj, name in plist:
                lines.append(f"      {name:<25} {proj:6.1f}")

    path = write_output("bench_points_by_position.txt", "\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
