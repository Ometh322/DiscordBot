"""Очередь воспроизведения на гильдию и пайплайн FFmpeg.

Поток: очередь треков (только id) -> свежая mp3-ссылка через audio.getById
-> FFmpegPCMAudio (стрим по https) -> Discord.
"""

import asyncio
import logging
import time
from collections import deque
from typing import List, Optional

import discord

import config
from services.gifs import attach_random_gif
from services.soundcloud import SoundCloud, SoundCloudError, Track

log = logging.getLogger(__name__)

# Переподключение к CDN при обрыве стрима (флаги идут до -i)
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
IDLE_DISCONNECT_SECONDS = 5 * 60


def fmt_duration(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


class GuildPlayer:
    """Состояние плеера одной гильдии: очередь, текущий трек, автовыход."""

    def __init__(self, bot: discord.Client, guild: discord.Guild, sc: SoundCloud):
        self.bot = bot
        self.guild = guild
        self.sc = sc
        self.queue: List[Track] = []
        self.current: Optional[Track] = None
        self.played: deque = deque(maxlen=100)  # история для кнопки «назад»
        self.text_channel: Optional[discord.abc.Messageable] = None
        self._idle_task: Optional[asyncio.Task] = None
        self._suppress_next = False  # приветствие останавливает трек без смены очереди
        # учёт позиции текущего трека для возобновления после приветствия
        self._track_started: Optional[float] = None  # monotonic
        self._paused_total: float = 0.0
        self._pause_started: Optional[float] = None
        self._resume_offset: float = 0.0  # секунды для следующего запуска потока

    @property
    def voice(self) -> Optional[discord.VoiceClient]:
        return self.guild.voice_client

    # ---- публичное API (вызывается из cog'а) ----

    async def enqueue(self, track: Track, announce_start: bool = False) -> int:
        """Добавить трек. Возвращает позицию: 1 = играет сейчас."""
        self.queue.append(track)
        if not self.current and not (self.voice and self.voice.is_playing()):
            await self.play_next(announce=announce_start)
            return 1
        return len(self.queue)

    async def skip(self) -> bool:
        """Пропустить текущий трек. True — если что-то играло."""
        vc = self.voice
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # after-callback сам запустит следующий трек
            return True
        await self.play_next()
        return False

    async def prev(self) -> bool:
        """Вернуть предыдущий трек (текущий встанет после него)."""
        if not self.played:
            return False
        prev_track = self.played.pop()
        if self.current is not None:
            self.queue.insert(0, self.current)
        self.queue.insert(0, prev_track)
        vc = self.voice
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # after-callback сам запустит предыдущий трек
        else:
            await self.play_next(announce=True)
        return True

    def pause_for_greeting(self) -> bool:
        """Останавливает текущий трек для приветствия, НЕ двигая очередь и
        запоминая позицию. True — если музыка играла (после приветствия
        вызвать resume_after_greeting)."""
        vc = self.voice
        if not (vc and (vc.is_playing() or vc.is_paused())):
            return False
        now = time.monotonic()
        if self._pause_started is not None:  # стоял на паузе кнопкой
            self._paused_total += now - self._pause_started
            self._pause_started = None
        if self._track_started is not None:
            self._resume_offset = max(
                0.0, now - self._track_started - self._paused_total
            )
        self._suppress_next = True
        vc.stop()
        return True

    async def resume_after_greeting(self) -> None:
        """Возвращает трек, прерванный приветствием, — с прежней позиции."""
        if self.current is None:
            await self.play_next()  # прерывать было нечего — просто очередь
            return
        track, self.current = self.current, None
        self.queue.insert(0, track)
        await self.play_next(announce=False)

    def pause_music(self) -> None:
        """Пауза с учётом времени (для возобновления по позиции)."""
        vc = self.voice
        if vc and vc.is_playing() and self._pause_started is None:
            vc.pause()
            self._pause_started = time.monotonic()

    def resume_music(self) -> None:
        vc = self.voice
        if vc and vc.is_paused():
            vc.resume()
            if self._pause_started is not None:
                self._paused_total += time.monotonic() - self._pause_started
                self._pause_started = None

    def stop(self) -> int:
        """Остановить воспроизведение и очистить очередь. Возвращает размер очереди."""
        cleared = len(self.queue)
        self.queue.clear()
        self.current = None
        self._cancel_idle()
        vc = self.voice
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        return cleared

    async def disconnect(self) -> None:
        self.queue.clear()
        self.current = None
        self._cancel_idle()
        vc = self.voice
        if vc:
            await vc.disconnect(force=True)

    # ---- внутреннее ----

    async def play_next(self, announce: bool = True) -> None:
        """Берёт следующий трек из очереди и запускает. announce=False — первый
        трек, запущенный командой, которая сама отвечает пользователю."""
        self._cancel_idle()

        if self.current is not None:  # сыгравшее — в историю для «назад»
            self.played.append(self.current)

        while self.queue:
            vc = self.voice
            if vc is None:
                self.queue.clear()
                self.current = None
                return

            track = self.queue.pop(0)
            offset, self._resume_offset = self._resume_offset, 0.0
            before = FFMPEG_BEFORE_OPTIONS
            if offset > 0.5:  # возобновление после приветствия — с позиции
                before = f"-ss {offset:.1f} " + FFMPEG_BEFORE_OPTIONS
            try:
                url = await asyncio.to_thread(self.sc.fresh_url, track)
                source = discord.FFmpegPCMAudio(
                    url,
                    executable=config.FFMPEG_PATH,
                    before_options=before,
                )
            except TrackUnavailable as e:
                await self._notify(f"⚠️ Пропускаю: {e}")
                continue
            except SoundCloudError as e:
                await self._notify(f"⚠️ SoundCloud недоступен, пропускаю трек: {e}")
                continue
            except Exception:
                log.exception("Ошибка подготовки трека %s", track.full_id)
                await self._notify("⚠️ Неожиданная ошибка, пропускаю трек.")
                continue

            self.current = track

            def _after(error):
                if error:
                    log.error("Ошибка воспроизведения: %s", error)
                if self._suppress_next:
                    # трек остановлен приветствием — очередь не двигаем
                    self._suppress_next = False
                    return
                # after() вызывается из потока аудио — переносим в цикл бота
                asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

            try:
                vc.play(source, after=_after)
            except discord.ClientException:
                log.exception("VoiceClient.play(%s)", track.full_id)
                self.current = None
                continue

            # трек стартовал — начинаем учёт позиции
            self._track_started = time.monotonic()
            self._paused_total = 0.0
            self._pause_started = None

            if announce:
                await self._now_playing()
            return

        # Очередь кончилась
        self.current = None
        self._start_idle()

    # ---- сообщения ----

    async def _notify(self, text: str) -> None:
        if not self.text_channel:
            return
        try:
            await self.text_channel.send(text)
        except discord.HTTPException:
            log.exception("Не удалось отправить сообщение")

    async def _now_playing(self) -> None:
        t = self.current
        if not t:
            return
        embed = discord.Embed(title="▶ Сейчас играет", description=f"**{t.title}**")
        embed.add_field(name="Исполнитель", value=t.artist or "—")
        embed.set_footer(text=f"Длительность: {fmt_duration(t.duration)}")
        embed.url = t.page_url
        gif = attach_random_gif(embed)
        try:
            await self.text_channel.send(
                embed=embed, file=gif, view=PlayerControls(self)
            )
        except (discord.HTTPException, AttributeError):
            log.exception("Не удалось отправить 'Сейчас играет'")

    # ---- автовыход ----

    def _start_idle(self):
        self._cancel_idle()
        if self.voice:
            self._idle_task = self.bot.loop.create_task(self._idle_disconnect())

    def _cancel_idle(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None

    async def _idle_disconnect(self) -> None:
        try:
            await asyncio.sleep(IDLE_DISCONNECT_SECONDS)
        except asyncio.CancelledError:
            return
        vc = self.voice
        if vc and not self.queue and not (vc.is_playing() or vc.is_paused()):
            await vc.disconnect(force=True)
            log.info("Автовыход из канала %s (гильдия %s): 5 минут простоя",
                     vc.channel, self.guild)


class PlayerControls(discord.ui.View):
    """Кнопки управления под сообщением «Сейчас играет»: ⏮ ⏸ ⏹ ⏭.

    Доступны всем, кто находится в голосовом канале вместе с ботом."""

    def __init__(self, player: GuildPlayer):
        super().__init__(timeout=None)
        self.player = player

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user_v = interaction.user.voice
        bot_v = self.player.voice
        if not user_v or not user_v.channel:
            await interaction.response.send_message(
                "Зайди в голосовой канал, чтобы управлять плеером 🎧", ephemeral=True
            )
            return False
        if bot_v and user_v.channel != bot_v.channel:
            await interaction.response.send_message(
                f"Ты в другом канале — плеер управляется из {bot_v.channel.mention}",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        if await self.player.prev():
            await interaction.response.defer()
        else:
            await interaction.response.send_message(
                "Предыдущего трека нет.", ephemeral=True
            )

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.primary)
    async def pause_button(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        vc = self.player.voice
        if not vc or not (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message(
                "Сейчас ничего не играет.", ephemeral=True
            )
            return
        if vc.is_paused():
            self.player.resume_music()
            button.emoji = "⏸️"
        else:
            self.player.pause_music()
            button.emoji = "▶️"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        if await self.player.skip():
            await interaction.response.defer()
        else:
            await interaction.response.send_message(
                "Нечего пропускать.", ephemeral=True
            )

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        self.player.stop()
        await interaction.response.edit_message(view=None)


class PlayerManager:
    def __init__(self, bot: discord.Client, sc: SoundCloud):
        self.bot = bot
        self.sc = sc
        self._players = {}

    def get(self, guild: discord.Guild) -> GuildPlayer:
        player = self._players.get(guild.id)
        if player is None:
            player = GuildPlayer(self.bot, guild, self.sc)
            self._players[guild.id] = player
        return player
