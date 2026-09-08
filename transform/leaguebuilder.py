# import TeamBuilder

class LeagueBuilder:

    def __init__(self, sleeper_client):
        self.league_id = sleeper_client.league_id

        self.users = sleeper_client.get_users()

        self.teams: list[TeamBuilder] = []
        for user in self.users:
            id = user.user_id
            self.teams.append(TeamBuilder(id))


