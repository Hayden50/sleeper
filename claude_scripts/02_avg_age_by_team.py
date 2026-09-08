"""
requests.txt #2: Average age of players on each team - split between
starters and bench players.

"Starters" = roster["starters"] (the currently set starting lineup).
"Bench" = everyone else on the active roster, excluding taxi squad and IR,
since those aren't really "bench" in the depth-chart sense.

Players with no age on file (team defenses, and any player Sleeper hasn't
back-filled birth data for) are excluded from the average and called out
separately so they don't silently skew the numbers.

Output: output_data/avg_age_by_team.txt
"""

from __future__ import annotations

from common import get_client, load_config, load_players, team_name_lookup, write_output


def avg_age(player_ids: list[str], players: dict) -> tuple[float | None, list[str]]:
    ages = []
    missing = []
    for pid in player_ids:
        age = (players.get(pid) or {}).get("age")
        if age is None:
            missing.append(pid)
        else:
            ages.append(age)
    if not ages:
        return None, missing
    return sum(ages) / len(ages), missing


def main():
    client = get_client()
    config_teams = team_name_lookup(load_config())

    rosters = client.get_rosters()
    players = load_players(client)

    rows = []
    for roster in rosters:
        owner_id = roster.get("owner_id")
        team_name = config_teams.get(owner_id, owner_id or "UNCLAIMED")

        starters = roster.get("starters") or []
        taxi = set(roster.get("taxi") or [])
        reserve = set(roster.get("reserve") or [])  # IR
        all_players = roster.get("players") or []
        bench = [
            pid for pid in all_players
            if pid not in set(starters) and pid not in taxi and pid not in reserve
        ]

        starter_avg, starter_missing = avg_age(starters, players)
        bench_avg, bench_missing = avg_age(bench, players)

        rows.append({
            "team": team_name,
            "starter_avg": starter_avg,
            "starter_n": len(starters) - len(starter_missing),
            "bench_avg": bench_avg,
            "bench_n": len(bench) - len(bench_missing),
            "missing": starter_missing + bench_missing,
        })

    rows.sort(key=lambda r: (r["starter_avg"] is None, r["starter_avg"]))

    def fmt(v):
        return f"{v:5.1f}" if v is not None else "  n/a"

    lines = []
    lines.append("AVERAGE PLAYER AGE BY TEAM (starters vs. bench)")
    lines.append("Bench excludes taxi squad and IR. Team defenses have no age on file and are excluded.")
    lines.append("")
    header = f"{'TEAM':<20} {'STARTERS':>10} {'(n)':>5} {'BENCH':>10} {'(n)':>5}"
    lines.append(header)
    lines.append("-" * len(header))
    for r in rows:
        lines.append(
            f"{r['team']:<20} {fmt(r['starter_avg']):>10} {r['starter_n']:>5} "
            f"{fmt(r['bench_avg']):>10} {r['bench_n']:>5}"
        )
        if r["missing"]:
            names = [
                (players.get(pid) or {}).get("full_name", pid)
                for pid in r["missing"]
            ]
            lines.append(f"    (no age on file, excluded: {', '.join(names)})")

    path = write_output("avg_age_by_team.txt", "\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
