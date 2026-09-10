"""Слэш-команды поиска и воспроизведения GACHI-музыки из SoundCloud."""

import asyncio
import logging
import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from services.catalog import Catalog
from services.gifs import attach_random_gif
from services.interactions import safe_defer, safe_followup
from services.player import PlayerControls, PlayerManager, fmt_duration
from services.soundcloud import (
    SEARCH_QUERIES,
    SoundCloud,
    SoundCloudError,
    detect_lang,
    is_gachi,
)

log = logging.getLogger(__name__)

# Случайная страница выдачи для разнообразия сетевого поиска
SEARCH_OFFSETS = (0, 10, 20, 30)
WARMUP_MIN_PER_LANG = 30  # до скольких треков прогревать каталог при старте


class Music(commands.Cog):
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.sc = SoundCloud()
        self.catalog = Catalog()
        self.players = PlayerManager(bot, self.sc, self.catalog)

    async def cog_load(self):
        asyncio.get_running_loop().create_task(self._warmup_catalog())

    async def _warmup_catalog(self):
        """Фоновый прогрев: если языка мало в каталоге — ищем и добавляем."""
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            return  # бот не запущен (тестовый прогон)
        for lang in ("ru", "ang"):
            if await asyncio.to_thread(self.catalog.count, lang) >= WARMUP_MIN_PER_LANG:
                continue
            query = random.choice(SEARCH_QUERIES[lang])
            try:
                tracks = await asyncio.to_thread(self.sc.search, query, count=30)
            except SoundCloudError as e:
                log.warning("Прогрев каталога %s: %s", lang, e)
                continue
            added = await asyncio.to_thread(self.catalog.upsert, tracks, lang)
            log.info("Каталог %s: +%d (всего %d)", lang, added,
                     await asyncio.to_thread(self.catalog.count, lang))

    # ---- вспомогательное ----

    async def _connect_to_author(self, interaction: discord.Interaction) -> bool:
        """Подключает бота к каналу автора команды. False — если отказали."""
        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        try:
            if vc is None:
                await channel.connect()
            elif vc.channel != channel:
                await safe_followup(interaction,
                    f"Я сейчас в другом канале ({vc.channel.mention}) — "
                    "подойди туда или попроси /leave."
                )
                return False
        except discord.ClientException:
            log.exception("Подключение к %s", channel)
            return False
        return True

    # ---- /play ----

    @app_commands.command(
        name="play",
        description="Найти любой трек на SoundCloud и поставить в очередь",
    )
    @app_commands.describe(query="Что искать (название / исполнитель)")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "Зайди в голосовой канал — я подключусь к тебе 🎧", ephemeral=True
            )
            return

        await safe_defer(interaction)
        player = self.players.get(interaction.guild)
        player.text_channel = interaction.channel

        try:
            tracks = await asyncio.to_thread(
                self.sc.search, query, count=10, gachi_only=False
            )
        except SoundCloudError as e:
            await safe_followup(interaction,f"❌ SoundCloud недоступен: {e}")
            return

        if not tracks:
            await safe_followup(interaction,
                f"По запросу «{query}» ничего не нашлось 🤷"
            )
            return
        track = tracks[0]

        # GACHI-треки с такого поиска тоже копим в каталог
        gachi_found = [t for t in tracks if is_gachi(t)]
        if gachi_found:
            by_lang = {"ru": [], "ang": []}
            for t in gachi_found:
                by_lang[detect_lang(t)].append(t)
            for l, group in by_lang.items():
                if group:
                    await asyncio.to_thread(self.catalog.upsert, group, l)
        await asyncio.to_thread(
            self.catalog.add_request, interaction.guild_id,
            interaction.user.id, [track],
        )

        if not await self._connect_to_author(interaction):
            return

        position = await player.enqueue(track, announce_start=False)

        embed = discord.Embed(title=track.title or "Без названия")
        embed.set_author(name="Найдено на SoundCloud")
        embed.add_field(name="Исполнитель", value=track.artist or "—", inline=True)
        embed.add_field(
            name="Длительность", value=fmt_duration(track.duration), inline=True
        )
        embed.url = track.page_url
        gif = attach_random_gif(embed)
        extra = {"file": gif} if gif else {}  # file=None отправлять нельзя
        await safe_followup(interaction,
            "▶ Играю" if position == 1 else f"➕ В очереди (позиция {position})",
            embed=embed,
            view=PlayerControls(player),
            **extra,
        )

    # ---- /gachi ----

    @app_commands.command(
        name="gachi",
        description="Добавить случайные GACHI-треки в очередь",
    )
    @app_commands.describe(
        count="Сколько треков добавить (1–10)",
        language="Язык: ru — искать «гачи…» (по умолчанию), ang — «gachi…»",
    )
    @app_commands.guild_only()
    async def gachi(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 10],
        language: Literal["ru", "ang"] = "ru",
    ):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "Зайди в голосовой канал — я подключусь к тебе 🎧", ephemeral=True
            )
            return

        await safe_defer(interaction)
        player = self.players.get(interaction.guild)
        player.text_channel = interaction.channel
        lang = "ru" if language == "ru" else "ang"

        # 1) Быстрая выборка из локального каталога
        picked = await asyncio.to_thread(
            self.catalog.pick, lang, count, interaction.guild_id
        )

        # 2) Если каталог дал мало — сеть (параллельные вариации запроса)
        last_error = None
        if len(picked) < count:
            pool = SEARCH_QUERIES[lang]
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

            # Всё найденное — в каталог (он растёт сам)
            if candidates:
                await asyncio.to_thread(self.catalog.upsert, candidates, lang)

            recent = await asyncio.to_thread(
                self.catalog.recent_ids, interaction.guild_id
            )
            already = {t.track_id for t in picked}
            fresh = [
                t for t in candidates
                if t.track_id not in recent and t.track_id not in already
            ]
            if not fresh and candidates:  # всё играло — лучше повтор, чем пустота
                fresh = [t for t in candidates if t.track_id not in already]
            random.shuffle(fresh)
            picked.extend(fresh[: count - len(picked)])

        if not picked:
            msg = f"❌ SoundCloud недоступен: {last_error}" if last_error \
                else "Не нашлось GACHI-треков, попробуй ещё раз 🤷"
            await safe_followup(interaction,msg)
            return

        # Подключаемся к каналу автора
        if not await self._connect_to_author(interaction):
            return

        await asyncio.to_thread(self.catalog.mark_played, interaction.guild_id, picked)
        await asyncio.to_thread(
            self.catalog.add_request, interaction.guild_id, interaction.user.id, picked
        )
        for t in picked:
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
        gif = attach_random_gif(embed)
        extra = {"file": gif} if gif else {}  # file=None отправлять нельзя
        await safe_followup(interaction,
            "▶ Первый уже играет" if len(picked) > 1 else "▶ Играю",
            embed=embed,
            view=PlayerControls(player),
            **extra,
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

    # ---- /top ----

    @app_commands.command(
        name="top",
        description="Топ гачирусов сервера и чарт треков по ♂-одобрениям",
    )
    @app_commands.guild_only()
    async def top(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        week = await asyncio.to_thread(self.catalog.top_requesters, gid, 7, 10)
        total = await asyncio.to_thread(self.catalog.top_requesters, gid, None, 10)
        chart = await asyncio.to_thread(self.catalog.top_tracks, gid, 10)

        def user_name(uid: int) -> str:
            member = interaction.guild.get_member(uid)
            return member.display_name if member else f"<@{uid}>"

        def fmt(rows, mapper):
            return "\n".join(
                f"{i}. {mapper(row)}" for i, row in enumerate(rows, start=1)
            ) or "—"

        embed = discord.Embed(title="🏆 Гачирусы сервера")
        embed.add_field(
            name="Неделя (кто заказывал)",
            value=fmt(week, lambda r: f"{user_name(r[0])} — {r[1]}"),
            inline=False,
        )
        embed.add_field(
            name="За всё время",
            value=fmt(total, lambda r: f"{user_name(r[0])} — {r[1]}"),
            inline=False,
        )
        embed.add_field(
            name="♂ Чарт треков (одобрения)",
            value=fmt(chart, lambda r: f"**{r[0]}** — {r[1]} ♂×{r[2]}"),
            inline=False,
        )
        embed.set_footer(text="♂ — кнопка одобрения под «Сейчас играет»")
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
