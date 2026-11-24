import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from services.catalog import Catalog
from services.soundcloud import SEARCH_QUERIES, Track, is_gachi

# префиксы id
sc = Track(track_id="123456", title="SC трек", source="sc")
yt = Track(track_id="dQw4w9WgXcQ", title="YT Гачи (Right Version)", source="yt")
assert sc.full_id == "123456", "sc остаётся без префикса (совместимость с базой)"
assert yt.full_id == "yt:dQw4w9WgXcQ"
assert is_gachi(yt)
print("full_id:", sc.full_id, "/", yt.full_id, "— OK")

# каталог: оба источника в одной базе, чарт сходится
tmp = Path(tempfile.gettempdir()) / "gachi_test_cat3.sqlite"
for s in ("", "-wal", "-shm"):
    Path(str(tmp) + s).unlink(missing_ok=True)
cat = Catalog(tmp)
cat.upsert([sc, yt], "ang")
row = cat._run(lambda con: con.execute(
    "SELECT track_id, page_url FROM tracks WHERE track_id='yt:dQw4w9WgXcQ'"
).fetchone())
assert row and row[1] == yt.page_url
cat.approvals_add(1, yt.full_id, 100)
chart = cat.top_tracks(1)
assert chart and chart[0][0] == yt.title, chart
cat.mark_played(1, [yt])
recent = cat.recent_ids(1)
assert yt.full_id in recent
picked = cat.pick("ang", 5, 1)
assert all(t.full_id != yt.full_id for t in picked)
print("каталог: yt-трек хранится, чарт сходится, повтор исключён — OK")
for s in ("", "-wal", "-shm"):
    Path(str(tmp) + s).unlink(missing_ok=True)

print("пулы:", len(SEARCH_QUERIES["ru"]), "ru /", len(SEARCH_QUERIES["ang"]), "ang запросов")
