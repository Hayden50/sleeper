"""Shared helpers for the one-off data-pull scripts in claude_scripts/."""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from collectors.sleeper import SleeperClient
CACHE_DIR = ROOT / "output_data" / "cache"
PLAYERS_CACHE_PATH = CACHE_DIR / "players.json"
PLAYERS_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60  # Sleeper: fetch at most once/day

FLEX_MAP = {
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "REC_FLEX": {"WR", "TE"},
    "WRRB_FLEX": {"WR", "RB"},
}
NON_POSITION_SLOTS = {"BN", "IR", "TAXI"}


def load_config() -> dict:
    with open(ROOT / "config" / "league.yaml", "r") as f:
        return yaml.safe_load(f)


def get_client() -> SleeperClient:
    return SleeperClient(load_config())


def team_name_lookup(config: dict) -> dict:
    """owner_id -> display username, from config/league.yaml."""
    return config["teams"]["ids"]


def load_players(client: SleeperClient, force_refresh: bool = False) -> dict:
    """player_id -> player dict, cached to disk since this is a ~14MB payload
    and Sleeper asks that it not be fetched more than once a day."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not force_refresh and PLAYERS_CACHE_PATH.exists():
        age = time.time() - PLAYERS_CACHE_PATH.stat().st_mtime
        if age < PLAYERS_CACHE_MAX_AGE_SECONDS:
            with open(PLAYERS_CACHE_PATH, "r") as f:
                return json.load(f)

    players = client.get_players()
    with open(PLAYERS_CACHE_PATH, "w") as f:
        json.dump(players, f)
    return players


def write_output(filename: str, content: str) -> Path:
    out_dir = ROOT / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    with open(path, "w") as f:
        f.write(content)
    return path


def required_positions(roster_positions: list[str]) -> list[str]:
    positions = set()
    for slot in roster_positions:
        if slot in NON_POSITION_SLOTS:
            continue
        positions |= FLEX_MAP.get(slot, {slot})
    return sorted(positions)


def points_field(scoring_settings: dict) -> str:
    rec = scoring_settings.get("rec", 0)
    if rec >= 1:
        return "pts_ppr"
    if rec >= 0.5:
        return "pts_half_ppr"
    return "pts_std"


def get_weekly_points(
    client: SleeperClient, season, weeks: range, positions: list[str], pts_field: str
) -> tuple[dict[int, dict[str, float]], dict[str, float]]:
    """Fetches per-week projections and returns:
    - weekly_points: week -> player_id -> projected points (a player missing
      from a given week's response is not playing that week, e.g. a bye)
    - season_totals: player_id -> summed projected points across all weeks
    """
    weekly_points: dict[int, dict[str, float]] = {}
    season_totals: dict[str, float] = defaultdict(float)

    for week in weeks:
        weekly = client.get_projections(season, week, positions)
        week_map = {}
        for entry in weekly:
            pid = entry.get("player_id")
            stats = entry.get("stats") or {}
            pts = stats.get(pts_field, 0) or 0
            week_map[pid] = pts
            season_totals[pid] += pts
        weekly_points[week] = week_map

    return weekly_points, season_totals


def load_game_log(
    client: SleeperClient,
    season,
    weeks: range,
    positions: list[str],
    pts_field: str,
    force_refresh: bool = False,
) -> dict[str, list[float]]:
    """player_id -> [actual fantasy points for each week they were active],
    for a completed season. Cached to disk since a finished season's results
    never change (delete the cache file to force a refetch, e.g. if
    pts_field/scoring format changes).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"game_log_{season}.json"

    if not force_refresh and cache_path.exists():
        with open(cache_path, "r") as f:
            return json.load(f)

    game_log: dict[str, list[float]] = defaultdict(list)
    for week in weeks:
        weekly = client.get_stats(season, week, positions)
        for entry in weekly:
            pid = entry.get("player_id")
            stats = entry.get("stats") or {}
            # `gms_active` is unreliable - Sleeper sets it to 1.0 even for
            # players who were inactive/on IR and recorded no stats at all
            # that week. The presence of the scoring field itself is the
            # real signal: Sleeper only emits it when the player actually
            # played (even a legitimate real 0.0 game keeps the key), and
            # omits it entirely for inactive/DNP weeks.
            if pts_field not in stats:
                continue
            game_log[pid].append(stats.get(pts_field, 0) or 0)

    game_log = dict(game_log)
    with open(cache_path, "w") as f:
        json.dump(game_log, f)
    return game_log


def consistency_stats(scores: list[float]) -> dict:
    """games played, mean, population stdev, and coefficient of variation
    (stdev / mean) for a player's per-game fantasy scores. stdev/cv are None
    with fewer than 2 games (not enough data to say anything about spread)."""
    n = len(scores)
    if n == 0:
        return {"games": 0, "mean": None, "stdev": None, "cv": None}
    mean = statistics.mean(scores)
    if n < 2:
        return {"games": n, "mean": mean, "stdev": None, "cv": None}
    stdev = statistics.pstdev(scores, mu=mean)
    cv = (stdev / mean) if mean else None
    return {"games": n, "mean": mean, "stdev": stdev, "cv": cv}


def optimal_lineup(
    roster_positions: list[str],
    player_ids: list[str],
    season_totals: dict[str, float],
    players: dict,
) -> tuple[float, list[tuple[str, str]]]:
    """The season-total-maximizing static lineup for a roster - i.e. "what
    if this team had started its best players by position all year," as
    opposed to whatever roster["starters"] actually says.

    Slots are filled from most to least flexible-eligible: exact-position
    slots (QB, RB, WR, TE, K, DEF) first, then FLEX, then SUPER_FLEX last,
    since SUPER_FLEX can use anything the earlier slots could and shouldn't
    "steal" a player a narrower slot needs. This greedy order is optimal
    here because each slot's eligible-position set is a superset of the
    slots filled before it.

    Returns (optimal_total, [(slot, player_id), ...]).
    """
    slot_types = [p for p in roster_positions if p not in NON_POSITION_SLOTS]
    slots_in_fill_order = sorted(
        range(len(slot_types)),
        key=lambda i: len(FLEX_MAP.get(slot_types[i], {slot_types[i]})),
    )

    available = set(player_ids)
    assignments: list[tuple[str, str]] = [None] * len(slot_types)
    total = 0.0

    for i in slots_in_fill_order:
        slot = slot_types[i]
        eligible_positions = FLEX_MAP.get(slot, {slot})
        candidates = [
            pid for pid in available
            if (players.get(pid) or {}).get("position") in eligible_positions
        ]
        if not candidates:
            assignments[i] = (slot, None)
            continue
        best = max(candidates, key=lambda pid: season_totals.get(pid, 0.0))
        available.discard(best)
        total += season_totals.get(best, 0.0)
        assignments[i] = (slot, best)

    return total, assignments


def starter_slots(roster: dict, roster_positions: list[str]) -> list[tuple[str, str]]:
    """[(slot_type, player_id), ...] for a roster's current starters, in
    roster_positions order. Empty slots ("0") are skipped."""
    slot_types = [p for p in roster_positions if p not in NON_POSITION_SLOTS]
    starters = roster.get("starters") or []
    return [
        (slot, pid)
        for slot, pid in zip(slot_types, starters)
        if pid != "0"
    ]


def effective_starter_points(
    roster: dict,
    roster_positions: list[str],
    weeks: range,
    weekly_points: dict[int, dict[str, float]],
    players: dict,
) -> tuple[float, dict[str, float], list[dict]]:
    """Sums starting-lineup points week by week, substituting the best
    same-slot bench player in for any starter missing that week (bye).

    Returns (season_starter_total, per_player_totals, substitution_log).
    """
    slots = starter_slots(roster, roster_positions)
    starter_ids = {pid for _, pid in slots}
    bench_ids = [pid for pid in (roster.get("players") or []) if pid not in starter_ids]

    per_player_totals: dict[str, float] = defaultdict(float)
    subs_log = []
    season_total = 0.0

    for week in weeks:
        week_pts = weekly_points.get(week, {})
        used_this_week: set[str] = set()

        for slot, pid in slots:
            if pid in week_pts:
                pts = week_pts[pid]
                per_player_totals[pid] += pts
                season_total += pts
                continue

            # Starter missing this week (bye) - find the best eligible bench sub.
            eligible_positions = FLEX_MAP.get(slot, {slot})
            candidates = [
                bid for bid in bench_ids
                if bid not in used_this_week
                and bid in week_pts
                and (players.get(bid) or {}).get("position") in eligible_positions
            ]
            if not candidates:
                continue

            sub_id = max(candidates, key=lambda bid: week_pts[bid])
            sub_pts = week_pts[sub_id]
            used_this_week.add(sub_id)
            per_player_totals[sub_id] += sub_pts
            season_total += sub_pts
            subs_log.append({
                "week": week,
                "slot": slot,
                "out_id": pid,
                "in_id": sub_id,
                "in_pts": sub_pts,
            })

    return season_total, per_player_totals, subs_log
