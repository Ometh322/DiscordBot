"""Слэш-команды поиска и воспроизведения GACHI-музыки из SoundCloud."""

import asyncio
import logging
import random
from collections import deque
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from services.player import PlayerControls, PlayerManager, fmt_duration
from services.soundcloud import SEARCH_QUERIES, SoundCloud, SoundCloudError

log = logging.getLogger(__name__)

# Сколько последних треков сервера не повторять при случайной выборке
RECENT_MAX = 60
# Случайная страница выдачи для разнообразия
SEARCH_OFFSETS = (0, 10, 20, 30)


class Music(commands.Cog):
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.sc = SoundCloud()
        self.players = PlayerManager(bot, self.sc)
        self._recent = {}  # guild_id -> deque[track_id] (история против повторов)

    # ---- /gachi ----

    @app_commands.command(
        name="gachi",
        description="Добавить случайные GACHI-треки в очередь",
    )
    @app_commands.describe(
        language="Язык: ru — искать «гачи…», ang — искать «gachi…»",
        count="Сколько треков добавить (1–10)",
    )
    @app_commands.guild_only()
    async def gachi(
        self,
        interaction: discord.Interaction,
        language: Literal["ru", "ang"],
        count: app_commands.Range[int, 1, 10] = 3,
    ):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "Зайди в голосовой канал — я подключусь к тебе 🎧", ephemeral=True
            )
            return

        await interaction.response.defer()
        player = self.players.get(interaction.guild)
        player.text_channel = interaction.channel
        recent = self._recent.setdefault(
            interaction.guild_id, deque(maxlen=RECENT_MAX)
        )

        # Случайные вариации запроса + случайная страница выдачи; поиск параллельно
        pool = SEARCH_QUERIES["ru" if language == "ru" else "ang"]
        queries = random.sample(pool, k=min(2, len(pool)))
        offset = random.choice(SEARCH_OFFSETS)

        results = await asyncio.gather(
            *(
                asyncio.to_thread(self.sc.search, q, count=20, offset=offset)
                for q in queries
            ),
            return_exceptions=True,
        )
        candidates, last_error = [], None
        for res in results:
            if isinstance(res, BaseException):
                last_error = res
                continue
            candidates.extend(res)

        # Дедупликация + отсев недавно игравшего
        unique = {}
        for t in candidates:
            unique.setdefault(t.full_id, t)
        fresh = [t for t in unique.values() if t.full_id not in recent]
        if not fresh and unique:  # всё уже играло — лучше повтор, чем пустота
            fresh = list(unique.values())
        random.shuffle(fresh)
        picked = fresh[:count]

        if not picked:
            msg = f"❌ SoundCloud недоступен: {last_error}" if last_error \
                else "Не нашлось GACHI-треков, попробуй ещё раз 🤷"
            await interaction.followup.send(msg)
            return

        # Подключаемся к каналу автора
        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        try:
            if vc is None:
                await channel.connect()
            elif vc.channel != channel:
                await interaction.followup.send(
                    f"Я сейчас в другом канале ({vc.channel.mention}) — "
                    "подойди туда или попроси /leave."
                )
                return
        except discord.ClientException:
            log.exception("Подключение к %s", channel)

        for t in picked:
            recent.append(t.full_id)
            await player.enqueue(t)

        lines = [
            f"{i}. **{t.title}** — {t.artist} ({fmt_duration(t.duration)})"
            for i, t in enumerate(picked, start=1)
        ]
        embed = discord.Embed(
            title=f"🎶 Добавлено: {len(picked)} "
                  f"({'гачи' if language == 'ru' else 'gachi'})",
            description="\n".join(lines),
        )
        await interaction.followup.send(
            "▶ Первый уже играет" if len(picked) > 1 else "▶ Играю",
            embed=embed,
            view=PlayerControls(player),
        )

    # ---- /skip ----

    @app_commands.command(name="skip", description="Пропустить текущий трек")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild)
        vc = interaction.guild.voice_client
        if not (vc and (vc.is_playing() or vc.is_paused())):
            await interaction.response.send_message(
                "Сейчас ничего не играет.", ephemeral=True
            )
            return
        title = player.current.title if player.current else "?"
        await player.skip()
        await interaction.response.send_message(f"⏭ Пропустил: **{title}**")

    # ---- /stop ----

    @app_commands.command(name="stop", description="Остановить музыку и очистить очередь")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild)
        cleared = player.stop()
        note = f" (из очереди убрал {cleared})" if cleared else ""
        await interaction.response.send_message(f"⏹ Остановлено{note}.")

    # ---- /queue ----

    @app_commands.command(name="queue", description="Что сейчас играет и что дальше")
    @app_commands.guild_only()
    async def queue_cmd(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild)
        if not player.current and not player.queue:
            await interaction.response.send_message(
                "Очередь пуста. Добавь что-нибудь через /gachi 🎵"
            )
            return

        lines = []
        if player.current:
            lines.append(
                f"▶ **{player.current.title}** — {player.current.artist} "
                f"({fmt_duration(player.current.duration)})"
            )
        for i, t in enumerate(player.queue[:10], start=1):
            lines.append(f"{i}. {t.title} — {t.artist} ({fmt_duration(t.duration)})")
        if len(player.queue) > 10:
            lines.append(f"…и ещё {len(player.queue) - 10}")

        embed = discord.Embed(title="🎼 Очередь", description="\n".join(lines))
        await interaction.response.send_message(embed=embed)

    # ---- /leave ----

    @app_commands.command(name="leave", description="Выйти из голосового канала")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            await interaction.response.send_message(
                "Меня нет в голосовом канале.", ephemeral=True
            )
            return
        await self.players.get(interaction.guild).disconnect()
        await interaction.response.send_message("👋 Вышел из канала.")


async def setup(bot):
    await bot.add_cog(Music(bot))
