"""Звуковые приветствия: личные аудиофайлы из data/sounds.

Файлы подбираются по имени: `<user_id>.mp3`, `<username>.mp3` или
`<display_name>.mp3` (в любом поддерживаемом формате: mp3/ogg/wav/m4a/
flac/opus). Имя файла — логин или отображаемое имя в нижнем регистре,
без пробелов (пробелы вырезаются).

Проигрывание:
- участник зашёл в голосовой канал → бот играет его файл
  (подключается следом и выходит после; музыку не прерывает);
- /hello — играет файл вызвавшего, а если персонального нет —
  случайный из папки.
Антиспам: один и тот же участник — не чаще раза в 30 секунд.
"""

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from services.player import FFMPEG_BEFORE_OPTIONS

log = logging.getLogger(__name__)

SOUND_EXTENSIONS = (".mp3", ".ogg", ".wav", ".m4a", ".flac", ".opus")
JOIN_COOLDOWN_SECONDS = 30.0


def _sanitize(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum() or c in "-_")


def find_sound(member: discord.Member) -> Optional[Path]:
    """Персональный файл участника: по id, затем по логину/имени."""
    folder = config.SOUNDS_DIR
    if not folder.is_dir():
        return None
    bases = [str(member.id), _sanitize(member.name), _sanitize(member.display_name)]
    for base in bases:
        if not base:
            continue
        for ext in SOUND_EXTENSIONS:
            path = folder / f"{base}{ext}"
            if path.is_file():
                return path
    return None


def random_sound() -> Optional[Path]:
    folder = config.SOUNDS_DIR
    if not folder.is_dir():
        return None
    files = [
        p for p in folder.iterdir()
        if p.suffix.lower() in SOUND_EXTENSIONS
    ]
    return random.choice(files) if files else None


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldowns = {}  # user_id -> monotonic время последнего звука

    # ---- вспомогательное ----

    def _cooldown_ok(self, user_id: int) -> bool:
        now = time.monotonic()
        if now - self._cooldowns.get(user_id, 0.0) < JOIN_COOLDOWN_SECONDS:
            return False
        self._cooldowns[user_id] = now
        return True

    def _play(self, vc: discord.VoiceClient, path: Path, leave_after: bool) -> None:
        def _after(error):
            if error:
                log.error("Ошибка воспроизведения %s: %s", path.name, error)
            if leave_after:
                asyncio.run_coroutine_threadsafe(
                    self._leave_when_idle(vc), self.bot.loop
                )

        source = discord.FFmpegPCMAudio(
            str(path),
            executable=config.FFMPEG_PATH,
            before_options=FFMPEG_BEFORE_OPTIONS,
        )
        vc.play(source, after=_after)

    async def _leave_when_idle(self, vc: discord.VoiceClient) -> None:
        await asyncio.sleep(1.0)
        try:
            if vc.is_connected() and not vc.is_playing() and not vc.is_paused():
                await vc.disconnect(force=True)
        except Exception:
            log.exception("Автовыход после приветствия")

    # ---- вход в голосовой канал ----

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot or before.channel is not None or after.channel is None:
            return  # боты, перемещения и выходы не приветствуем

        sound = find_sound(member)
        if sound is None or not self._cooldown_ok(member.id):
            return

        vc = member.guild.voice_client
        try:
            if vc is None:
                vc = await after.channel.connect()
                leave_after = True
            elif vc.channel == after.channel:
                leave_after = False
            else:
                return  # бот занят в другом канале
        except (discord.ClientException, asyncio.TimeoutError):
            log.exception("Подключение для приветствия %s", member)
            return

        if vc.is_playing() or vc.is_paused():
            if leave_after:  # подключились, а канал занят музыкой — уходим
                await vc.disconnect(force=True)
            return  # музыку не прерываем

        log.info("Приветствие %s: %s", member, sound.name)
        self._play(vc, sound, leave_after)

    # ---- /hello ----

    @app_commands.command(
        name="hello",
        description="Сыграть твой персональный звук (или случайный из папки)",
    )
    @app_commands.guild_only()
    async def hello(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "Зайди в голосовой канал 🎧", ephemeral=True
            )
            return

        sound = find_sound(interaction.user) or random_sound()
        if sound is None:
            await interaction.response.send_message(
                "В папке data/sounds ещё нет аудиофайлов.", ephemeral=True
            )
            return

        vc = interaction.guild.voice_client
        try:
            if vc is None:
                vc = await interaction.user.voice.channel.connect()
                leave_after = True
            elif vc.channel == interaction.user.voice.channel:
                leave_after = False
            else:
                await interaction.response.send_message(
                    f"Я сейчас в другом канале ({vc.channel.mention}).",
                    ephemeral=True,
                )
                return
        except (discord.ClientException, asyncio.TimeoutError):
            log.exception("Подключение /hello")
            await interaction.response.send_message(
                "Не смог подключиться к каналу.", ephemeral=True
            )
            return

        if vc.is_playing() or vc.is_paused():
            await interaction.response.send_message(
                "Сейчас играет музыка — сначала ⏹ или /stop.", ephemeral=True
            )
            return

        self._cooldowns[interaction.user.id] = time.monotonic()
        self._play(vc, sound, leave_after)
        await interaction.response.send_message(f"🔊 {sound.stem}")


async def setup(bot):
    await bot.add_cog(Welcome(bot))
