"""
Builds the power-rankings site: one page per week (site/week-N.html) plus a
landing page (site/index.html) linking between them.

Pulls together, per week:
- reports/week_N_report(s).txt   (tiers, rank, write-up prose / bullets)
- Sleeper API (live)            (avatar, team nickname, that week's opponent)

Rank movement on a week's page is computed against the previous week's
parsed tiers (by manager first name, which is stable week to week) - the
first week in REPORTS has nothing to compare against, so it shows no
movement badges.

Re-run this script any time a report, roster, or matchup changes; it fully
regenerates every page under site/ (site/style.css is hand-authored, not
touched).
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml

from collectors.sleeper import SleeperClient

SITE_DIR = ROOT / "site"

# Each week's report, its output page, and which live matchup week to show
# as "this week's opponent" on that page (the matchup immediately following
# the write-up - e.g. the preseason report previews Week 1's matchups).
# results_week, when set, is the most recently completed week - its final
# scores and current injury designations are shown in a brief at the top of
# the page. The preseason report has no completed week yet, so it's None.
REPORTS = [
    {
        "path": ROOT / "reports" / "week_0_reports.txt",
        "output": "week-0.html",
        "nav_label": "Week 0",
        "period_label": "Preseason",
        "matchup_week": 1,
        "matchup_label": "week 1",
        "results_week": None,
    },
    {
        "path": ROOT / "reports" / "week_1_reports.txt",
        "output": "week-1.html",
        "nav_label": "Week 1",
        "period_label": "Week 1",
        "matchup_week": 2,
        "matchup_label": "week 2",
        "results_week": 1,
    },
    {
        "path": ROOT / "reports" / "week_2_report.txt",
        "output": "week-2.html",
        "nav_label": "Week 2",
        "period_label": "Week 2",
        "matchup_week": 3,
        "matchup_label": "week 3",
        "results_week": 2,
    },
]

# Sleeper usernames don't reveal the manager's first name (or vice versa) -
# this mapping was worked out by hand against the league and doesn't change.
USERNAME_TO_FIRST_NAME = {
    "jlgreen": "Jacob",
    "FredJHCJ09": "Brett",
    "mwalter05": "Matt",
    "currancmm": "Curran",
    "scottwilliamson2152": "Scott",
    "Theowgs10": "Theo",
    "cjyarbrough": "Caleb",
    "chandlerpittman": "Chandler",
    "nathanmedley2153": "Nathan",
    "CharMcNabb": "Charles",
    "Jsiegel1120": "Siegel",
    "dhunt2001": "Darren",
    "HaydenR50": "Hayden",
    "jessegeorge21": "Jesse",
}
FIRST_NAME_TO_USERNAME = {v: k for k, v in USERNAME_TO_FIRST_NAME.items()}

TIER_SLUGS = {
    "Champions": "champions",
    "Deep Playoff Runs": "deep-playoff-runs",
    "Solid Playoff Teams": "solid-playoff-teams",
    "Meh": "meh",
    "Future Dynasty / Rebuilders": "rebuilders",
}


def load_config() -> dict:
    with open(ROOT / "config" / "league.yaml") as f:
        return yaml.safe_load(f)


def parse_report(path: Path) -> list[dict]:
    """Returns an ordered list of tier dicts: {name, teams: [...]}.

    Each team dict: {rank, first_name, paragraphs, human_bullets, claude_bullets}.
    """
    tier_header_re = re.compile(r"^={3,}\s*(.+?)\s*={3,}$")
    team_header_re = re.compile(r"^(\d+)\.\s+(\S+)\s*$")

    tiers: list[dict] = []
    current_tier = None
    current_team = None

    def flush_paragraph(team, buf):
        if buf:
            team["paragraphs"].append(" ".join(buf).strip())
            buf.clear()

    para_buf: list[str] = []

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()

        tier_m = tier_header_re.match(line)
        team_m = team_header_re.match(line)

        if line == "------------------------------------":
            break  # end of the rankings section; reference tables follow

        if tier_m:
            if current_team:
                flush_paragraph(current_team, para_buf)
            current_tier = {"name": tier_m.group(1), "teams": []}
            tiers.append(current_tier)
            current_team = None
            continue

        if team_m:
            if current_team:
                flush_paragraph(current_team, para_buf)
            current_team = {
                "rank": int(team_m.group(1)),
                "first_name": team_m.group(2),
                "paragraphs": [],
                "human_bullets": [],
                "claude_bullets": [],
            }
            current_tier["teams"].append(current_team)
            continue

        if not line:
            flush_paragraph(current_team, para_buf) if current_team else None
            continue

        if current_team is None:
            continue  # stray text before the first tier/team (e.g. title line)

        if line.startswith("- "):
            flush_paragraph(current_team, para_buf)
            bullet = line[2:].strip()
            if bullet.startswith("CLAUDE:"):
                current_team["claude_bullets"].append(bullet[len("CLAUDE:"):].strip())
            else:
                current_team["human_bullets"].append(bullet)
        else:
            para_buf.append(line)

    if current_team:
        flush_paragraph(current_team, para_buf)

    return tiers


def ranks_by_first_name(tiers: list[dict]) -> dict[str, int]:
    return {t["first_name"]: t["rank"] for tier in tiers for t in tier["teams"]}


def build_team_lookup(users: list[dict], rosters: list[dict], config: dict) -> dict[str, dict]:
    """username -> {avatar_url, nickname, roster_id, owner_id}."""
    # config/league.yaml's "ids" side is already owner_id -> username, with
    # the report's exact casing (jlgreen, FredJHCJ09, etc.) - no inversion needed.
    owner_to_username = config["teams"]["ids"]

    users_by_id = {u["user_id"]: u for u in users}
    lookup: dict[str, dict] = {}

    for roster in rosters:
        owner_id = roster["owner_id"]
        username = owner_to_username.get(owner_id)
        if username is None:
            continue
        user = users_by_id.get(owner_id, {})
        metadata = user.get("metadata") or {}
        avatar_hash = user.get("avatar")
        nickname = (metadata.get("team_name") or user.get("display_name") or username).strip()
        # metadata["avatar"] is the custom team logo set inside this league
        # (a full URL); the top-level "avatar" is just the manager's personal
        # Sleeper account picture. Prefer the team logo, fall back to the
        # account picture if a manager never set one.
        team_avatar_url = metadata.get("avatar")
        account_avatar_url = (
            f"https://sleepercdn.com/avatars/thumbs/{avatar_hash}" if avatar_hash else None
        )
        lookup[username] = {
            "roster_id": roster["roster_id"],
            "owner_id": owner_id,
            "avatar_url": team_avatar_url or account_avatar_url,
            "nickname": nickname,
        }
    return lookup


def build_opponent_map(matchups: list[dict], team_lookup: dict) -> dict[str, str | None]:
    """username -> opponent username (or None for a bye) for the given week's matchups."""
    roster_id_to_username = {v["roster_id"]: k for k, v in team_lookup.items()}

    by_matchup: dict[int, list[int]] = {}
    for m in matchups:
        by_matchup.setdefault(m["matchup_id"], []).append(m["roster_id"])

    opponent_of_roster: dict[int, int | None] = {}
    for roster_ids in by_matchup.values():
        if len(roster_ids) == 2:
            a, b = roster_ids
            opponent_of_roster[a] = b
            opponent_of_roster[b] = a
        else:
            for r in roster_ids:
                opponent_of_roster[r] = None

    result = {}
    for username, info in team_lookup.items():
        opp_roster_id = opponent_of_roster.get(info["roster_id"])
        result[username] = roster_id_to_username.get(opp_roster_id) if opp_roster_id else None
    return result


