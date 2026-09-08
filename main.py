from collections import defaultdict
from pathlib import Path

import yaml

from collectors.sleeper import SleeperClient
from transform.leaguebuilder import LeagueBuilder

def load_config():
    with open(Path("config") / "league.yaml", "r") as f:
        return yaml.safe_load(f)


def main():

    config = load_config()
    sleeper_client = SleeperClient(config)
    # ktc_client...

    # League Factory
    builder = LeagueBuilder(sleeper_client)



if __name__ == "__main__":
    main()
