"""
A plain-text worksheet for manually deciding the power-ranking order:
each team's starting-lineup projected points (bye-subs included, see
01_season_projections.py) plus the actual starting lineup by slot, so you
can eyeball roster construction next to the raw projection number.

This intentionally leaves out full bench/depth and average age - it's meant
to be a quick, readable pass. See season_projections.txt,
bench_points_by_position.txt, and avg_age_by_team.txt for those.

Also writes a second, compact one-row-per-team version (same data, each
starter's slot as a column) for quick side-by-side reference.

Output: outputs/ranking_worksheet.txt, outputs/ranking_table.txt
"""

from __future__ import annotations

from collections import defaultdict

from common import (
    effective_starter_points,
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

    weekly_points, season_totals = get_weekly_points(client, season, weeks, positions, pts_field)

    team_rows = []
    for roster in rosters:
        owner_id = roster.get("owner_id")
        team_name = config_teams.get(owner_id, owner_id or "UNCLAIMED")

        starter_total, _, subs_log = effective_starter_points(
            roster, roster_positions, weeks, weekly_points, players
        )
        bye_slots = {sub["slot"] for sub in subs_log}

        lineup = []
        for slot, pid in starter_slots(roster, roster_positions):
            info = players.get(pid, {})
            name = info.get("full_name") or pid
            proj = season_totals.get(pid, 0.0)
            has_bye_sub = slot in bye_slots
            lineup.append((slot, name, proj, has_bye_sub))

        team_rows.append((starter_total, team_name, lineup))

    team_rows.sort(key=lambda r: r[0], reverse=True)

    lines = []
    lines.append(f"RANKING WORKSHEET ({season}, starting-lineup projections, weeks 1-{playoff_week_start - 1})")
    lines.append("Sorted by projected starting-lineup points, highest first.")
    lines.append("This is a starting point, not the ranking - use it to help decide the order.")
    lines.append("")

    for rank, (starter_total, team_name, lineup) in enumerate(team_rows, start=1):
        lines.append(f"{rank:>2}. {team_name}  -  {starter_total:.1f} projected pts")
        for slot, name, proj, has_bye_sub in lineup:
            bye_note = "  (bye wk sub used later this season)" if has_bye_sub else ""
            lines.append(f"      {slot:<10} {name:<25} {proj:6.1f}{bye_note}")
        lines.append("")

    path = write_output("ranking_worksheet.txt", "\n".join(lines) + "\n")
    print(f"Wrote {path}")

    # Compact one-row-per-team table, same slot order for every team since
    # roster_positions is fixed league-wide. Duplicate slot types (RB, WR)
    # get numbered so the header stays distinct (RB1/RB2, WR1/WR2, ...).
    slot_order = [slot for slot, *_ in team_rows[0][2]] if team_rows else []
    slot_counts = defaultdict(int)
    for slot in slot_order:
        slot_counts[slot] += 1
    seen = defaultdict(int)
    column_labels = []
    for slot in slot_order:
        if slot_counts[slot] > 1:
            seen[slot] += 1
            column_labels.append(f"{slot}{seen[slot]}")
        else:
            column_labels.append(slot)

    col_width = 22
    table_lines = []
    table_lines.append(f"RANKING TABLE ({season}, starting-lineup projections, weeks 1-{playoff_week_start - 1})")
    table_lines.append("Sorted by projected starting-lineup points, highest first. Compact companion to ranking_worksheet.txt.")
    table_lines.append("")
    header = f"{'#':>3}  {'TEAM':<20} {'PROJ':>8}  " + "  ".join(f"{c:<{col_width}}" for c in column_labels)
    table_lines.append(header)
    table_lines.append("-" * len(header))
    for rank, (starter_total, team_name, lineup) in enumerate(team_rows, start=1):
        cells = "  ".join(f"{name:<{col_width}}" for _, name, _, _ in lineup)
        table_lines.append(f"{rank:>3}  {team_name:<20} {starter_total:8.1f}  {cells}")

    table_path = write_output("ranking_table.txt", "\n".join(table_lines) + "\n")
    print(f"Wrote {table_path}")


if __name__ == "__main__":
    main()
