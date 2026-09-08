"""Звуковые приветствия: случайные аудиофайлы из data/sounds.

Все файлы из папки — общий пул. Когда участник заходит в голосовой канал
(или вызывает /hello), бот играет СЛУЧАЙНЫЙ файл из папки:
- если играла музыка — она останавливается, приветствие проигрывается,
  затем трек возобновляется (тем же треком, очередь не двигается);
- если бота не было в канале — он подключается следом и после уходит.

Антиспам: /hello — не чаще раза в 3 секунды; на вход в канал
ограничений нет.
Форматы: mp3, ogg, wav, m4a, flac, opus. Загружать можно командой
/sound (вложением) или просто копируя файлы в папку.
"""

import asyncio
import logging
import math
import random
import time
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from services.player import GuildPlayer

log = logging.getLogger(__name__)

SOUND_EXTENSIONS = (".mp3", ".ogg", ".wav", ".m4a", ".flac", ".opus")
HELLO_COOLDOWN_SECONDS = 3.0
MAX_SOUND_BYTES = 10 * 1024 * 1024   # 10 МБ на файл
MAX_SOUND_FILES = 100                # предохранитель от замусоривания


def _safe_stem(stem: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:50] or "sound"


def _sound_files() -> list:
    folder = config.SOUNDS_DIR
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir() if p.suffix.lower() in SOUND_EXTENSIONS
    )


