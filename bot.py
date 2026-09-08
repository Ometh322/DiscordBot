"""Точка входа Gachi Music Bot. Этап 0: подключение, /ping, проверка токенов."""

import logging
import sys

import discord
from discord.ext import commands

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("bot")


class GachiBot(commands.Bot):
    # commands.Bot нужен для cogs/load_extension; префиксные команды не
    # используются (message_content intent выключен)
    def __init__(self):
        intents = discord.Intents.default()
        intents.voice_states = True      # события голосовых каналов
        intents.members = True           # приветственные звуки (привилегированный)
        intents.message_content = False  # слэш-команды, контент не нужен
        super().__init__(command_prefix="!", help_command=None, intents=intents)

    async def setup_hook(self):
        try:
            from discord.opus import Encoder

            log.info("Opus: %s", Encoder.get_opus_version())
        except Exception:
            log.warning("Opus-кодек не загрузился — голос может не работать")

        await self.load_extension("cogs.music")
        await self.load_extension("cogs.welcome")
        await self.load_extension("cogs.gifs")
        await self.tree.sync()
        log.info("Слэш-команды синхронизированы")


bot = GachiBot()


@bot.tree.command(name="ping", description="Проверка, что бот жив")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"pong 🏓 ({bot.latency * 1000:.0f} мс)"
    )


@bot.event
async def on_ready():
    config.ensure_dirs()
    log.info("bot online: %s | серверов: %d", bot.user, len(bot.guilds))


def main() -> None:
    if not config.DISCORD_TOKEN:
        log.error("DISCORD_TOKEN не задан. Заполни .env (см. .env.example).")
        sys.exit(1)

    try:
        bot.run(config.DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        log.error("DISCORD_TOKEN неверный — перепроверь в Developer Portal.")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        log.error(
            "В Developer Portal не включён Server Members Intent: "
            "Bot -> Privileged Gateway Intents."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
