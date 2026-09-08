from __future__ import annotations

import requests


class SleeperClient:
    BASE_URL = "https://api.sleeper.app/v1"
    PROJECTIONS_BASE_URL = "https://api.sleeper.app/projections/nfl"
    STATS_BASE_URL = "https://api.sleeper.app/stats/nfl"

    def __init__(self, config):
        self.session = requests.Session()
        self.league_id = config["league"]["id"]
        self.teams = config["teams"]["users"]


    def _get(self, endpoint: str, params: dict = None):
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        response = self.session.get(url, params=params)

        response.raise_for_status()

        return response.json()

    def get(self, endpoint: str):
        return self._get(endpoint)

    # League

    def get_league(self):
        return self._get(f"league/{self.league_id}")

    def get_users(self):
        return self._get(f"league/{self.league_id}/users")


    def get_rosters(self):
        return self._get(f"league/{self.league_id}/rosters")


    def get_traded_picks(self):
        return self._get(f"league/{self.league_id}/traded_picks")


    def get_drafts(self):
        return self._get(f"league/{self.league_id}/drafts")


    def get_matchups(self, week: int = None):
        assert week is not None and week > 0 and week < 20
        return self._get(f"/league/{self.league_id}/matchups/{week}")


    # Draft

    def get_draft(self, draft_id: str):
        return self._get(f"draft/{draft_id}")

    def get_draft_picks(self, draft_id: str):
        return self._get(f"draft/{draft_id}/picks")

    def get_draft_traded_picks(self, draft_id: str):
        return self._get(f"draft/{draft_id}/traded_picks")

    def get_latest_draft(self):
        drafts = self.get_drafts()
        if not drafts:
            raise RuntimeError("No drafts found for league.")
        return drafts[0]

    # Players

    def get_players(self):
        return self._get("players/nfl")

    def get_trending_adds(self, limit: int = 25):
        return self._get(f"players/nfl/trending/add?lookback_hours=24&limit={limit}")

    def get_trending_drops(self, limit: int = 25):
        return self._get(f"players/nfl/trending/drop?lookback_hours=24&limit={limit}")

    def get_projections(
        self,
        season: int,
        week: int,
        positions: list[str],
        season_type: str = "regular",
    ):
        """Weekly per-player fantasy projections.

        Undocumented endpoint (not under /v1) used by Sleeper's own web app,
        so it's not guaranteed stable, but it's the only source of
        projections Sleeper exposes.
        """
        url = f"{self.PROJECTIONS_BASE_URL}/{season}/{week}"
        params = {"season_type": season_type, "position[]": positions}
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_stats(
        self,
        season: int,
        week: int,
        positions: list[str],
        season_type: str = "regular",
    ):
        """Weekly per-player actual results. Same undocumented shape as
        get_projections, but historical results instead of a forecast."""
        url = f"{self.STATS_BASE_URL}/{season}/{week}"
        params = {"season_type": season_type, "position[]": positions}
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    # User

    def get_user(self, username: str):
        return self._get(f"user/{username}")

    def get_user_leagues(self, user_id: str, season: int):
        return self._get(f"user/{user_id}/leagues/nfl/{season}")

    # State

    def get_nfl_state(self):
        return self._get("state/nfl")
