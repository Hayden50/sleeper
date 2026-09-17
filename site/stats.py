"""
Builds site/stats/variance.html: methodology + full data table for the
"coefficient of variation" stat referenced in the write-ups.

Parses outputs/variance_by_position.txt directly (same source of truth the
main report uses) rather than re-deriving anything, so this page always
matches whatever the analysis scripts most recently computed.
"""

from __future__ import annotations

import re
from pathlib import Path

from generate import (
    FIRST_NAME_TO_USERNAME,
    USERNAME_TO_FIRST_NAME,
    esc,
    render_avatar,
)

ROOT = Path(__file__).resolve().parent.parent
VARIANCE_PATH = ROOT / "outputs" / "variance_by_position.txt"
SITE_DIR = Path(__file__).resolve().parent

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def parse_variance_file(path: Path) -> dict:
    lines = path.read_text().splitlines()

    # --- team summary table -------------------------------------------------
    summary_start = next(i for i, l in enumerate(lines) if l.strip().startswith("TEAM ") and "AVG CV" in l)
    summary = []
    for line in lines[summary_start + 1:]:
        if not line.strip():
            break
        tokens = line.split()
        username, avg_cv, *pos_values = tokens
        summary.append({
            "username": username,
            "avg_cv": avg_cv,
            "positions": dict(zip(POSITIONS, pos_values)),
        })

    # --- league average by position -----------------------------------------
    league_avg_start = next(i for i, l in enumerate(lines) if l.strip().startswith("LEAGUE AVERAGE"))
    league_avg = {}
    for line in lines[league_avg_start + 1:]:
        if not line.strip():
            break
        pos, val = line.split()
        league_avg[pos] = val

    # --- per-team, per-position, per-player detail ---------------------------
    detail_start = next(i for i, l in enumerate(lines) if l.strip().startswith("PER-TEAM STARTER DETAIL"))
    team_header_re = re.compile(r"^(\S+) \(avg starter CV: ([\d.]+|n/a)\)$")
    pos_header_re = re.compile(r"^  (\w+) \(avg CV: ([\d.]+|n/a)\)$")
    player_re = re.compile(
        r"^      (.+?)\s{2,}games=\s*(\d+)\s+mean=\s*([\d.]+)\s+stdev=\s*([\d.]+)\s+cv=([\d.]+)$"
    )
    no_data_re = re.compile(r"^      (.+?)\s{2,}games=\s*0\s+\(not enough")

    detail = {}
    current_team = None
    current_pos = None

    for line in lines[detail_start + 1:]:
        if not line.strip():
            continue
        if m := team_header_re.match(line):
            current_team = {"username": m.group(1), "avg_cv": m.group(2), "positions": []}
            detail[m.group(1)] = current_team
            current_pos = None
            continue
        if m := pos_header_re.match(line):
            current_pos = {"position": m.group(1), "avg_cv": m.group(2), "players": []}
            current_team["positions"].append(current_pos)
            continue
        if m := player_re.match(line):
            current_pos["players"].append({
                "name": m.group(1).strip(),
                "games": int(m.group(2)),
                "mean": m.group(3),
                "stdev": m.group(4),
                "cv": m.group(5),
                "no_data": False,
            })
            continue
        if m := no_data_re.match(line):
            current_pos["players"].append({"name": m.group(1).strip(), "no_data": True})
            continue

    return {"summary": summary, "league_avg": league_avg, "detail": detail}


def render_summary_table(summary: list[dict], team_lookup: dict, back_href: str) -> str:
    header_cells = "".join(
        f'<th data-sort="{esc(p)}">{esc(p)}</th>' for p in ["Avg CV", *POSITIONS]
    )
    rows = []
    for row in summary:
        username = row["username"]
        first_name = USERNAME_TO_FIRST_NAME.get(username, username)
        nickname = team_lookup.get(username, {}).get("nickname", first_name)
        avatar = render_avatar(team_lookup.get(username, {}).get("avatar_url"), nickname, "avatar-sm")
        team_cell = (
            f'<td data-value="{esc(nickname)}">'
            f'<a href="{esc(back_href)}#team-{esc(first_name.lower())}" class="table-team-link">'
            f'{avatar}<span>{esc(nickname)}</span></a></td>'
        )
        value_cells = f'<td data-value="{esc(row["avg_cv"])}" class="stat-highlight">{esc(row["avg_cv"])}</td>'
        for pos in POSITIONS:
            v = row["positions"].get(pos, "n/a")
            sort_v = v if v != "n/a" else "9.99"
            value_cells += f'<td data-value="{esc(sort_v)}">{esc(v)}</td>'
        rows.append(f"<tr>{team_cell}{value_cells}</tr>")

    return f"""
    <div class="stat-table-wrap">
      <table class="stat-table sortable">
        <thead><tr><th data-sort="Team">Team</th>{header_cells}</tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>"""


