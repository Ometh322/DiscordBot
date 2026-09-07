"""Слэш-команды поиска и воспроизведения GACHI-музыки из ВК."""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.player import PlayerManager, fmt_duration
from services.vk import VkMusic, VkMusicError

log = logging.getLogger(__name__)


class Music(commands.Cog):
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.vk = VkMusic()
        self.players = PlayerManager(bot, self.vk)

    # ---- /gachi ----

    @app_commands.command(name="gachi", description="Найти GACHI-трек в ВК и поставить")
    @app_commands.describe(query="Что искать (например: gachi remix, Gymnasium…)")
    @app_commands.guild_only()
    async def gachi(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "Зайди в голосовой канал — я подключусь к тебе 🎧", ephemeral=True
            )
            return

        await interaction.response.defer()  # поиск в ВК занимает пару секунд
        player = self.players.get(interaction.guild)
        player.text_channel = interaction.channel

        try:
            tracks = await asyncio.to_thread(self.vk.search, query)
            if not tracks:  # запасной проход: добавляем gachi к запросу
                tracks = await asyncio.to_thread(
                    self.vk.search, f"{query} gachi", gachi_only=False
                )
        except VkMusicError as e:
            await interaction.followup.send(f"❌ VK недоступен: {e}")
            return

        if not tracks:
            await interaction.followup.send(
                f"По запросу «{query}» ничего GACHI/ГАЧИ не нашлось 🤷"
            )
            return
        track = tracks[0]

        # подключаемся к каналу автора
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

        position = await player.enqueue(track, announce_start=False)

        embed = discord.Embed(title=track.title or "Без названия")
        embed.set_author(name="Найдено в ВК")
        embed.add_field(name="Исполнитель", value=track.artist or "—", inline=True)
        embed.add_field(
            name="Длительность", value=fmt_duration(track.duration), inline=True
        )
        embed.url = track.vk_url
        if position == 1:
            await interaction.followup.send("▶ Играю", embed=embed)
        else:
            await interaction.followup.send(
                f"➕ В очереди (позиция {position})", embed=embed
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
