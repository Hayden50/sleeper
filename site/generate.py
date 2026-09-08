"""
Builds site/index.html: a static, no-JS power-rankings page.

Pulls together:
- reports/week_0_reports.txt   (tiers, rank, write-up prose / bullets)
- outputs/ranking_table.txt    (projected starting-lineup points)
- Sleeper API (live)           (avatar, team nickname, this week's opponent)

Re-run this script any time the report or rosters change; it fully
regenerates site/index.html (site/style.css is hand-authored, not touched).
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

REPORT_PATH = ROOT / "reports" / "week_0_reports.txt"
RANKING_TABLE_PATH = ROOT / "outputs" / "ranking_table.txt"
SITE_DIR = ROOT / "site"

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


def fetch_sleeper_data(config: dict) -> dict:
    client = SleeperClient(config)
    state = client.get_nfl_state()
    return {
        "users": client.get_users(),
        "rosters": client.get_rosters(),
        "matchups": client.get_matchups(state["week"]),
        "league": client.get_league(),
        "state": state,
    }


def load_projected_points() -> dict[str, float]:
    """username -> projected starting-lineup points, from ranking_table.txt."""
    points = {}
    row_re = re.compile(r"^\s*\d+\s+(\S+)\s+([\d.]+)\s")
    for line in RANKING_TABLE_PATH.read_text().splitlines():
        m = row_re.match(line)
        if m:
            points[m.group(1)] = float(m.group(2))
    return points


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


def build_team_lookup(sleeper: dict, config: dict) -> dict[str, dict]:
    """username -> {avatar_url, nickname, roster_id, owner_id}."""
    # config/league.yaml's "ids" side is already owner_id -> username, with
    # the report's exact casing (jlgreen, FredJHCJ09, etc.) - no inversion needed.
    owner_to_username = config["teams"]["ids"]

    users_by_id = {u["user_id"]: u for u in sleeper["users"]}
    lookup: dict[str, dict] = {}

    for roster in sleeper["rosters"]:
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


def build_opponent_map(sleeper: dict, team_lookup: dict) -> dict[str, str | None]:
    """username -> opponent username (or None for a bye) for the fetched week."""
    roster_id_to_username = {v["roster_id"]: k for k, v in team_lookup.items()}

    by_matchup: dict[int, list[int]] = {}
    for m in sleeper["matchups"]:
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


def esc(text: str) -> str:
    return html.escape(text, quote=False)


# Phrases in the write-ups that get auto-linked to a methodology + data page.
# Keyed by the exact phrase (case-insensitive match, original casing kept),
# value is the href relative to site/index.html. Includes the couple of
# non-standard variants ("variance"/"variability" instead of "variation")
# that have shown up in write-ups, so a wording slip doesn't silently drop
# the link.
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


def render_team_card(team: dict, tier_slug: str, team_lookup: dict, points: dict, opponents: dict, roster_html_by_username: dict) -> str:
    username = FIRST_NAME_TO_USERNAME[team["first_name"]]
    info = team_lookup.get(username, {})
    nickname = info.get("nickname", team["first_name"])
    avatar_url = info.get("avatar_url")
    proj = points.get(username)
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
    proj_html = f"{proj:.1f}" if proj is not None else "—"
    roster_html = roster_html_by_username.get(username, "")

    return f"""
      <article class="team-card tier-{tier_slug}" id="team-{esc(team["first_name"].lower())}">
        <div class="team-card-header">
          <div class="rank-badge">{team["rank"]}</div>
          {avatar_html}
          <div class="team-identity">
            <div class="team-nickname">{esc(nickname)}</div>
            <div class="team-manager">{esc(team["first_name"])}</div>
          </div>
          <div class="team-stats">
            <div class="stat">
              <div class="stat-value">{proj_html}</div>
              <div class="stat-label">proj. pts</div>
            </div>
            <div class="stat stat-matchup">
              <div class="stat-value stat-matchup-value">{matchup_html}</div>
              <div class="stat-label">week 1</div>
            </div>
          </div>
        </div>
        <div class="team-card-body">
          {body_html}
          {roster_html}
        </div>
      </article>"""


def render_tier_section(tier: dict, team_lookup: dict, points: dict, opponents: dict, roster_html_by_username: dict) -> str:
    slug = TIER_SLUGS.get(tier["name"], re.sub(r"[^a-z0-9]+", "-", tier["name"].lower()).strip("-"))
    cards = "\n".join(
        render_team_card(t, slug, team_lookup, points, opponents, roster_html_by_username) for t in tier["teams"]
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


def render_page(tiers: list[dict], team_lookup: dict, points: dict, opponents: dict, roster_html_by_username: dict, league_name: str, week: int, season: str) -> str:
    sections = "\n".join(render_tier_section(t, team_lookup, points, opponents, roster_html_by_username) for t in tiers)
    nav_links = "\n".join(
        f'<a href="#{TIER_SLUGS.get(t["name"], "")}" class="nav-link nav-{TIER_SLUGS.get(t["name"], "")}">{esc(t["name"])}</a>'
        for t in tiers
    )
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
        <span class="site-title-sub">Power Rankings · {esc(season)} Season, Week {week}</span>
      </div>
      <nav class="tier-nav">
        {nav_links}
      </nav>
    </div>
  </header>

  <main class="rankings">
    {sections}
  </main>

  <footer class="site-footer">
    <p>Projections and stats pulled from Sleeper. Analysis by the league; notes marked "AI-assisted" were drafted with Claude and reviewed by the commissioner.</p>
  </footer>
</body>
</html>
"""


def main():
    config = load_config()
    sleeper = fetch_sleeper_data(config)
    team_lookup = build_team_lookup(sleeper, config)
    opponents = build_opponent_map(sleeper, team_lookup)
    points = load_projected_points()
    tiers = parse_report(REPORT_PATH)

    import roster  # deferred: roster.py imports back from this module

    players = roster.load_players_catalog()
    lineups = roster.build_starting_lineups(sleeper, team_lookup, players)
    roster_html_by_username = {
        username: roster.render_roster_details(slots) for username, slots in lineups.items()
    }

    html_out = render_page(
        tiers,
        team_lookup,
        points,
        opponents,
        roster_html_by_username,
        league_name=sleeper["league"].get("name", "Fantasy League"),
        week=sleeper["state"]["week"],
        season=sleeper["state"]["season"],
    )

    out_path = SITE_DIR / "index.html"
    out_path.write_text(html_out)
    print(f"Wrote {out_path}")

    import stats  # deferred: stats.py imports back from this module

    stats.build(team_lookup)


if __name__ == "__main__":
    main()
