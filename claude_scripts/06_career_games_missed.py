"""
Average games missed per season over a player's recent career, for every
rostered player (starters, bench, taxi, IR - the whole roster).

For each player, looks back over their most recent completed NFL seasons
(capped at CAREER_LOOKBACK_SEASONS) and counts, per season, 17 minus the
number of games they actually recorded a stat line for (using the same
"did they really play" logic as 05_variance_by_position.py / common.py's
load_game_log - presence of the scoring field, not Sleeper's unreliable
gms_active flag). Averaging over their own career length (via years_exp)
means a 3rd-year player's average is only over 3 seasons.

Notes / assumptions:
- Capped to the last 5 completed seasons (2021-2025 as of this run) for two
  reasons: API cost (each extra season is ~18 more requests), and every one
  of those seasons is a uniform 17-game/18-week schedule, so "games
  possible" per season can just be a constant 17 with no per-team bye-week
  lookup needed. A 10+ year veteran's rookie-year injuries aren't counted.
- Which seasons count is driven by the player catalog's years_exp (number
  of completed NFL seasons). Rookies (years_exp == 0) have no career data
  yet and are reported separately as N/A, not silently dropped.
- A player who wasn't on an NFL roster in a given season (didn't exist in
  that season's data at all) is different from one who was on a roster but
  inactive every week - years_exp is what prevents mixing these up; without
  it, a young player's pre-draft years would wrongly count as 17 missed
  games per year.
- This intentionally doesn't try to distinguish *why* games were missed
  (injury vs. suspension vs. healthy scratch vs. trade limbo) - it's total
  missed games, since Sleeper doesn't expose a reliable per-week reason.

Output: outputs/career_games_missed.txt
"""

from __future__ import annotations

from common import (
    get_client,
    load_config,
    load_game_log,
    load_players,
    points_field,
    required_positions,
    team_name_lookup,
    write_output,
)

CAREER_LOOKBACK_SEASONS = 5
GAMES_PER_SEASON = 17  # true for every season in the lookback window (2021+)


def main():
    client = get_client()
    config_teams = team_name_lookup(load_config())

    league = client.get_league()
    positions = required_positions(league["roster_positions"])
    pts_field = points_field(league["scoring_settings"])

    state = client.get_nfl_state()
    last_completed_season = int(state["previous_season"])
    all_seasons = [last_completed_season - i for i in range(CAREER_LOOKBACK_SEASONS)]

    rosters = client.get_rosters()
    players = load_players(client)

    # Which fantasy team owns each rostered player_id.
    owner_of = {}
    for roster in rosters:
        owner_id = roster.get("owner_id")
        team_name = config_teams.get(owner_id, owner_id or "UNCLAIMED")
        for pid in roster.get("players") or []:
            owner_of[pid] = team_name

    rostered_ids = set(owner_of)

    # Only fetch seasons that at least one rostered player actually needs.
    needed_seasons = set()
    for pid in rostered_ids:
        years_exp = (players.get(pid) or {}).get("years_exp") or 0
        n = min(years_exp, CAREER_LOOKBACK_SEASONS)
        needed_seasons.update(all_seasons[:n])

    game_logs = {
        season: load_game_log(client, season, range(1, 19), positions, pts_field)
        for season in sorted(needed_seasons, reverse=True)
    }

    rows = []
    no_career_data = []
    for pid in rostered_ids:
        info = players.get(pid, {})
        name = info.get("full_name") or pid
        pos = info.get("position") or "?"
        years_exp = info.get("years_exp") or 0
        n = min(years_exp, CAREER_LOOKBACK_SEASONS)
        seasons = all_seasons[:n]

        if not seasons:
            no_career_data.append((owner_of[pid], name, pos))
            continue

        per_season = []
        total_missed = 0
        for season in seasons:
            played = len(game_logs[season].get(pid, []))
            missed = GAMES_PER_SEASON - played
            per_season.append((season, played, missed))
            total_missed += missed

        avg_missed = total_missed / len(seasons)
        rows.append((avg_missed, owner_of[pid], name, pos, years_exp, per_season, total_missed))

    rows.sort(key=lambda r: r[0], reverse=True)

    lines = []
    lines.append(
        f"CAREER GAMES MISSED PER SEASON (last {CAREER_LOOKBACK_SEASONS} completed seasons, "
        f"{min(all_seasons)}-{max(all_seasons)}, {GAMES_PER_SEASON} games/season)"
    )
    lines.append("Every rostered player (starters, bench, taxi, IR). Sorted most games missed/season first.")
    lines.append("")
    header = f"  {'PLAYER':<25} {'POS':<4} {'TEAM':<20} {'YRS':>4} {'SSNS':>5} {'AVG MISSED':>11} {'TOTAL MISSED':>13}"
    lines.append(header)
    lines.append("-" * len(header))
    for avg_missed, team_name, name, pos, years_exp, per_season, total_missed in rows:
        lines.append(
            f"  {name:<25} {pos:<4} {team_name:<20} {years_exp:>4} {len(per_season):>5} "
            f"{avg_missed:>11.1f} {total_missed:>13}"
        )

    lines.append("")
    lines.append(
        f"NO CAREER DATA YET (rookies, and team defenses which have no individual "
        f"years_exp - years_exp = 0, {len(no_career_data)} players)"
    )
    for team_name, name, pos in sorted(no_career_data, key=lambda r: (r[0], r[1])):
        lines.append(f"  {name:<25} {pos:<4} {team_name}")

    lines.append("")
    lines.append("PER-PLAYER SEASON DETAIL (played / missed, out of 17 each season)")
    for avg_missed, team_name, name, pos, years_exp, per_season, total_missed in rows:
        detail = ", ".join(f"{s}: {played}p/{missed}m" for s, played, missed in per_season)
        lines.append(f"  {name:<25} {pos:<4} {team_name:<20} {detail}")

    path = write_output("career_games_missed.txt", "\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