def random_sound() -> Optional[Path]:
    files = _sound_files()
    return random.choice(files) if files else None


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._hello_cd = {}  # user_id -> время последнего /hello

    # ---- вспомогательное ----

    def _music_player(self, guild: discord.Guild) -> Optional[GuildPlayer]:
        music = self.bot.get_cog("Music")
        return music.players.get(guild) if music else None

    def _cooldown_ok(self, user_id: int, store: dict, seconds: float) -> bool:
        now = time.monotonic()
        if now - store.get(user_id, 0.0) < seconds:
            return False
        store[user_id] = now
        return True

    async def _play_greeting(
        self, vc: discord.VoiceClient, path: Path, leave_after: bool,
        player: Optional[GuildPlayer], music_interrupted: bool,
    ) -> None:
        def _after(error):
            if error:
                log.error("Ошибка воспроизведения %s: %s", path.name, error)
            if leave_after:
                asyncio.run_coroutine_threadsafe(
                    self._leave_when_idle(vc), self.bot.loop
                )
            if music_interrupted and player is not None:
                asyncio.run_coroutine_threadsafe(
                    player.resume_after_greeting(), self.bot.loop
                )

        try:
            # Усиление фильтром FFmpeg + лимитер: громко, но без жёсткого
            # клиппинга. ВАЖНО: options — только строкой (dict FFmpegPCMAudio
            # молча игнорирует). Локальным файлам -reconnect не нужен.
            gain_db = 20 * math.log10(config.WELCOME_VOLUME)
            source = discord.FFmpegPCMAudio(
                str(path),
                executable=config.FFMPEG_PATH,
                options=f"-af volume={gain_db:.1f}dB,alimiter=limit=0.95",
            )
            vc.play(source, after=_after)
        except Exception:
            log.exception("Приветствие %s не заиграло", path.name)
            if music_interrupted and player is not None:
                await player.resume_after_greeting()  # не бросаем музыку молчащей

    async def _leave_when_idle(self, vc: discord.VoiceClient) -> None:
        await asyncio.sleep(1.0)
        try:
            if vc.is_connected() and not vc.is_playing() and not vc.is_paused():
                await vc.disconnect(force=True)
        except Exception:
            log.exception("Автовыход после приветствия")

    async def _run_greeting(self, channel, user_id: int) -> Optional[Path]:
        """Подключение + играем случайный файл (кулдаун проверяет вызывающий).
        Возвращает сыгранный путь."""
        sound = random_sound()
        if sound is None:
            return None

        vc = channel.guild.voice_client
        player = self._music_player(channel.guild)
        music_interrupted = False
        try:
            if vc is None:
                vc = await channel.connect()
                leave_after = True
            elif vc.channel == channel:
                leave_after = False
                music_interrupted = player.pause_for_greeting()  # sync: bool
            else:
                return None  # бот занят в другом канале
        except (discord.ClientException, asyncio.TimeoutError):
            log.exception("Подключение для приветствия")
            return None

        if music_interrupted:
            # даём голосу освободиться после vc.stop(), иначе vc.play падает
            # с «Already playing audio» и приветствие молча сгорает
            await asyncio.sleep(0.35)

        log.info("Приветствие: %s", sound.name)
        await self._play_greeting(vc, sound, leave_after, player, music_interrupted)
        return sound

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

        await self._run_greeting(after.channel, member.id)

    # ---- /hello ----

    @app_commands.command(
        name="hello",
        description="Сыграть случайный звук приветствия",
    )
    @app_commands.guild_only()
    async def hello(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "Зайди в голосовой канал 🎧", ephemeral=True
            )
            return
        if random_sound() is None:
            await interaction.response.send_message(
                "В папке data/sounds ещё нет аудиофайлов.", ephemeral=True
            )
            return

        if not self._cooldown_ok(
            interaction.user.id, self._hello_cd, HELLO_COOLDOWN_SECONDS
        ):
            await interaction.response.send_message(
                "Слишком часто — подожди пару секунд ⏳", ephemeral=True
            )
            return
        sound = await self._run_greeting(
            interaction.user.voice.channel, interaction.user.id
        )
        if sound is None:
            await interaction.response.send_message(
                "Не смог (в папке нет файлов или бот занят в другом канале).",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(f"🔊 {sound.stem}")


    # ---- /sound: загрузка ----

    @app_commands.command(
        name="sound",
        description="Загрузить звук приветствия (вложением)",
    )
    @app_commands.describe(file="Аудиофайл: mp3, ogg, wav, m4a, flac, opus (до 10 МБ)")
    @app_commands.guild_only()
    async def sound(self, interaction: discord.Interaction, file: discord.Attachment):
        ext = Path(file.filename).suffix.lower()
        if ext not in SOUND_EXTENSIONS:
            await interaction.response.send_message(
                "Поддерживаю только: " + ", ".join(SOUND_EXTENSIONS), ephemeral=True
            )
            return
        if file.size > MAX_SOUND_BYTES:
            await interaction.response.send_message(
                "Файл больше 10 МБ — обрежь или сожми его.", ephemeral=True
            )
            return

        config.ensure_dirs()
        files = _sound_files()
        name = _safe_stem(Path(file.filename).stem) + ext
        exists = (config.SOUNDS_DIR / name).is_file()
        if not exists and len(files) >= MAX_SOUND_FILES:
            await interaction.response.send_message(
                f"В папке уже {len(files)} звуков — почисть лишние.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)
        try:
            await file.save(config.SOUNDS_DIR / name)
        except (discord.HTTPException, OSError) as e:
            log.exception("Сохранение звука %s", name)
            await interaction.followup.send(f"❌ Не удалось сохранить: {e}")
            return

        action = "обновлён" if exists else "сохранён"
        await interaction.followup.send(
            f"✅ Звук **{name}** {action} — он в случайной ротации приветствий "
            f"(всего в папке: {len(_sound_files())})."
        )

    # ---- /sounds: список ----

    @app_commands.command(
        name="sounds",
        description="Какие звуки приветствий есть в ротации",
    )
    @app_commands.guild_only()
    async def sounds(self, interaction: discord.Interaction):
        files = _sound_files()
        if not files:
            await interaction.response.send_message(
                "Папка приветствий пуста — загрузи первый через /sound."
            )
            return
        total_mb = sum(p.stat().st_size for p in files) / 1024 / 1024
        lines = [f"{i}. {p.name} ({p.stat().st_size / 1024:.0f} КБ)"
                 for i, p in enumerate(files[:20], start=1)]
        if len(files) > 20:
            lines.append(f"…и ещё {len(files) - 20}")
        embed = discord.Embed(
            title=f"🔊 Звуки приветствий: {len(files)} ({total_mb:.1f} МБ)",
            description="\n".join(lines),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
