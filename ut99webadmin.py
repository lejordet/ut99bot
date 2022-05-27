import re

import requests
from bs4 import BeautifulSoup

PLAYER_COLUMNS = ["name", "team", "ping", "score", "ip"]
HEADER_RE = re.compile(r"(.+?)\sin\s(.+?)\s\(\s(\d+:\d+)")


def sanitize_wa_text(text):
    return text.replace("\xa0", " ")


class UT99WebAdmin(object):
    def __init__(self, url, username, password):
        self.url = url
        self.username = username
        self.password = password

    def __get_url(self, subpath):
        return requests.get(self.url + subpath, auth=(self.username, self.password))

    def __parse(self, subpath):
        return BeautifulSoup(self.__get_url(subpath).text, features="lxml")

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
