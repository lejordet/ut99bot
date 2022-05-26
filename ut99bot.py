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

INTERVAL_STATUS = timedelta(seconds=15)

class UT99Client(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = parse_config()

        self.current_rotation = "default"

        self.wa = UT99WebAdmin(self.cfg["waurl"], self.cfg["wauser"], self.cfg["wapass"])

        self.game = discord.Game("UT99")
        self.game_status_change = False  # if true, we update the presence
        # an attribute we can access from our task
        self.msgs = deque()
        # create the background task and run it in the background
        self.bg_task = self.loop.create_task(self.my_background_task())

        self.current_game = dict()
        self.last_check = datetime.utcnow() - INTERVAL_STATUS
        self.add_commands()

    async def on_ready(self):
        logger.info("Logged in as")
        logger.info(self.user.name)
        logger.info(self.user.id)
        logger.info("------")
        await self.change_presence(status=discord.Status.online, activity=self.game)


    async def ensure_status(self, force=False):
        checktime = datetime.utcnow()
        if "mapname" not in self.current_game or force or checktime - INTERVAL_STATUS > self.last_check:
            status = self.wa.get_state()
            logger.info(status)
            self.current_game.update(status)
            logger.info(f"wa> fetched mapname {status['mapname']}")
            self.game = discord.Game(f"UT99 on {status['mapname']}")
            self.game_status_change = True
            self.last_check = checktime

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
                f"{self.current_game['mapname']} ({self.current_game['mode']}, {self.current_game['timeleft']} remaining)"
            )
            for cli in self.current_game["players"]:
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