def render_detail(detail: dict, team_lookup: dict) -> str:
    blocks = []
    # keep the same most-consistent-first order as the summary table
    for username, team in detail.items():
        first_name = USERNAME_TO_FIRST_NAME.get(username, username)
        nickname = team_lookup.get(username, {}).get("nickname", first_name)
        pos_html = []
        for pos in team["positions"]:
            player_rows = []
            for p in pos["players"]:
                if p.get("no_data"):
                    player_rows.append(
                        f'<div class="player-row"><span class="player-name">{esc(p["name"])}</span>'
                        f'<span class="no-data">not enough 2025 data</span></div>'
                    )
                else:
                    player_rows.append(
                        f'<div class="player-row">'
                        f'<span class="player-name">{esc(p["name"])}</span>'
                        f'<span>{p["games"]} gm</span>'
                        f'<span>{esc(p["mean"])} avg</span>'
                        f'<span>±{esc(p["stdev"])}</span>'
                        f'<span>{esc(p["cv"])} cv</span>'
                        f'</div>'
                    )
            pos_html.append(
                f'<div class="position-group">'
                f'<div class="position-group-title">{esc(pos["position"])} · avg cv {esc(pos["avg_cv"])}</div>'
                f'{"".join(player_rows)}'
                f'</div>'
            )
        blocks.append(f"""
      <details class="team-detail">
        <summary><span>{esc(nickname)}</span><span class="avg-cv">{esc(team["avg_cv"])}</span></summary>
        <div class="team-detail-body">{"".join(pos_html)}</div>
      </details>""")
    return "\n".join(blocks)


def render_page(data: dict, team_lookup: dict, back_href: str) -> str:
    summary_table = render_summary_table(data["summary"], team_lookup, back_href)
    detail_html = render_detail(data["detail"], team_lookup)

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Coefficient of Variation — Power Rankings</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Public+Sans:wght@400;500;600&display=swap">
<link rel="stylesheet" href="../style.css">
</head>
<body>
  <header class="site-header">
    <div class="site-header-inner">
      <a class="back-link" href=\"""" + back_href + """\">&larr; Power Rankings</a>
    </div>
  </header>

  <main class="stat-page">
    <div class="stat-page-kicker">Methodology &amp; data</div>
    <h1 class="stat-page-title">Coefficient of Variation</h1>

    <div class="stat-methodology">
      <p>Coefficient of variation (<code>CV = stdev / mean</code>) measures how much a
      player's scoring bounces around week to week, on a scale that works the
      same for a low-scoring kicker as it does for a high-scoring RB1. It's
      computed from each current starter's actual 2025 game log: every week
      they recorded a real stat line counts (byes and inactive weeks are
      excluded), the mean and population standard deviation of their points
      per game are taken, and CV is just stdev divided by mean.</p>
      <p><strong>Lower CV means more consistent</strong> week-to-week scoring.
      Higher CV means more boom/bust. A team's "avg CV" is the average of
      that number across its own current starters, and the position columns
      below break that average out by position group.</p>
    </div>

    <div class="stat-example">
      <strong>Worked example</strong> — Christian McCaffrey (jlgreen's RB1) played
      17 games in 2025, averaging 24.5 points with a standard deviation of
      8.0. CV = 8.0 / 24.5 = <strong>0.33</strong> — one of the steadiest
      starters in the league. Compare a boom/bust name like Bhayshul Tuten
      (chandlerpittman): 15 games, 5.9 mean, 4.8 stdev &rarr; CV =
      4.8 / 5.9 = <strong>0.80</strong>.
    </div>

    <div class="stat-section-title">By team</div>
    <p class="stat-section-note">Sorted most consistent to least by default — click a column to re-sort. "n/a" means fewer than 2 games played this season at that position.</p>
    """ + summary_table + """

    <div class="stat-section-title">Per-player detail</div>
    <p class="stat-section-note">Every current starter's own games played, mean points, standard deviation, and CV, grouped by team and position.</p>
    <div class="detail-section">
    """ + detail_html + """
    </div>
  </main>

  <footer class="site-footer">
    <p>Source: outputs/variance_by_position.txt, from last season's (2025) actual game logs.</p>
  </footer>

  <script>
  (function () {
    document.querySelectorAll("table.sortable").forEach(function (table) {
      var tbody = table.tBodies[0];
      var headers = table.querySelectorAll("th[data-sort]");
      headers.forEach(function (th, idx) {
        th.addEventListener("click", function () {
          var asc = th.getAttribute("data-dir") !== "asc";
          headers.forEach(function (h) { h.removeAttribute("data-dir"); });
          th.setAttribute("data-dir", asc ? "asc" : "desc");
          var rows = Array.prototype.slice.call(tbody.rows);
          rows.sort(function (a, b) {
            var av = a.children[idx].dataset.value;
            var bv = b.children[idx].dataset.value;
            var an = parseFloat(av), bn = parseFloat(bv);
            var cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv);
            return asc ? cmp : -cmp;
          });
          rows.forEach(function (r) { tbody.appendChild(r); });
        });
      });
    });
  })();
  </script>
</body>
</html>
"""


def build(team_lookup: dict, back_href: str = "../index.html") -> None:
    data = parse_variance_file(VARIANCE_PATH)
    out_dir = SITE_DIR / "stats"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "variance.html"
    out_path.write_text(render_page(data, team_lookup, back_href))
    print(f"Wrote {out_path}")