def compute_records(matchups_by_week: dict[int, list[dict]], through_week: int, team_lookup: dict) -> dict[str, str]:
    """username -> "W-L" (or "W-L-T" once a tie has happened) from the
    head-to-head results of weeks 1..through_week, so each week's page shows
    the records as they stood when that report was written."""
    roster_id_to_username = {v["roster_id"]: k for k, v in team_lookup.items()}
    tallies = {username: [0, 0, 0] for username in team_lookup}

    for week in range(1, through_week + 1):
        by_matchup: dict[int, list[dict]] = {}
        for m in matchups_by_week[week]:
            by_matchup.setdefault(m["matchup_id"], []).append(m)
        for pair in by_matchup.values():
            if len(pair) != 2:
                continue
            a, b = pair
            a_pts, b_pts = a.get("points") or 0, b.get("points") or 0
            for side, pts, opp_pts in ((a, a_pts, b_pts), (b, b_pts, a_pts)):
                username = roster_id_to_username.get(side["roster_id"])
                if username is None:
                    continue
                idx = 0 if pts > opp_pts else 1 if pts < opp_pts else 2
                tallies[username][idx] += 1

    return {
        username: f"{w}-{l}-{t}" if t else f"{w}-{l}"
        for username, (w, l, t) in tallies.items()
    }


