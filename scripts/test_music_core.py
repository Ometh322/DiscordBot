"""Живой тест без Discord: поиск SoundCloud -> свежая ссылка -> декод FFmpeg.

Запуск:
    venv\\Scripts\\python scripts\\test_music_core.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from services.soundcloud import SoundCloud, is_gachi


def main() -> None:
    sc = SoundCloud()

    tracks = sc.search("gachi", count=20)
    print(f"1) scsearch 'gachi': {len(tracks)} треков прошли фильтр GACHI/ГАЧИ")
    for t in tracks[:5]:
        print(f"   - {t.name}  [{t.duration} c]  id={t.full_id}")
    if not tracks:
        print("   Фильтр ничего не оставил — проверь сеть/доступ к SoundCloud.")
        sys.exit(1)
    assert all(is_gachi(t) for t in tracks), "фильтр пропустил не-GACHI трек"

    track = tracks[0]
    url = sc.fresh_url(track)
    host = url.split("/")[2]
    print(f"2) fresh_url: получил ссылку на поток (хост {host}, длина {len(url)})")

    result = subprocess.run(
        [
            config.FFMPEG_PATH,
            "-hide_banner",
            "-loglevel", "error",
            "-i", url,
            "-t", "3",          # декодируем 3 секунды
            "-f", "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(f"3) FFmpeg decode 3 c: exit={result.returncode}")
    if result.stderr.strip():
        print("   stderr:", result.stderr.strip()[:300])
    if result.returncode != 0:
        sys.exit(1)

    print("\nOK: поиск, фильтр, свежая ссылка и стрим-декод работают.")


if __name__ == "__main__":
    main()
