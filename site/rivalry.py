"""
Builds the "Rivalry Week" brief shown at the top of a rivalry-week page:
each rivalry's all-time head-to-head record and average margin of victory.

Rivals are whoever is matched up in the rivalry week itself (each pair
plays twice a season - the other meeting is week 1). History walks the
league's previous_league_id chain back to the first season and counts
every meeting: regular season plus playoff / consolation bracket games.
Past seasons' rosters are tied to managers by owner_id, which is stable
across seasons.
"""

from __future__ import annotations

from generate import USERNAME_TO_FIRST_NAME, esc, render_avatar


def _season_games(client, league: dict, owner_to_username: dict) -> list[tuple[str, float, str, float]]:
    """[(username_a, pts_a, username_b, pts_b), ...] for every completed
    meeting in one season of the league."""
    lid = league["league_id"]
    playoff_start = league["settings"]["playoff_week_start"]
    rid_to_username = {
        r["roster_id"]: owner_to_username.get(r["owner_id"])
        for r in client.get(f"league/{lid}/rosters")
    }

    complete = league["status"] == "complete"
    last_reg_week = playoff_start - 1 if complete else league["settings"].get("last_scored_leg", 0)

    games = []
    for week in range(1, min(playoff_start - 1, last_reg_week) + 1):
        by_matchup: dict[int, list[dict]] = {}
        for m in client.get(f"league/{lid}/matchups/{week}"):
            if m.get("matchup_id"):
                by_matchup.setdefault(m["matchup_id"], []).append(m)
        for pair in by_matchup.values():
            if len(pair) == 2:
                a, b = pair
                games.append((rid_to_username[a["roster_id"]], a["points"], rid_to_username[b["roster_id"]], b["points"]))

    if complete:
        points: dict[tuple[int, int], float] = {}
        for week in range(playoff_start, 19):
            matchups = client.get(f"league/{lid}/matchups/{week}")
            if not matchups:
                break
            for m in matchups:
                points[(week, m["roster_id"])] = m["points"]
        for bracket in ("winners_bracket", "losers_bracket"):
            for game in client.get(f"league/{lid}/{bracket}"):
                t1, t2 = game.get("t1"), game.get("t2")
                if not (isinstance(t1, int) and isinstance(t2, int)):
                    continue
                week = playoff_start + game["r"] - 1
                if (week, t1) in points and (week, t2) in points:
                    games.append((rid_to_username[t1], points[(week, t1)], rid_to_username[t2], points[(week, t2)]))

    return games


def all_time_games(client, owner_to_username: dict) -> list[tuple[str, float, str, float]]:
    games = []
    league = client.get_league()
    while True:
        games.extend(_season_games(client, league, owner_to_username))
        prev_id = league.get("previous_league_id")
        if not prev_id or prev_id == "0":
            break
        league = client.get(f"league/{prev_id}")
    return games


def head_to_head(games: list, a: str, b: str) -> dict:
    wins = {a: 0, b: 0}
    margins = {a: [], b: []}
    for x, x_pts, y, y_pts in games:
        if {x, y} != {a, b} or x_pts == y_pts:
            continue
        winner, margin = (x, x_pts - y_pts) if x_pts > y_pts else (y, y_pts - x_pts)
        wins[winner] += 1
        margins[winner].append(margin)
    all_margins = margins[a] + margins[b]
    return {
        "wins": wins,
        "avg_margin": sum(all_margins) / len(all_margins) if all_margins else None,
    }


def render_rivalry_side(info: dict, wins: int, leads: bool) -> str:
    nickname = info.get("nickname", "—")
    avatar_html = render_avatar(info.get("avatar_url"), nickname, "avatar-sm")
    cls = "score-side score-side-win" if leads else "score-side"
    return (
        f'<div class="{cls}">{avatar_html}'
        f'<span class="score-side-name">{esc(nickname)}</span>'
        f'<span class="score-side-pts">{wins}</span></div>'
    )


def render_rivalry_section(
    client, config: dict, rivalry_matchups: list[dict], team_lookup: dict, ranked_first_names: list[str],
) -> str:
    owner_to_username = config["teams"]["ids"]
    roster_id_to_username = {v["roster_id"]: k for k, v in team_lookup.items()}
    games = all_time_games(client, owner_to_username)

    by_matchup: dict[int, list[str]] = {}
    for m in rivalry_matchups:
        by_matchup.setdefault(m["matchup_id"], []).append(roster_id_to_username[m["roster_id"]])

    def rank_of(username: str) -> int:
        first = USERNAME_TO_FIRST_NAME.get(username)
        return ranked_first_names.index(first) if first in ranked_first_names else len(ranked_first_names)

    # Higher-ranked team on top, rivalries ordered by their best-ranked team.
    pairs = [sorted(p, key=rank_of) for p in by_matchup.values() if len(p) == 2]
    pairs.sort(key=lambda p: rank_of(p[0]))

    rows = []
    for a, b in pairs:
        h2h = head_to_head(games, a, b)
        wa, wb = h2h["wins"][a], h2h["wins"][b]
        margin = f'{h2h["avg_margin"]:.1f}' if h2h["avg_margin"] is not None else "—"
        rows.append(
            '<div class="score-game">'
            f'{render_rivalry_side(team_lookup.get(a, {}), wa, wa > wb)}'
            f'{render_rivalry_side(team_lookup.get(b, {}), wb, wb > wa)}'
            f'<div class="rivalry-margin">Avg margin of victory <span>{margin}</span></div>'
            '</div>'
        )

    return f"""
    <section class="brief-section">
      <h2 class="brief-title">Rivalry Week · All-Time Head to Head</h2>
      <p class="rivalry-intro">Rivals play twice every season and everyone else once. Records go back to 2024 and include playoff and consolation meetings.</p>
      <div class="score-grid">{"".join(rows)}</div>
    </section>"""
