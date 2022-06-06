import re
from ast import literal_eval

import requests
from bs4 import BeautifulSoup

PLAYER_COLUMNS = ["name", "team", "ping", "score", "ip"]
HEADER_RE = re.compile(r"(.+?)\sin\s(.+?)\s\(\s(\d+:\d+)")


MUTATORS = {
    "InstaGib": "BotPack.InstaGibDM",
}

def sanitize_wa_text(text):
    return text.replace("\xa0", " ")


def try_eval(val):
    try:
        return literal_eval(val.title())
    except ValueError:
        return val


class UT99WebAdmin(object):
    def __init__(self, url, username, password):
        self.url = url
        self.username = username
        self.password = password
        self.session = requests.Session()

    def __get_url(self, subpath):
        return self.session.get(self.url + subpath, auth=(self.username, self.password))

    def __post_url(self, subpath, payload):
        self.__get_url(subpath)  # to prime cookies
        return self.session.post(
            self.url + subpath, auth=(self.username, self.password), data=payload
        )

    # a few proxy functions for development
    def get_url(self, subpath):
        return self.__get_url(subpath)

    def post_url(self, subpath, payload):
        return self.__post_url(subpath, payload)

    def __parse(self, subpath):
        return BeautifulSoup(self.__get_url(subpath).text, features="lxml")

    def parse(self, subpath):
        return self.__parse(subpath)

    def get_state(self):
        plpg = self.__parse("current_players")
        header = plpg("table")[1]("b")[0].text

        rem = HEADER_RE.match(header)
        if rem is None:
            return {}

        return {
            "mode": rem.group(1),
            "mapname": rem.group(2),
            "timeleft": rem.group(3),
            "players": self.get_players(),
        }

    def get_players(self):
        plpg = self.__parse("current_players")

        playertable = plpg("table")[4]

        if playertable("tr")[1]("td")[0].text == "** No Players Connected **":
            return dict()

        players = playertable("tr")[1:]
        res = dict()

        for p in players:
            tokens = p("td")
            offset = 2
            if len(tokens) == 6:  # Bot
                offset = 1
            pl = dict(
                zip(PLAYER_COLUMNS, [sanitize_wa_text(x.text) for x in tokens[offset:]])
            )
            res[pl["name"]] = pl

        return res

    def get_rules(self):
        drpg = self.__parse("defaults_rules")

        trs = drpg("table")[3]("tr")

        settings = dict()

        for tr in trs:
            tokens = tr("td")
            if len(tokens) == 2:
                key = tokens[0].text
                value = tokens[1].input["value"]
            else:
                continue

            settings[key] = try_eval(value)

        return settings

    def get_min_players(self):
        plpg = self.__parse("current_players")
        settable = plpg("table")[3]
        return int(settable("input")[1]["value"])

    def set_min_players(self, num):
        self.__post_url(
            "current_players",
            {"Sort": "Name", "MinPlayers": str(num), "SetMinPlayers": "Set"},
        )
        return self.get_min_players()

    def add_mutator(self, mutator):
        mut = MUTATORS.get(mutator, mutator)
        addmut = {'ExcludeMutatorsSelect': mut, 'AddMutator': '>'}
        self.__post_url("current_mutators", addmut)
    
    def del_mutator(self, mutator):
        mut = MUTATORS.get(mutator, mutator)
        delmut = {'DelMutator': '<', 'IncludeMutatorsSelect': mut}
        self.__post_url("current_mutators", delmut)

    def get_maps(self):
        res = self.__parse("current_game")
        mapsel = res("select")[1]

        return [opt["value"].replace(".unr", "") for opt in mapsel("option")]

    def switch_map(self, mapname):
        # Add a few assumptions here
        if not mapname.endswith(".unr"):
            mapname = f"{mapname}.unr"
        
        if "-" not in mapname:
            mapname = f"DM-{mapname}"

        postmap = {"MapSelect": mapname, "SwitchMap": "Switch"}
        self.__post_url("current_game", postmap)

    def restart(self):
        self.__get_url("current_restart")