def esc(text: str) -> str:
    return html.escape(text, quote=False)


# Phrases in the write-ups that get auto-linked to a methodology + data page.
# Keyed by the exact phrase (case-insensitive match, original casing kept),
# value is the href relative to a week page (site/week-N.html). Includes the
# couple of non-standard variants ("variance"/"variability" instead of
# "variation") that have shown up in write-ups, so a wording slip doesn't
# silently drop the link.
GLOSSARY_LINKS = {
    "coefficient of variation": "stats/variance.html",
    "coefficient of variance": "stats/variance.html",
    "coefficient of variability": "stats/variance.html",
}
_GLOSSARY_RE = re.compile(
    "|".join(re.escape(p) for p in GLOSSARY_LINKS), re.IGNORECASE
)


def linkify(escaped_text: str) -> str:
    """Wraps any glossary phrase (already-HTML-escaped text) in a link to
    its methodology/data page. Must run after esc(), not before."""

    def _sub(m: re.Match) -> str:
        href = GLOSSARY_LINKS[m.group(0).lower()]
        return f'<a class="glossary-link" href="{href}">{m.group(0)}</a>'

    return _GLOSSARY_RE.sub(_sub, escaped_text)


def render_avatar(avatar_url: str | None, alt: str, size_class: str) -> str:
    if avatar_url:
        return f'<img class="avatar {size_class}" src="{esc(avatar_url)}" alt="{esc(alt)}" loading="lazy">'
    initial = esc(alt[:1].upper()) if alt else "?"
    return f'<div class="avatar avatar-fallback {size_class}">{initial}</div>'


def render_movement(delta: int | None) -> str:
    """delta is old_rank - new_rank: positive means the team moved up
    (rank number went down). None means no prior week to compare against."""
    if delta is None:
        return ""
    if delta > 0:
        return f'<div class="rank-movement rank-movement-up" title="Up {delta} from last week">&#9650;{delta}</div>'
    if delta < 0:
        return f'<div class="rank-movement rank-movement-down" title="Down {-delta} from last week">&#9660;{-delta}</div>'
    return '<div class="rank-movement rank-movement-same" title="Unchanged from last week">&ndash;</div>'


# Game-status designations worth surfacing in the quick brief - IR/PUP/NA/DNR
# are season-long roster situations, not this-week news, so they're left out
# here (the full breakdown is still in outputs/injury_report.txt).
INJURY_BRIEF_STATUSES = ["Out", "Doubtful", "Questionable"]
INJURY_CHIP_CLASS = {
    "Out": "injury-chip-out",
    "Doubtful": "injury-chip-doubtful",
    "Questionable": "injury-chip-questionable",
}


def build_injury_brief(rosters: list[dict], team_lookup: dict, players: dict) -> dict[str, list[dict]]:
    """username -> [{name, position, status, body_part}, ...] for rostered
    players (starters + bench) currently tagged Out/Doubtful/Questionable."""
    username_by_roster_id = {v["roster_id"]: k for k, v in team_lookup.items()}
    result: dict[str, list[dict]] = {}

    for r in rosters:
        username = username_by_roster_id.get(r["roster_id"])
        if username is None:
            continue
        entries = []
        for pid in r.get("players") or []:
            p = players.get(pid) or {}
            status = p.get("injury_status")
            if status not in INJURY_BRIEF_STATUSES:
                continue
            entries.append({
                "name": p.get("full_name") or pid,
                "position": p.get("position") or "?",
                "status": status,
                "body_part": p.get("injury_body_part") or "",
            })
        if entries:
            entries.sort(key=lambda e: (INJURY_BRIEF_STATUSES.index(e["status"]), e["name"]))
            result[username] = entries

    return result


