"""Устойчивость к «протухшим» interaction'ам.

При нестабильном канале до Discord (DPI-обход вроде zapret, ломкие сети)
ответ на слэш-команду может опоздать дольше 3 секунд — Discord отвечает
404 Unknown interaction (10062). Такая ошибка не должна ронять выполнение
команды: музыка должна заиграть, даже если красивый ответ не ушёл.
"""

import logging

import discord

log = logging.getLogger(__name__)


async def safe_defer(interaction: discord.Interaction, **kwargs) -> bool:
    """defer() без падения на NotFound/HTTPException. False — ответ не ушёл."""
    try:
        await interaction.response.defer(**kwargs)
        return True
    except (discord.NotFound, discord.HTTPException) as e:
        lag = (discord.utils.utcnow() - interaction.created_at).total_seconds()
        log.warning(
            "defer не прошёл (%s); возраст interaction: %.1f с — канал до "
            "Discord медленный/ломкий", e, lag,
        )
        return False


async def safe_followup(interaction: discord.Interaction, *args, **kwargs) -> None:
    """followup.send() без падения — команда продолжает работать молча."""
    try:
        await interaction.followup.send(*args, **kwargs)
    except (discord.NotFound, discord.HTTPException) as e:
        log.warning("followup не прошёл: %s", e)
