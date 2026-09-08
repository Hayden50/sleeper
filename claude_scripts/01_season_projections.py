"""
requests.txt #1: Projected points over the whole season.

Sums Sleeper's weekly per-player projections (an undocumented endpoint, see
SleeperClient.get_projections) across every regular-season week for every
player currently on a roster, then rolls that up to a per-team total. Also
breaks out the subtotal for just the starting lineup, since bench depth
doesn't actually score points.

The starting-lineup subtotal accounts for bye weeks: for each week, if a
starter is missing from that week's projections (Sleeper doesn't project
players who aren't playing, i.e. on bye), the bench player at the same
roster slot with the highest projection *for that week* is substituted in.
This is recomputed independently per week, so different bench players can
fill a bye'd slot in different weeks.

Notes / assumptions:
- "Whole season" = the regular season only (weeks 1 .. playoff_week_start-1),
  not the playoff weeks, since that's what decides standings/seeding.
- "Starting lineup" = roster["starters"] as currently set in Sleeper today
  (with bye-week substitutions applied); it is NOT an optimal/best-ball
  lineup and will drift as rosters/starters change week to week.
- A starter's roster slot (QB / RB / FLEX / SUPER_FLEX / etc.) is inferred
  by zipping roster["starters"] against the league's roster_positions,
  since Sleeper returns starters in that positional order.
- A bench player who is themselves on bye that week is not eligible as a
  sub that week. If no eligible bench player exists, the slot scores 0.
- One bench player can't fill two bye'd slots in the same week; slots are
  filled in roster_positions order, so an earlier slot gets first pick of
  the best available bench player.
- The scoring format (std / half-ppr / full-ppr) is read from the league's
  scoring_settings so the right projection column is used.
- Sleeper's projections are generic (rotowire, etc.) and won't reflect this
  league's exact custom scoring categories (return yards, bonuses, etc.),
  just the standard stat categories.

Output: outputs/season_projections.txt
"""

from __future__ import annotations

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
        player_ids = roster.get("players") or []
        original_starter_ids = {pid for _, pid in starter_slots(roster, roster_positions)}

        starter_total, starter_player_totals, subs_log = effective_starter_points(
            roster, roster_positions, weeks, weekly_points, players
        )
        subbed_in_ids = set(starter_player_totals) - original_starter_ids

        player_rows = []
        team_total = 0.0
        for pid in player_ids:
            proj = season_totals.get(pid, 0.0)
            team_total += proj
            info = players.get(pid, {})
            name = info.get("full_name") or pid
            pos = info.get("position") or "?"
            is_original_starter = pid in original_starter_ids
            player_rows.append((proj, name, pos, is_original_starter, pid in subbed_in_ids))

        player_rows.sort(key=lambda r: r[0], reverse=True)
        team_rows.append((team_total, starter_total, team_name, player_rows, subs_log))

    team_rows.sort(key=lambda r: r[0], reverse=True)

    lines = []
    lines.append(f"SEASON PROJECTED POINTS ({season}, weeks 1-{playoff_week_start - 1})")
    lines.append(f"Scoring column used: {pts_field}")
    lines.append("")
    lines.append("TEAM TOTALS  (full roster vs. starting lineup w/ bye subs)")
    header = f"  {'TEAM':<20} {'ROSTER':>8} {'STARTERS':>10}"
    lines.append(header)
    for total, starter_total, team_name, _, _ in team_rows:
        lines.append(f"  {team_name:<20} {total:8.1f} {starter_total:10.1f}")

    lines.append("")
    lines.append("PER-TEAM ROSTER BREAKDOWN  (* = current starter, + = bye-week bench sub at some point)")
    for total, starter_total, team_name, player_rows, subs_log in team_rows:
        lines.append("")
        lines.append(f"{team_name} (roster: {total:.1f} pts, starters w/ bye subs: {starter_total:.1f} pts)")
        for proj, name, pos, is_original_starter, was_subbed_in in player_rows:
            marker = "*" if is_original_starter else ("+" if was_subbed_in else " ")
            lines.append(f"  {marker} {pos:<4} {name:<25} {proj:6.1f}")

        if subs_log:
            lines.append("  bye-week substitutions:")
            for sub in subs_log:
                out_name = (players.get(sub["out_id"]) or {}).get("full_name", sub["out_id"])
                in_name = (players.get(sub["in_id"]) or {}).get("full_name", sub["in_id"])
                lines.append(
                    f"    week {sub['week']:>2}  {sub['slot']:<10} "
                    f"{out_name} (BYE) -> {in_name} ({sub['in_pts']:.1f})"
                )

    path = write_output("season_projections.txt", "\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
