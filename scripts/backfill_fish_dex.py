# -*- coding: utf-8 -*-
"""📖 낚시 도감(`fish.dex`) 소급 채우기 (2026-11-22).

도감은 2026-11-22에 생겼어요. 그 전엔 **종별 누적 기록이 없었어요** — 어항(`tank`)은 팔면
비워지고, 남는 건 최고기록(`best`)과 주간 대회 최고어(`fishing_week.bestKey`)뿐이에요.
그래서 그 셋에서 **"잡아본 적 있다"는 확실한 증거만** 모아 채워요.

- 어항에 든 종: 그 마리 수
- 최고기록·주간 최고어 종: 최소 1마리

⭐ `$max`로 써요 → **여러 번 돌려도 안전**하고, 그사이 실제 낚시로 올라간 값을 깎지 않아요.

    python scripts/backfill_fish_dex.py          # 미리보기
    python scripts/backfill_fish_dex.py --send   # 실제 기록
"""
import os
import sys
from collections import defaultdict

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from utils.fish_data import BY_KEY  # noqa: E402
from utils.fishing_store import _normalize_tank  # noqa: E402
from utils.pokemon_store import _db  # noqa: E402

SEND = "--send" in sys.argv
evidence: dict[str, dict[str, int]] = defaultdict(dict)


def note(uid: str, key: str | None, n: int = 1) -> None:
    if key in BY_KEY and n > 0:
        evidence[uid][key] = max(evidence[uid].get(key, 0), n)


for d in _db["fish"].find({}, {"tank": 1, "best": 1}):
    uid = str(d["_id"])
    for key, sizes in _normalize_tank(d.get("tank") or {}).items():
        note(uid, key, len(sizes))
    note(uid, (d.get("best") or {}).get("key"))

for w in _db["fishing_week"].find({"bestKey": {"$exists": True}}, {"userId": 1, "bestKey": 1}):
    note(str(w["userId"]), w.get("bestKey"))

print(f"{len(evidence)}명 · 종 기록 {sum(len(v) for v in evidence.values())}건")
for uid, dex in sorted(evidence.items(), key=lambda kv: -len(kv[1])):
    print(f"  {uid[-4:]}  {len(dex):2d}종  {', '.join(BY_KEY[k][1] for k in sorted(dex))}")

if not SEND:
    print("\n미리보기만 했어요. 실제로 쓰려면 --send")
    sys.exit(0)

for uid, dex in evidence.items():
    _db["fish"].update_one({"_id": uid}, {"$max": {f"dex.{k}": n for k, n in dex.items()}})
print("\n✅ 기록했어요 ($max라 다시 돌려도 안전해요)")