def render_injury_brief(injury_by_username: dict[str, list[dict]], team_lookup: dict, ranked_first_names: list[str]) -> str:
    blocks = []
    for first_name in ranked_first_names:
        username = FIRST_NAME_TO_USERNAME.get(first_name)
        entries = injury_by_username.get(username)
        if not entries:
            continue
        nickname = team_lookup.get(username, {}).get("nickname", first_name)
        chips = "".join(
            f'<div class="injury-chip {INJURY_CHIP_CLASS.get(e["status"], "")}">'
            f'<span class="injury-chip-status">{esc(e["status"])}</span>'
            f'<span class="injury-chip-name">{esc(e["name"])}</span>'
            f'<span class="injury-chip-meta">{esc(e["position"])}'
            + (f' · {esc(e["body_part"])}' if e["body_part"] else '')
            + '</span></div>'
            for e in entries
        )
        blocks.append(
            f'<div class="injury-brief-team">'
            f'<div class="injury-brief-team-name">{esc(nickname)}</div>'
            f'<div class="injury-brief-chips">{chips}</div>'
            f'</div>'
        )
    if not blocks:
        return '<p class="week-brief-empty">No Out/Doubtful/Questionable designations.</p>'
    return "".join(blocks)


def render_score_side(info: dict, pts: float, is_winner: bool) -> str:
    nickname = info.get("nickname", "—")
    avatar_html = render_avatar(info.get("avatar_url"), nickname, "avatar-sm")
    cls = "score-side score-side-win" if is_winner else "score-side"
    return (
        f'<div class="{cls}">{avatar_html}'
        f'<span class="score-side-name">{esc(nickname)}</span>'
        f'<span class="score-side-pts">{pts:.2f}</span></div>'
    )


def render_score_brief(matchups: list[dict], team_lookup: dict) -> str:
    roster_id_to_username = {v["roster_id"]: k for k, v in team_lookup.items()}

    by_matchup: dict[int, list[dict]] = {}
    for m in matchups:
        by_matchup.setdefault(m["matchup_id"], []).append(m)

    games = [entries for entries in by_matchup.values() if len(entries) == 2]
    games.sort(key=lambda g: max(g[0].get("points") or 0, g[1].get("points") or 0), reverse=True)

    rows = []
    for a, b in games:
        a_info = team_lookup.get(roster_id_to_username.get(a["roster_id"]), {})
        b_info = team_lookup.get(roster_id_to_username.get(b["roster_id"]), {})
        a_pts = a.get("points") or 0
        b_pts = b.get("points") or 0
        a_win = a_pts >= b_pts
        rows.append(
            '<div class="score-game">'
            f'{render_score_side(a_info, a_pts, a_win)}'
            f'{render_score_side(b_info, b_pts, not a_win)}'
            '</div>'
        )
    if not rows:
        return '<p class="week-brief-empty">No completed games yet.</p>'
    return "".join(rows)


def render_score_brief_section(week_num: int, matchups: list[dict], team_lookup: dict) -> str:
    score_html = render_score_brief(matchups, team_lookup)
    return f"""
    <section class="brief-section">
      <h2 class="brief-title">Week {week_num} Scores</h2>
      <div class="score-grid">{score_html}</div>
    </section>"""


def render_injury_brief_section(injury_by_username: dict, team_lookup: dict, ranked_first_names: list[str]) -> str:
    injury_html = render_injury_brief(injury_by_username, team_lookup, ranked_first_names)
    return f"""
    <section class="brief-section">
      <h2 class="brief-title">Injury Report</h2>
      <div class="injury-brief-grid">{injury_html}</div>
    </section>"""


