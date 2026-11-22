"""
Builds the "Playoff Odds" brief shown at the top of a week page: for each
team, its chance to make the playoffs / earn a first-round bye if it wins
vs. loses its upcoming matchup.

Monte Carlo over the rest of the regular season. Each simulated week, every
team's score is drawn from a normal distribution fit to its own scores so
far (season mean / sample stdev). Standings are wins, then points for (PF)
as the tiebreaker. The top `playoff_teams` make it; the top 2 get byes.
"Win"/"Loss" odds are conditioned on the simulated result of the upcoming
week - so a win also tends to come with a higher score, like it would in
real life.

The seed is fixed and only completed weeks feed the model, so re-running
generate.py reproduces the same numbers for a given week.
"""

from __future__ import annotations

import random
import statistics

from generate import esc, render_avatar

SIMULATIONS = 50_000
SEED = 42
BYE_SPOTS = 2


def _pairs(matchups: list[dict]) -> list[list[dict]]:
    by_matchup: dict[int, list[dict]] = {}
    for m in matchups:
        by_matchup.setdefault(m["matchup_id"], []).append(m)
    return [v for v in by_matchup.values() if len(v) == 2]


def simulate(matchups_for, rosters: list[dict], league: dict, through_week: int) -> dict[int, dict]:
    """roster_id -> {"win": (playoff_pct, bye_pct), "loss": (...), "all": (...),
    "p_win": pct} for the week after `through_week`."""
    settings = league["settings"]
    last_reg_week = settings["playoff_week_start"] - 1
    playoff_teams = settings["playoff_teams"]
    rids = [r["roster_id"] for r in rosters]

    wins = {r: 0 for r in rids}
    pf = {r: 0.0 for r in rids}
    scores = {r: [] for r in rids}
    for week in range(1, through_week + 1):
        for a, b in _pairs(matchups_for(week)):
            for x in (a, b):
                pf[x["roster_id"]] += x["points"]
                scores[x["roster_id"]].append(x["points"])
            wins[(a if a["points"] > b["points"] else b)["roster_id"]] += 1

    mu = {r: statistics.mean(s) for r, s in scores.items()}
    sd = {r: statistics.stdev(s) for r, s in scores.items()}
    schedule = [
        [(a["roster_id"], b["roster_id"]) for a, b in _pairs(matchups_for(week))]
        for week in range(through_week + 1, last_reg_week + 1)
    ]
    if not schedule:
        return {}

    rng = random.Random(SEED)
    # counts[rid][cond] = [sims, made_playoffs, got_bye]
    counts = {r: {k: [0, 0, 0] for k in ("all", "win", "loss")} for r in rids}
    for _ in range(SIMULATIONS):
        w, p, first = dict(wins), dict(pf), {}
        for k, week in enumerate(schedule):
            s = {r: rng.gauss(mu[r], sd[r]) for r in rids}
            for r in rids:
                p[r] += s[r]
            for i, j in week:
                winner, loser = (i, j) if s[i] > s[j] else (j, i)
                w[winner] += 1
                if k == 0:
                    first[winner], first[loser] = "win", "loss"
        order = sorted(rids, key=lambda r: (w[r], p[r]), reverse=True)
        for pos, r in enumerate(order):
            for cond in ("all", first.get(r, "all")):
                c = counts[r][cond]
                c[0] += 1
                c[1] += pos < playoff_teams
                c[2] += pos < BYE_SPOTS

    def pct(c):
        return (100 * c[1] / c[0], 100 * c[2] / c[0]) if c[0] else (None, None)

    return {
        r: {
            "all": pct(counts[r]["all"]),
            "win": pct(counts[r]["win"]),
            "loss": pct(counts[r]["loss"]),
            "p_win": 100 * counts[r]["win"][0] / SIMULATIONS,
        }
        for r in rids
    }


