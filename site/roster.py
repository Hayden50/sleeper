"""
Builds the collapsed "starting lineup" disclosure shown on each team card:
headshot + name for every starter, in roster-slot order.

Uses the same live roster/starters data generate.py already fetched (no
extra API calls) plus the cached player catalog (output_data/cache/players.json)
for names/positions - the exact same source claude_scripts/*.py use.
"""

from __future__ import annotations

from pathlib import Path

from generate import esc

ROOT = Path(__file__).resolve().parent.parent
PLAYERS_CACHE_PATH = ROOT / "output_data" / "cache" / "players.json"

NON_POSITION_SLOTS = {"BN", "IR", "TAXI"}


def load_players_catalog() -> dict:
    import json

    with open(PLAYERS_CACHE_PATH) as f:
        return json.load(f)


def headshot_url(player_id: str, position: str) -> str:
    if position == "DEF":
        return f"https://sleepercdn.com/images/team_logos/nfl/{player_id.lower()}.png"
    return f"https://sleepercdn.com/content/nfl/players/{player_id}.jpg"


def build_starting_lineups(sleeper: dict, team_lookup: dict, players: dict) -> dict[str, list[dict]]:
    """username -> [{slot, name, position, headshot}, ...] in roster-slot order."""
    roster_positions = sleeper["league"]["roster_positions"]
    slot_types = [p for p in roster_positions if p not in NON_POSITION_SLOTS]

    rosters_by_id = {r["roster_id"]: r for r in sleeper["rosters"]}
    lineups: dict[str, list[dict]] = {}

    for username, info in team_lookup.items():
        roster = rosters_by_id.get(info["roster_id"])
        if not roster:
            continue
        starters = roster.get("starters") or []
        slots = []
        for slot, player_id in zip(slot_types, starters):
            if player_id == "0":
                slots.append({"slot": slot, "name": "Empty", "position": slot, "headshot": None})
                continue
            player = players.get(player_id, {})
            position = player.get("position") or slot
            name = (
                player.get("full_name")
                or " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
                or player_id
            )
            slots.append({
                "slot": slot,
                "name": name,
                "position": position,
                "headshot": headshot_url(player_id, position),
            })
        lineups[username] = slots

    return lineups


SLOT_LABELS = {
    "SUPER_FLEX": "SFLX",
    "WRRB_FLEX": "W/R",
    "REC_FLEX": "W/T",
}


def render_roster_details(slots: list[dict]) -> str:
    tiles = []
    for s in slots:
        if s["headshot"]:
            img = (
                f'<img class="roster-slot-photo" src="{esc(s["headshot"])}" '
                f'alt="{esc(s["name"])}" loading="lazy" onerror="this.remove()">'
            )
        else:
            img = '<div class="roster-slot-photo roster-slot-photo-empty"></div>'
        label = SLOT_LABELS.get(s["slot"], s["slot"])
        tiles.append(
            '<div class="roster-slot">'
            f'{img}'
            f'<div class="roster-slot-label">{esc(label)}</div>'
            f'<div class="roster-slot-name">{esc(s["name"])}</div>'
            '</div>'
        )

    return (
        '<details class="roster-detail">'
        '<summary>Starting lineup</summary>'
        f'<div class="roster-grid">{"".join(tiles)}</div>'
        '</details>'
    )
