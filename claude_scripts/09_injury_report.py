"""
Injury report for every rostered player across all fantasy teams: anyone
with a non-empty Sleeper injury_status (Questionable, Doubtful, Out, IR,
PUP, etc.) as of the most recent player-catalog refresh.

Sleeper's player catalog carries a single current injury_status per player
(not a per-week history), so this is a snapshot of "who is banged up right
now" rather than a week-by-week log - it reflects whatever the most recent
practice/game report set, whether that came out of Week 1 or off a practice
report since.

Output: outputs/injury_report.txt
"""

from __future__ import annotations

from common import get_client, load_config, load_players, team_name_lookup, write_output

# Rough severity ordering for grouping, most fantasy-relevant first.
STATUS_ORDER = ["Out", "Doubtful", "Questionable", "PUP", "IR", "NA", "COV"]


def status_rank(status: str) -> tuple[int, str]:
    if status in STATUS_ORDER:
        return (STATUS_ORDER.index(status), status)
    return (len(STATUS_ORDER), status)


def main():
    client = get_client()
    config_teams = team_name_lookup(load_config())

    rosters = client.get_rosters()
    players = load_players(client)

    owner_of = {}
    for roster in rosters:
        owner_id = roster.get("owner_id")
        team_name = config_teams.get(owner_id, owner_id or "UNCLAIMED")
        for pid in roster.get("players") or []:
            owner_of[pid] = team_name

    rows = []
    for pid, team_name in owner_of.items():
        info = players.get(pid) or {}
        status = info.get("injury_status")
        if not status:
            continue
        rows.append({
            "team": team_name,
            "name": info.get("full_name") or pid,
            "pos": info.get("position") or "?",
            "nfl_team": info.get("team") or "FA",
            "status": status,
            "body_part": info.get("injury_body_part") or "",
            "notes": info.get("injury_notes") or "",
            "practice": info.get("practice_participation") or "",
            "practice_desc": info.get("practice_description") or "",
        })

    rows.sort(key=lambda r: (status_rank(r["status"]), r["team"], r["name"]))

    lines = []
    lines.append("FANTASY LEAGUE INJURY REPORT")
    lines.append(
        f"{len(rows)} rostered players carrying a current Sleeper injury_status "
        f"(snapshot as of the latest player-catalog refresh)."
    )
    lines.append("")

    header = f"  {'PLAYER':<24} {'POS':<4} {'NFL':<4} {'FANTASY TEAM':<20} {'STATUS':<12} {'INJURY':<20} PRACTICE"
    for status in STATUS_ORDER + sorted({r["status"] for r in rows} - set(STATUS_ORDER)):
        group = [r for r in rows if r["status"] == status]
        if not group:
            continue
        lines.append(f"=== {status.upper()} ({len(group)}) ===")
        lines.append(header)
        lines.append("-" * len(header))
        for r in group:
            practice = r["practice"]
            if r["practice_desc"]:
                practice = f"{practice} - {r['practice_desc']}" if practice else r["practice_desc"]
            lines.append(
                f"  {r['name']:<24} {r['pos']:<4} {r['nfl_team']:<4} {r['team']:<20} "
                f"{r['status']:<12} {r['body_part']:<20} {practice}"
            )
            if r["notes"]:
                lines.append(f"      note: {r['notes']}")
        lines.append("")

    lines.append("PER FANTASY TEAM")
    for team_name in sorted(set(config_teams.values())):
        team_rows = [r for r in rows if r["team"] == team_name]
        if not team_rows:
            continue
        lines.append(f"  {team_name} ({len(team_rows)}):")
        for r in sorted(team_rows, key=lambda r: status_rank(r["status"])):
            lines.append(f"    {r['name']:<24} {r['pos']:<4} {r['status']:<12} {r['body_part']}")

    path = write_output("injury_report.txt", "\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
