"""
"What if every team had started its best possible lineup all season?"

Compares each team's actual current starters (by season-total projected
points, no bye-week substitution layer here - see 01_season_projections.py
for that) against the optimal static lineup: the season-total-maximizing
assignment of that team's own roster to its roster slots.

This exists to check for roster-construction mistakes - e.g. a bench
player projected higher than the guy actually starting at that slot - as
opposed to bad luck (injuries, byes). If actual == optimal, the manager is
already starting their best lineup and any gap to another team is just
roster strength, not a lineup-setting mistake.

Output: outputs/optimal_lineup.txt
"""

from __future__ import annotations

from common import (
    get_client,
    get_weekly_points,
    load_config,
    load_players,
    optimal_lineup,
    points_field,
    required_positions,
    starter_slots,
    team_name_lookup,
    write_output,
)


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
    for roster in rosters:
        owner_id = roster.get("owner_id")
        team_name = config_teams.get(owner_id, owner_id or "UNCLAIMED")
        player_ids = roster.get("players") or []

        actual_slots = starter_slots(roster, roster_positions)
        actual_total = sum(season_totals.get(pid, 0.0) for _, pid in actual_slots)
        actual_by_slot = {}
        seen_counts = {}
        for slot, pid in actual_slots:
            seen_counts[slot] = seen_counts.get(slot, 0) + 1
            actual_by_slot[(slot, seen_counts[slot])] = pid

        optimal_total, optimal_assignments = optimal_lineup(
            roster_positions, player_ids, season_totals, players
        )

        diffs = []
        seen_counts = {}
        for slot, pid in optimal_assignments:
            seen_counts[slot] = seen_counts.get(slot, 0) + 1
            actual_pid = actual_by_slot.get((slot, seen_counts[slot]))
            if pid != actual_pid:
                diffs.append((slot, actual_pid, pid))

        team_rows.append((optimal_total - actual_total, actual_total, optimal_total, team_name, diffs))

    team_rows.sort(key=lambda r: r[0], reverse=True)

    lines = []
    lines.append(f"OPTIMAL vs. ACTUAL STARTING LINEUP ({season}, season-total projected points)")
    lines.append("Sorted by points left on the table (optimal - actual), highest first.")
    lines.append("")
    header = f"  {'TEAM':<20} {'ACTUAL':>8} {'OPTIMAL':>8} {'LEFT ON TABLE':>14}"
    lines.append(header)
    for gap, actual_total, optimal_total, team_name, _ in team_rows:
        lines.append(f"  {team_name:<20} {actual_total:8.1f} {optimal_total:8.1f} {gap:14.1f}")

    lines.append("")
    lines.append("SUGGESTED SWAPS (where the optimal lineup differs from the actual starters)")
    lines.append("Teams with ~0 pts available are omitted - any 'diff' there is just two starters")
    lines.append("relabeled between identical slots (e.g. WR1/WR2), not an actual lineup change.")
    for gap, actual_total, optimal_total, team_name, diffs in team_rows:
        if not diffs or gap < 0.1:
            continue
        lines.append("")
        lines.append(f"{team_name} (+{gap:.1f} pts available)")
        for slot, actual_pid, optimal_pid in diffs:
            actual_name = (players.get(actual_pid) or {}).get("full_name", actual_pid) if actual_pid else "(empty)"
            optimal_name = (players.get(optimal_pid) or {}).get("full_name", optimal_pid) if optimal_pid else "(empty)"
            actual_pts = season_totals.get(actual_pid, 0.0) if actual_pid else 0.0
            optimal_pts = season_totals.get(optimal_pid, 0.0) if optimal_pid else 0.0
            lines.append(
                f"  {slot:<10} {actual_name:<22} {actual_pts:6.1f}  ->  "
                f"{optimal_name:<22} {optimal_pts:6.1f}"
            )

    path = write_output("optimal_lineup.txt", "\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
