"""Управление гифками: /gif (загрузка вложением) и /gifs (список)."""

import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import config
from services.gifs import (
    GIF_EXTENSIONS,
    MAX_GIF_BYTES,
    MAX_GIF_FILES,
    _url_safe_name,
    gif_files,
)

log = logging.getLogger(__name__)


class Gifs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="gif",
        description="Загрузить гифку для сообщений «Сейчас играет»",
    )
    @app_commands.describe(file="Картинка: gif, apng, png, jpg, webp (до 8 МБ)")
    @app_commands.guild_only()
    async def gif(self, interaction: discord.Interaction, file: discord.Attachment):
        ext = Path(file.filename).suffix.lower()
        if ext not in GIF_EXTENSIONS:
            await interaction.response.send_message(
                "Поддерживаю только: " + ", ".join(GIF_EXTENSIONS), ephemeral=True
            )
            return
        if file.size > MAX_GIF_BYTES:
            await interaction.response.send_message(
                "Файл больше 8 МБ — сожми гифку.", ephemeral=True
            )
            return

        config.ensure_dirs()
        files = gif_files()
        name = _url_safe_name(file.filename)
        exists = (config.GIFS_DIR / name).is_file()
        if not exists and len(files) >= MAX_GIF_FILES:
            await interaction.response.send_message(
                f"В папке уже {len(files)} гифок — почисть лишние.", ephemeral=True
            )
            return

        await interaction.response.defer()
        try:
            await file.save(config.GIFS_DIR / name)
        except (discord.HTTPException, OSError) as e:
            log.exception("Сохранение гифки %s", name)
            await interaction.followup.send(f"❌ Не удалось сохранить: {e}")
            return

        action = "обновлена" if exists else "сохранена"
        await interaction.followup.send(
            f"🖼 Гифка **{name}** {action} — теперь появится в ротации "
            f"(всего: {len(gif_files())})."
        )

    @app_commands.command(
        name="gifs",
        description="Какие гифки есть в ротации",
    )
    @app_commands.guild_only()
    async def gifs(self, interaction: discord.Interaction):
        files = gif_files()
        if not files:
            await interaction.response.send_message(
                "Папка гифок пуста — загрузи первую через /gif."
            )
            return
        total_mb = sum(p.stat().st_size for p in files) / 1024 / 1024
        lines = [f"{i}. {p.name} ({p.stat().st_size / 1024:.0f} КБ)"
                 for i, p in enumerate(files[:20], start=1)]
        if len(files) > 20:
            lines.append(f"…и ещё {len(files) - 20}")
        embed = discord.Embed(
            title=f"🖼 Гифки: {len(files)} ({total_mb:.1f} МБ)",
            description="\n".join(lines),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Gifs(bot))
