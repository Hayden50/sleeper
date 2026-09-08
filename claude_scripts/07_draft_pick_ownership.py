"""
Future draft pick ownership - reference / fact-checking data only.

This is NOT meant to feed team-strength/power-ranking judgments (this
power ranking is scoped to the current season); it's here so pick-related
claims in the writeup ("still has all his picks", "missing his 1st",
"4 firsts next year") can be checked against the actual data instead of
memory.

get_traded_picks() only returns picks that have moved at least once, and
only reports their *current* owner (not the full trade chain), so: for
every (season, round, original roster) combination, the default owner is
that roster itself unless a traded_picks entry overrides it.

Only seasons *after* the league's current season are shown - the current
season's rookie draft has already happened (see output_data/*_rookie_draft
.txt), so pick data for it is moot/stale, not a "future" pick anymore.
That leaves a 2-year forward window (e.g. 2027-2028 as of the 2026
season), matching what's actually tradeable in this league right now.

Output: outputs/draft_pick_ownership.txt
"""

from __future__ import annotations

from collections import defaultdict

from common import get_client, load_config, team_name_lookup, write_output


def main():
    client = get_client()
    config_teams = team_name_lookup(load_config())

    league = client.get_league()
    draft_rounds = league["settings"]["draft_rounds"]
    current_season = int(league["season"])

    rosters = client.get_rosters()
    roster_team = {}
    for roster in rosters:
        owner_id = roster.get("owner_id")
        roster_team[roster["roster_id"]] = config_teams.get(owner_id, owner_id or "UNCLAIMED")

    traded_picks = client.get_traded_picks()
    # Current season's draft already happened; only future seasons are
    # real "picks", not the ones already spent. Always show at least the
    # next 2 years even if a given year has no trades yet.
    future_seasons_with_trades = {int(p["season"]) for p in traded_picks if int(p["season"]) > current_season}
    seasons = sorted({current_season + 1, current_season + 2} | future_seasons_with_trades)

    # (season, round, original_roster_id) -> current_owner_roster_id
    current_owner = {}
    for p in traded_picks:
        key = (int(p["season"]), p["round"], p["roster_id"])
        current_owner[key] = p["owner_id"]

    # roster_id -> season -> [(round, current_owner_roster_id or None if own)]
    owned_by_team = defaultdict(lambda: defaultdict(list))  # what each team currently holds
    traded_away_by_team = defaultdict(lambda: defaultdict(list))  # original picks they gave up

    for season in seasons:
        for round_ in range(1, draft_rounds + 1):
            for roster_id in roster_team:
                owner = current_owner.get((season, round_, roster_id), roster_id)
                owned_by_team[owner][season].append((round_, roster_id))
                if owner != roster_id:
                    traded_away_by_team[roster_id][season].append((round_, owner))

    lines = []
    lines.append("FUTURE DRAFT PICK OWNERSHIP (reference / fact-checking only - not a ranking input)")
    lines.append(f"Seasons: {', '.join(str(s) for s in seasons)}  |  Rounds per draft: {draft_rounds}")
    lines.append("")

    for roster_id in sorted(roster_team, key=lambda rid: roster_team[rid]):
        team_name = roster_team[roster_id]
        lines.append(f"{team_name}")

        for season in seasons:
            owned = sorted(owned_by_team[roster_id][season])
            parts = []
            for round_, original_roster_id in owned:
                if original_roster_id == roster_id:
                    parts.append(f"{round_}")
                else:
                    parts.append(f"{round_} (from {roster_team[original_roster_id]})")
            picks_str = ", ".join(parts) if parts else "none"
            lines.append(f"  {season}: {picks_str}")

        traded_away = traded_away_by_team[roster_id]
        if any(traded_away[s] for s in seasons):
            away_bits = []
            for season in seasons:
                for round_, new_owner_roster_id in sorted(traded_away[season]):
                    away_bits.append(f"{season} rd{round_} -> {roster_team[new_owner_roster_id]}")
            lines.append(f"  traded away: {'; '.join(away_bits)}")

        lines.append("")

    path = write_output("draft_pick_ownership.txt", "\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
