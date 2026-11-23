# -*- coding: utf-8 -*-
"""👑 도감 왕관용 종별 최대 치수(`fish.dexmax`) 소급 채우기 (2026-11-24).

왕관은 2026-11-24에 생겼어요. 그 전엔 **종별 최대 치수를 따로 적지 않았어요** — 어항(`tank`)은
팔면 비워지고, 남는 건 최고기록(`best`)과 주간 대회 최고어(`fishing_week.bestKey/bestSize`)뿐이에요.
그래서 그 셋에서 **확실히 잡아본 치수**만 모아 채워요. 팔아버린 큰 놈은 되살릴 수 없어요.

⭐ `$max`로 써요 → **여러 번 돌려도 안전**하고, 그사이 실제 낚시로 올라간 값을 깎지 않아요.
⚠️ 도감에 아직 없는 종(`dex.<key>`가 0)에 왕관만 생기면 이상해요 → 그 경우 `dex`도 최소 1로 채워요.

    python scripts/backfill_fish_crown.py          # 미리보기
    python scripts/backfill_fish_crown.py --send   # 실제 기록
"""
import os
import sys
from collections import defaultdict

# ⚠️ 윈도우 콘솔(cp949)은 👑을 못 찍어서 기록 전에 죽어요(2026-11-24에 실제로). UTF-8로 내보내요.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from utils.fish_data import BY_KEY, is_crown  # noqa: E402
from utils.fishing_store import _normalize_tank  # noqa: E402
from utils.pokemon_store import _db  # noqa: E402

SEND = "--send" in sys.argv
biggest: dict[str, dict[str, int]] = defaultdict(dict)


def note(uid: str, key: str | None, size) -> None:
    if key in BY_KEY and isinstance(size, (int, float)) and size > 0:
        biggest[uid][key] = max(biggest[uid].get(key, 0), int(size))


for d in _db["fish"].find({}, {"tank": 1, "best": 1}):
    uid = str(d["_id"])
    for key, sizes in _normalize_tank(d.get("tank") or {}).items():
        for s in sizes:
            note(uid, key, s)
    best = d.get("best") or {}
    note(uid, best.get("key"), best.get("size"))

for w in _db["fishing_week"].find({"bestKey": {"$exists": True}}, {"userId": 1, "bestKey": 1, "bestSize": 1}):
    note(str(w["userId"]), w.get("bestKey"), w.get("bestSize"))

crowns = {uid: [k for k, s in m.items() if is_crown(k, s)] for uid, m in biggest.items()}
print(f"{len(biggest)}명 · 종 최대치 {sum(len(v) for v in biggest.values())}건 · "
      f"왕관 {sum(len(v) for v in crowns.values())}개")
for uid, ks in sorted(crowns.items(), key=lambda kv: -len(kv[1])):
    if ks:
        print(f"  {uid[-4:]}  👑 {len(ks)}  {', '.join(f'{BY_KEY[k][1]} {biggest[uid][k]}cm' for k in sorted(ks))}")

if not SEND:
    print("\n미리보기만 했어요. 실제로 쓰려면 --send")
    sys.exit(0)

for uid, m in biggest.items():
    update = {f"dexmax.{k}": s for k, s in m.items()}
    update.update({f"dex.{k}": 1 for k in m})          # 도감에 없던 종이면 최소 1마리
    _db["fish"].update_one({"_id": uid}, {"$max": update})
print("\n✅ 기록했어요 ($max라 다시 돌려도 안전해요)")