def render_team_card(
    team: dict,
    tier_slug: str,
    team_lookup: dict,
    opponents: dict,
    roster_html_by_username: dict,
    matchup_label: str,
    prev_ranks: dict[str, int] | None,
    records: dict[str, str] | None,
) -> str:
    username = FIRST_NAME_TO_USERNAME[team["first_name"]]
    info = team_lookup.get(username, {})
    nickname = info.get("nickname", team["first_name"])
    avatar_url = info.get("avatar_url")
    opp_username = opponents.get(username)

    if opp_username:
        opp_info = team_lookup.get(opp_username, {})
        opp_name = opp_info.get("nickname", opp_username)
        opp_avatar = render_avatar(opp_info.get("avatar_url"), opp_name, "avatar-sm")
        matchup_html = f'{opp_avatar}<span>{esc(opp_name)}</span>'
    else:
        matchup_html = '<span class="bye-label">BYE</span>'

    body_parts = []
    for p in team["paragraphs"]:
        body_parts.append(f'<p class="team-prose">{linkify(esc(p))}</p>')
    if team["human_bullets"]:
        items = "".join(f"<li>{linkify(esc(b))}</li>" for b in team["human_bullets"])
        body_parts.append(f'<ul class="team-bullets">{items}</ul>')
    if team["claude_bullets"]:
        items = "".join(f"<li>{linkify(esc(b))}</li>" for b in team["claude_bullets"])
        body_parts.append(
            '<div class="ai-note">'
            '<div class="ai-note-label">AI-assisted notes</div>'
            f'<ul class="ai-note-list">{items}</ul>'
            "</div>"
        )
    body_html = "\n".join(body_parts) if body_parts else '<p class="team-prose team-prose-empty">No write-up yet.</p>'

    avatar_html = render_avatar(avatar_url, nickname, "avatar-lg")
    roster_html = roster_html_by_username.get(username, "")

    prev_rank = (prev_ranks or {}).get(team["first_name"])
    delta = (prev_rank - team["rank"]) if prev_rank is not None else None
    movement_html = render_movement(delta)

    record = (records or {}).get(username)
    record_html = f'<span class="team-record">{esc(record)}</span>' if record else ""

    return f"""
      <article class="team-card tier-{tier_slug}" id="team-{esc(team["first_name"].lower())}">
        <div class="team-card-header">
          <div class="rank-badge-group">
            <div class="rank-badge">{team["rank"]}</div>
            {movement_html}
          </div>
          {avatar_html}
          <div class="team-identity">
            <div class="team-nickname"><span class="team-nickname-text">{esc(nickname)}</span>{record_html}</div>
            <div class="team-manager">{esc(team["first_name"])}</div>
          </div>
          <div class="team-stats">
            <div class="stat stat-matchup">
              <div class="stat-value stat-matchup-value">{matchup_html}</div>
              <div class="stat-label">{esc(matchup_label)}</div>
            </div>
          </div>
        </div>
        <div class="team-card-body">
          {body_html}
          {roster_html}
        </div>
      </article>"""


def render_tier_section(
    tier: dict, team_lookup: dict, opponents: dict, roster_html_by_username: dict,
    matchup_label: str, prev_ranks: dict[str, int] | None, records: dict[str, str] | None,
) -> str:
    slug = TIER_SLUGS.get(tier["name"], re.sub(r"[^a-z0-9]+", "-", tier["name"].lower()).strip("-"))
    cards = "\n".join(
        render_team_card(t, slug, team_lookup, opponents, roster_html_by_username, matchup_label, prev_ranks, records)
        for t in tier["teams"]
    )
    return f"""
    <section class="tier tier-{slug}" id="{slug}">
      <div class="tier-header">
        <h2 class="tier-name">{esc(tier["name"])}</h2>
        <div class="tier-rule"></div>
      </div>
      <div class="tier-teams">
        {cards}
      </div>
    </section>"""


def render_week_switcher(current_output: str) -> str:
    links = ['<a href="index.html" class="week-switch-link">All Weeks</a>']
    for cfg in REPORTS:
        active = " week-switch-link-active" if cfg["output"] == current_output else ""
        links.append(f'<a href="{cfg["output"]}" class="week-switch-link{active}">{esc(cfg["nav_label"])}</a>')
    return f'<nav class="week-switcher">{"".join(links)}</nav>'


