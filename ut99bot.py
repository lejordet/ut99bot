import logging
from asyncio import sleep
from collections import deque
from datetime import datetime, timedelta

import discord
from discord.ext import commands

from ut99webadmin import UT99WebAdmin

logging.basicConfig(
    filename="discord.log",
    level=logging.ERROR,
    format="[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
# set up logging to console
console = logging.StreamHandler()
console.setLevel(logging.DEBUG)
# set a format which is simpler for console use
formatter = logging.Formatter("[%(asctime)s] %(name)-12s: %(levelname)-8s %(message)s")
console.setFormatter(formatter)
# add the handler to the root logger
logging.getLogger("").addHandler(console)

logger = logging.getLogger(__name__)

INTERVAL_NOGAME = timedelta(seconds=15)
INTERVAL_GAME = timedelta(seconds=1)


class UT99Client(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = parse_config()

        self.current_rotation = "default"

        self.wa = UT99WebAdmin(
            self.cfg["waurl"], self.cfg["wauser"], self.cfg["wapass"]
        )

        self.game = discord.Game("UT99")
        self.game_status_change = False  # if true, we update the presence
        # an attribute we can access from our task
        self.msgs = deque()
        # create the background task and run it in the background
        self.bg_task = self.loop.create_task(self.my_background_task())

        self.current_game = dict()
        self.current_rules = dict()
        self.interval = INTERVAL_NOGAME
        self.announce_next = False

        self.last_check = datetime.utcnow() - INTERVAL_GAME
        self.add_commands()

    async def on_ready(self):
        logger.info("Logged in as")
        logger.info(self.user.name)
        logger.info(self.user.id)
        logger.info("------")
        await self.change_presence(status=discord.Status.online, activity=self.game)

    def __new_state(self, status):
        delta = {}
        cur = self.current_game

        quickcheck = ["mapname", "mode", "timeleft"]
        for key in quickcheck:
            if cur.get(key, "") != status[key]:
                delta[key] = (cur.get(key, "<unknown>"), status[key])

            if key not in cur:
                delta["prev_blank"] = True

        # Player check is a bit more complex
        curpl = set(cur.get("players", dict()).keys())
        newpl = set(status["players"].keys())
        # See who's joined:
        joined = newpl - curpl
        if len(joined) > 0:
            delta["players_new"] = joined

        # See who left
        left = curpl - newpl
        if len(left) > 0:
            delta["players_left"] = left

        # Check if anything's changed with the ones that remain
        for pl in curpl.intersection(newpl):
            plc = cur["players"][pl]
            pln = status["players"][pl]
            if plc["score"] != pln["score"]:
                if "players" not in delta:
                    delta["players"] = dict()

                delta["players"][pl] = (plc["score"], pln["score"])

        if status["timeleft"] == "0:00" and cur.get("timeleft", "X:XX") != "0:00":
            delta["gameover"] = True

        return delta

    async def ensure_status(self, force=False):
        checktime = datetime.utcnow()
        fetch_rules = False
        if (
            "mapname" not in self.current_game
            or force
            or checktime - self.interval > self.last_check
        ):
            try:
                status = self.wa.get_state()
            except Exception as details:
                logger.exception("Server down?", exc_info=details)
                self.game = discord.Game("UT99 changing maps")
                self.game_status_change = True
                return

            if len(self.current_rules) == 0:
                self.current_rules = self.wa.get_rules()

            game_ended_kills = False
            logger.info(status)
            delta = self.__new_state(status)

            if len(delta) > 0:
                self.current_game.update(status)
                logger.info(f"wa> fetched mapname {status['mapname']}")
                self.game = discord.Game(f"UT99 on {status['mapname']}")
                self.game_status_change = True
                self.last_check = checktime
                # also see if we have anything actionable
                if "mapname" in delta and len(status["players"]) > 0:
                    self.announce_next = True

                if "prev_blank" not in delta:
                    for pl in delta.get("players_new", set()):
                        if "(Spectator)" not in pl:
                            self.msgs.append(f"{pl} joined the game!")
                        if len(self.current_game["players"]) == 1:
                            self.announce_next = True
                            fetch_rules = True
                    for pl in delta.get("players_left", set()):
                        if "(Spectator)" not in pl:
                            self.msgs.append(f"{pl} left the game!")

                    if "mode" in delta:
                        self.msgs.append(f"Game mode is {delta['mode'][1]}")
                        fetch_rules = True
                    if "players" in delta:  # scores changed
                        fraglimit = self.current_rules.get("Frag Limit", 15)
                        for _, sc in delta["players"].items():
                            if int(sc[1]) >= fraglimit:
                                game_ended_kills = True
                else:
                    fetch_rules = True

                if "gameover" in delta or game_ended_kills:
                    if not game_ended_kills:
                        self.msgs.append("Game ended on time limit hit!")
                    else:
                        self.msgs.append("Game ended on frag limit hit!")

                    for cli in sorted(
                        self.current_game["players"].values(),
                        key=lambda x: x["score"],
                        reverse=True,
                    ):
                        self.msgs.append(
                            f"> {cli.get('name', '<unknown>')}: "
                            f"{cli.get('score', '0?')} kills"
                        )

        if self.announce_next:
            self.msgs.append(
                f"New game starting on {self.current_game['mapname']}, "
                f"{len(self.current_game['players'])} in game"
            )
            fetch_rules = True
            self.announce_next = False


        if fetch_rules:
            self.current_rules = self.wa.get_rules()



        if len(self.current_game.get("players", [])) > 0:
            self.interval = INTERVAL_GAME
        else:
            self.interval = INTERVAL_NOGAME

        if self.game_status_change:
            await self.change_presence(status=discord.Status.online, activity=self.game)
            self.game_status_change = False

    def add_commands(self):
        @self.command(name="status", pass_context=True)
        async def status(ctx):
            """See who's playing and where"""
            logger.info(f"status requested: {ctx}")
            await self.ensure_status(True)
            await ctx.channel.send(
                f"status: {len(self.current_game['players'])} players on "
                f"{self.current_game['mapname']} ({self.current_game['mode']}, "
                f"{self.current_game['timeleft']} remaining)"
            )
            for _, cli in self.current_game["players"].items():
                await ctx.channel.send(
                    f"> {cli.get('name', '<unknown>')}: "
                    f"{cli.get('score', '0?')} kills"
                )

        @self.command(name="stats", pass_context=True)
        async def stats(ctx, limit: str = "all"):
            """Show historical stats

            Args:
                limit: Show stats from 'all', 'week', 'today', yyyy-mm-dd
                       unknown text will be taken as 'all'
            """
            await ctx.channel.send("Stats not implemented")

        @self.command(name="numplayers", pass_context=True)
        async def numplayers(ctx, num: str = ""):
            """ Get/set minimum number of players (including bots) 
            
            Args:
                num: Number of players, must be > 1 - or blank to get current setting
            """
            if num != "":
                try:
                    num_ = int(num)
                    self.wa.set_min_players(num_)
                except ValueError:
                    await ctx.channel.send(f"ERROR! {num} is not a number")

            await ctx.channel.send(f"Currently set to minimum {self.wa.get_min_players()} players")
                
        @self.command(name="instagib", pass_context=True)
        async def instagib(ctx, onoff: str = "1"):
            """ Turn instagib on/off

            Args:
                onoff: 1 for on, 0 for off
            """

            if onoff == "0":
                self.wa.del_mutator("InstaGib")
                await ctx.channel.send("InstaGib OFF! Use ?restart to reload level")
            else:
                self.wa.add_mutator("InstaGib")
                await ctx.channel.send("InstaGib ON! Use ?restart to reload level")

        @self.command(name="restart", pass_context=True)
        async def restart(ctx):
            """ Restart level """
            self.wa.restart()
            await ctx.channel.send("Restarted level, please wait a few seconds")
            self.announce_next = True
            await self.ensure_status(True)

        @self.command(name="map", pass_context=True)
        async def switch_map(ctx, newmap: str):
            """ Restart level """
            self.wa.switch_map(newmap)
            await ctx.channel.send("Changing map, please wait a few seconds")
            await sleep(5.0)  # Give it a few seconds
            self.announce_next = True
            await self.ensure_status(True)
        
    async def my_background_task(self):
        await self.wait_until_ready()
        channel = self.get_channel(int(self.cfg["channel"]))

        while not self.is_closed():
            msg = None
            try:
                msg = self.msgs.popleft()
            except IndexError:
                await sleep(0.01)  # tiny sleep to avoid spamming CPU

            if msg is not None:
                await channel.send(msg)
            else:
                await self.ensure_status()


def parse_config():
    cfg = dict()
    with open("secrets.ini", "rt") as f:
        for line in f.readlines():
            k, v = line.strip().split("=")
            cfg[k] = v
    return cfg


def main():
    cfg = parse_config()
    intents = discord.Intents.default()
    intents.typing = False
    intents.presences = False
    client = UT99Client(command_prefix="?", intents=intents)

    client.run(cfg["token"])


if __name__ == "__main__":
    main()