def _fmt(p: float | None) -> str:
    if p is None:
        return "—"
    if p >= 99.95:
        return "100%"
    if p >= 99.5:
        return ">99%"
    if p == 0:
        return "0%"
    if p < 0.05:
        return "<0.1%"
    if p < 1:
        return f"{p:.1f}%"
    return f"{p:.0f}%"


def _outcome(label: str, cls: str, odds: tuple) -> str:
    playoff, bye = odds
    width = 0 if playoff is None else max(0.0, min(100.0, playoff))
    return (
        f'<div class="odds-outcome {cls}">'
        f'<div class="odds-outcome-label">{label}</div>'
        f'<div class="odds-outcome-main"><span class="odds-pct">{_fmt(playoff)}</span>'
        f'<span class="odds-pct-label">playoffs</span></div>'
        f'<div class="odds-bar"><span style="width:{width:.1f}%"></span></div>'
        f'<div class="odds-outcome-bye"><span>{_fmt(bye)}</span> bye</div>'
        f'</div>'
    )


def render_playoff_odds_section(
    odds: dict[int, dict], team_lookup: dict, opponents: dict, records: dict | None, week: int,
    min_pct: float = 0.1, long_shot_pct: float = 10.0,
) -> str:
    """One card per team that still has a realistic shot (any chance above
    `min_pct`), ordered by overall playoff odds; everyone else gets listed
    on one line at the bottom."""
    if not odds:
        return ""
    rid_to_username = {v["roster_id"]: k for k, v in team_lookup.items()}
    ranked = sorted(odds, key=lambda r: (odds[r]["all"][0] or 0, odds[r]["all"][1] or 0), reverse=True)

    cards, long_shots, out = [], [], []
    for rid in ranked:
        username = rid_to_username.get(rid)
        info = team_lookup.get(username, {})
        nickname = info.get("nickname", username or "?")
        o = odds[rid]
        if (o["win"][0] or 0) < min_pct and (o["loss"][0] or 0) < min_pct:
            out.append(nickname)
            continue
        opp = team_lookup.get(opponents.get(username), {}).get("nickname")
        record = (records or {}).get(username, "")
        swing = (o["win"][0] or 0) - (o["loss"][0] or 0)
        swing_html = (
            f'<span class="odds-swing">{swing:.0f}% swing</span>' if swing >= 1 else ""
        )
        target = cards if (o["all"][0] or 0) >= long_shot_pct else long_shots
        target.append(
            '<div class="odds-card">'
            '<div class="odds-card-head">'
            f'{render_avatar(info.get("avatar_url"), nickname, "avatar-sm")}'
            '<div class="odds-card-id">'
            f'<span class="odds-card-name">{esc(nickname)}</span>'
            f'<span class="odds-card-meta">{esc(record)}'
            + (f' · vs {esc(opp)}' if opp else "")
            + '</span></div>'
            f'{swing_html}'
            '</div>'
            '<div class="odds-outcomes">'
            f'{_outcome("Win", "odds-win", o["win"])}'
            f'{_outcome("Loss", "odds-loss", o["loss"])}'
            '</div>'
            '</div>'
        )

    out_html = (
        f'<p class="odds-footnote"><strong>Effectively eliminated:</strong> {esc(", ".join(out))}</p>'
        if out else ""
    )
    long_html = (
        '<details class="odds-more">'
        f'<summary>Long shots ({len(long_shots)}) <span>under {long_shot_pct:.0f}% overall</span></summary>'
        f'<div class="odds-grid">{"".join(long_shots)}</div>'
        '</details>'
        if long_shots else ""
    )
    return f"""
    <section class="brief-section">
      <h2 class="brief-title">Week {week} Playoff Odds</h2>
      <p class="odds-intro">What a win or a loss this week does to each team's chances of making the playoffs (top 6) and getting a first-round bye (top 2). Based on {SIMULATIONS:,} simulations of the rest of the regular season using each team's 2026 scoring.</p>
      <div class="odds-grid">{"".join(cards)}</div>
      {long_html}
      {out_html}
    </section>"""