def render_page(
    tiers: list[dict], team_lookup: dict, opponents: dict, roster_html_by_username: dict,
    league_name: str, period_label: str, season: str, matchup_label: str, prev_ranks: dict[str, int] | None,
    current_output: str, records: dict[str, str] | None = None,
    top_brief_html: str = "", bottom_brief_html: str = "",
) -> str:
    sections = "\n".join(
        render_tier_section(t, team_lookup, opponents, roster_html_by_username, matchup_label, prev_ranks, records)
        for t in tiers
    )
    nav_links = "\n".join(
        f'<a href="#{TIER_SLUGS.get(t["name"], "")}" class="nav-link nav-{TIER_SLUGS.get(t["name"], "")}">{esc(t["name"])}</a>'
        for t in tiers
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(league_name)} — Power Rankings — {esc(period_label)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Public+Sans:wght@400;500;600&display=swap">
<link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="site-header">
    <div class="site-header-inner">
      <div class="site-title">
        <span class="site-title-league">{esc(league_name)}</span>
        <span class="site-title-sub">Power Rankings · {esc(season)} Season, {esc(period_label)}</span>
      </div>
      {render_week_switcher(current_output)}
      <nav class="tier-nav">
        {nav_links}
      </nav>
    </div>
  </header>

  <main class="rankings">
    {top_brief_html}
    {sections}
    {bottom_brief_html}
  </main>

  <footer class="site-footer">
    <p>Projections and stats pulled from Sleeper. Analysis by the league; notes marked "AI-assisted" were drafted with Claude and reviewed by the commissioner.</p>
  </footer>
</body>
</html>
"""


def render_index_page(league_name: str, season: str, reports: list[dict]) -> str:
    # Newest week first.
    rows = []
    for cfg in reversed(reports):
        rows.append(f"""
      <li class="week-row">
        <a class="week-row-link" href="{esc(cfg["output"])}">
          <span class="week-row-label">{esc(cfg["nav_label"])}</span>
          <span class="week-row-period">{esc(cfg["period_label"])}</span>
          <span class="week-row-arrow">&rarr;</span>
        </a>
      </li>""")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(league_name)} — Power Rankings</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Public+Sans:wght@400;500;600&display=swap">
<link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="site-header">
    <div class="site-header-inner">
      <div class="site-title">
        <span class="site-title-league">{esc(league_name)}</span>
        <span class="site-title-sub">Power Rankings · {esc(season)} Season</span>
      </div>
    </div>
  </header>

  <main class="landing">
    <ul class="week-list">
      {"".join(rows)}
    </ul>
  </main>

  <footer class="site-footer">
    <p>Projections and stats pulled from Sleeper. Analysis by the league; notes marked "AI-assisted" were drafted with Claude and reviewed by the commissioner.</p>
  </footer>
</body>
</html>
"""


def main():
    config = load_config()
    client = SleeperClient(config)

    users = client.get_users()
    rosters = client.get_rosters()
    league = client.get_league()
    state = client.get_nfl_state()

    team_lookup = build_team_lookup(users, rosters, config)

    import roster  # deferred: roster.py imports back from this module

    sleeper_for_roster = {"rosters": rosters, "league": league}
    players = roster.load_players_catalog()
    lineups = roster.build_starting_lineups(sleeper_for_roster, team_lookup, players)
    roster_html_by_username = {
        username: roster.render_roster_details(slots) for username, slots in lineups.items()
    }

    league_name = league.get("name", "Fantasy League")
    season = state["season"]

    prev_ranks: dict[str, int] | None = None
    matchups_by_week: dict[int, list[dict]] = {}

    def matchups_for(week: int) -> list[dict]:
        if week not in matchups_by_week:
            matchups_by_week[week] = client.get_matchups(week)
        return matchups_by_week[week]

    for cfg in REPORTS:
        matchups = matchups_for(cfg["matchup_week"])
        opponents = build_opponent_map(matchups, team_lookup)
        tiers = parse_report(cfg["path"])

        top_brief_html = ""
        bottom_brief_html = ""
        records = None
        if cfg["results_week"]:
            for week in range(1, cfg["results_week"] + 1):
                matchups_for(week)
            records = compute_records(matchups_by_week, cfg["results_week"], team_lookup)
            results_matchups = matchups_for(cfg["results_week"])
            top_brief_html = render_score_brief_section(cfg["results_week"], results_matchups, team_lookup)

            injury_by_username = build_injury_brief(rosters, team_lookup, players)
            ranked_first_names = [t["first_name"] for tier in tiers for t in tier["teams"]]
            bottom_brief_html = render_injury_brief_section(injury_by_username, team_lookup, ranked_first_names)

        html_out = render_page(
            tiers, team_lookup, opponents, roster_html_by_username,
            league_name=league_name,
            period_label=cfg["period_label"],
            season=season,
            matchup_label=cfg["matchup_label"],
            prev_ranks=prev_ranks,
            current_output=cfg["output"],
            records=records,
            top_brief_html=top_brief_html,
            bottom_brief_html=bottom_brief_html,
        )
        out_path = SITE_DIR / cfg["output"]
        out_path.write_text(html_out)
        print(f"Wrote {out_path}")

        prev_ranks = ranks_by_first_name(tiers)

    index_html = render_index_page(league_name, season, REPORTS)
    index_path = SITE_DIR / "index.html"
    index_path.write_text(index_html)
    print(f"Wrote {index_path}")

    import stats  # deferred: stats.py imports back from this module

    stats.build(team_lookup, back_href=f"../{REPORTS[-1]['output']}")


if __name__ == "__main__":
    main()
