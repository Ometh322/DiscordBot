"""Мем-команды: гачи-рулетка.

/roulette: d6 —
  1–4: живёшь (мемная фраза);
  5:   лёгкое наказание — random-звук + гифка;
  6:   тяжёлое наказание — то же + 10 секунд серверного мута
       (боту нужно право «Отключать участников» / Mute Members).
"""

import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from services.gifs import attach_random_gif
from services.interactions import safe_defer, safe_followup

log = logging.getLogger(__name__)

SAFE_LINES = (
    "Повезло… на этот раз ♂",
    "Билли одобряет твоё существование",
    "Освобождён от приседаний",
    "Гачимучи смотрит на тебя с надеждой",
    "Ты выжил. Дункан доволен",
)
LIGHT_LINES = (
    "♂ Лёгкое наказание: слушай и познавай ♂",
    "♂ Билли заметил твою наглость ♂",
)
HARD_LINES = ("♂ НАКАЗАНИЕ НЕИЗБЕЖНО ♂ 10 секунд тишины",)


class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="roulette",
        description="Гачи-рулетка: 4/6 — живёшь, 1/6 — лёгкое, 1/6 — тяжёлое наказание",
    )
    @app_commands.guild_only()
    async def roulette(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "Зайди в голосовой канал — рулетка честная только в бою 🎲",
                ephemeral=True,
            )
            return

        await safe_defer(interaction)
        roll = random.randint(1, 6)
        embed = discord.Embed(title="🎲 Гачи-рулетка")

        if roll <= 4:
            embed.description = random.choice(SAFE_LINES)
            embed.color = discord.Color.green()
            await safe_followup(interaction,embed=embed)
            return

        # Наказание: random-звук (через модуль приветствий) + гифка
        welcome = self.bot.get_cog("Welcome")
        if welcome is not None:
            from cogs.welcome import random_mumble_sound

            await welcome._run_greeting(
                interaction.user.voice.channel, random_mumble_sound()
            )
        gif = attach_random_gif(embed)

        if roll == 5:
            embed.description = random.choice(LIGHT_LINES)
            embed.color = discord.Color.orange()
            await safe_followup(interaction,embed=embed, file=gif)
            return

        # roll == 6: тяжёлое — 10 секунд серверного мута
        muted = False
        try:
            await interaction.user.edit(mute=True)
            muted = True
        except (discord.Forbidden, discord.HTTPException):
            log.warning("Мут в рулетке не вышел (нет прав) для %s", interaction.user)
        embed.description = random.choice(HARD_LINES) + (
            "" if muted else "\n(мут не вышел — у бота нет прав, свободен)"
        )
        embed.color = discord.Color.red()
        await safe_followup(interaction,embed=embed, file=gif)
        if muted:
            await asyncio.sleep(10)
            try:
                await interaction.user.edit(mute=False)
            except (discord.Forbidden, discord.HTTPException):
                log.warning("Не удалось снять мут с %s", interaction.user)


async def setup(bot):
    await bot.add_cog(Fun(bot))
