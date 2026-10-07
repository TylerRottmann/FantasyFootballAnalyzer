import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ESPNLeagueService:
    BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"

    def __init__(self, league_id, season):
        self.league_id = str(league_id).strip()
        self.season = int(season)

        if not self.league_id:
            raise ValueError("An ESPN League ID is required.")

    def _get(self, params=""):
        url = (
            f"{self.BASE_URL}/seasons/{self.season}"
            f"/segments/0/leagues/{self.league_id}"
            f"{params}"
        )

        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "FantasyFootballAnalyzer/1.0",
            },
        )

        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)

        except HTTPError as error:
            if error.code in (401, 403):
                raise ValueError(
                    "This ESPN league is private or could not be accessed. "
                    "Public ESPN leagues are currently supported."
                ) from error

            if error.code == 404:
                raise ValueError(
                    "ESPN league not found. Check the League ID and season."
                ) from error

            raise ValueError(
                f"ESPN returned an error ({error.code})."
            ) from error

        except URLError as error:
            raise ValueError(
                "Could not connect to ESPN. Please try again."
            ) from error

    def get_league(self):
        return self._get("?view=mSettings")

    def get_teams(self):
        data = self._get("?view=mTeam")
        return data.get("teams", [])

    def get_rosters(self):
        data = self._get("?view=mRoster")
        return data.get("teams", [])

    def get_league_data(self):
        return {
            "league": self.get_league(),
            "teams": self.get_teams(),
            "rosters": self.get_rosters(),
        }