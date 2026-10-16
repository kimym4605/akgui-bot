"""🎴 카드 뽑기 검증. 실제 DB 없이 돌아가요.

2026-10-17에 만들었어요. 뽑기는 **배포하고 나면 확률을 되돌릴 수 없어요** - 누가 이미
레전드를 받아버린 뒤에 "확률이 10배였네"를 고치면 그 사람 카드를 빼앗아야 하니까요.
그래서 숫자가 의도대로 나오는지 미리 전부 재봐요.

여기서 확인하는 것:
  1) 등급 분포가 GRADE_WEIGHTS와 맞는다 (10만 장 시뮬레이션)
  2) 천장: 레전드 없이 30장을 지나면 그 다음 장은 **레전드 확정**이다
  3) 천장은 레전드를 받으면 0으로 리셋된다
  4) 에픽·레전드는 **같은 카드가 두 번 안 나온다** (한 뽑기 안에서도)
  5) 일반·레어는 중복이 나온다 (장수로 세는 등급)
  6) 그 등급을 다 모으면 그 등급은 안 뽑히고 다른 등급으로 재굴림된다
  7) 에픽·레전드를 전부 모아도 뽑기가 **종료된다** (무한루프 없음)
  8) 레전드 완주자에게는 천장이 발동하지 않는다 (줄 카드가 없으니까)
  9) 동시에 두 번 들어오면 낙관적 동시성이 잡고 재시도해서 둘 다 반영된다
 10) 레지스트리의 모든 카드에 실제 이미지 파일이 있다 (없으면 뽑고 나서 터져요)
 11) 도감 요약(summarize)이 등급별 보유/전체를 맞게 센다
"""
import os
import sys
from collections import Counter
from pathlib import Path
from random import Random

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_card_test"

from utils import card_store  # noqa: E402
from utils.card_data import BY_KEY, CARDS, TOTAL  # noqa: E402
from utils.card_store import (  # noqa: E402
    CARDS_PER_PULL,
    GRADE_WEIGHTS,
    PITY_DRAWS,
    PULL_PRICE,
    draw_cards,
)

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def all_keys(grade):
    return [c["key"] for c in CARDS[grade]]


# ==================================================================
print("\n[1] 등급 분포가 설정과 맞는가 (10만 장)")
# ------------------------------------------------------------------
# ⚠️ counts를 매번 비워서 뽑아요. 누적하면 에픽·레전드가 고갈돼서 분포가 일부러 틀어져요
#    (그 동작은 [6]에서 따로 확인해요).
rng = Random(20261017)
N = 100_000
dist = Counter()
for _ in range(N):
    drawn, _ = draw_cards({}, 0, n=1, rng=rng)
    dist[drawn[0]["grade"]] += 1

total_w = sum(GRADE_WEIGHTS.values())

# 🚨 합이 100이어야 **적은 가중치가 곧 퍼센트**예요. random.choices가 알아서 정규화해서
#    합이 96.5여도 조용히 돌아가는데, 그러면 "에픽 5"라고 적어두고 실제로는 5.18%가 나가요
#    (`/카드확률`이 공개하는 값과 어긋나요 - 뽑기에서 이건 분쟁거리예요).
check("가중치 합이 정확히 100", abs(total_w - 100) < 1e-9, f"합={total_w}")

for grade, weight in GRADE_WEIGHTS.items():
    expected = weight / total_w * 100
    actual = dist[grade] / N * 100
    # 0.5%짜리도 10만 장이면 표준오차가 0.02%p라 0.3%p 여유는 충분히 넉넉해요.
    check(
        f"{grade} {expected:.1f}% 기대",
        abs(actual - expected) < 0.3,
        f"실측 {actual:.2f}%",
    )

# ==================================================================
print("\n[2][3] 천장이 30장에서 발동하고 레전드를 받으면 리셋되는가")
# ------------------------------------------------------------------
# 레전드가 절대 안 나오는 상태를 만들려고 since_legend를 직접 올려요.
drawn, since = draw_cards({}, PITY_DRAWS - 2, n=1, rng=Random(1))
check(f"{PITY_DRAWS - 1}장째는 아직 확정이 아니다", not drawn[0]["pity"])

drawn, since = draw_cards({}, PITY_DRAWS - 1, n=1, rng=Random(1))
check(f"{PITY_DRAWS}장째에 레전드 확정", drawn[0]["grade"] == "레전드" and drawn[0]["pity"])
check("레전드를 받으면 카운터가 0으로", since == 0, f"since={since}")

# 운으로 먼저 레전드가 나와도 리셋돼야 해요.
drawn, since = draw_cards({}, 10, n=1, rng=Random(1))
if drawn[0]["grade"] == "레전드":
    check("운으로 나온 레전드도 리셋", since == 0)
else:
    check("레전드가 아니면 카운터 +1", since == 11, f"since={since}")

# 천장이 실제로 간격을 제한하는지 - 긴 구간을 돌려 최대 간격을 재요.
#
# ⚠️ 레전드 13종을 **다 모은 뒤**로는 천장이 발동하지 않아요(줄 카드가 없으니까 - 의도된
#    동작이고 card_store 모듈 주석에 적혀 있어요). 그래서 완주 전까지만 재야 해요.
#    처음엔 5,000장을 그냥 돌렸다가 "최장 4697장"이 나와서 실패했는데, 그건 버그가 아니라
#    완주 이후 구간까지 같이 센 거였어요.
legend_keys = all_keys("레전드")
rng = Random(7)
since, worst, counts = 0, 0, {}
for _ in range(5_000):
    if all(counts.get(k) for k in legend_keys):
        break   # 레전드 완주 - 여기부터는 천장이 적용되지 않아요
    drawn, since = draw_cards(counts, since, n=1, rng=rng)
    for d in drawn:
        counts[d["key"]] = counts.get(d["key"], 0) + 1
    worst = max(worst, since)
check(
    f"레전드 완주 전까지 레전드 없는 최장 구간이 {PITY_DRAWS}장을 안 넘는다",
    worst < PITY_DRAWS,
    f"최장 {worst}장",
)

# 완주 뒤에는 카운터가 그냥 쌓이기만 해요 (문서화된 동작이라 같이 못 박아둬요).
after = draw_cards({k: 1 for k in legend_keys}, PITY_DRAWS * 3, n=1, rng=Random(8))
check("레전드 완주 뒤에는 천장이 쌓여도 발동하지 않는다", not after[0][0]["pity"])

# ==================================================================
print("\n[4][5] 중복 규칙이 등급마다 다른가")
# ------------------------------------------------------------------
# 에픽·레전드: 한 뽑기(3장) 안에서도 같은 카드가 안 나와야 해요.
rng = Random(99)
dupe_in_pull = False
for _ in range(20_000):
    drawn, _ = draw_cards({}, 0, n=CARDS_PER_PULL, rng=rng)
    keys = [d["key"] for d in drawn if d["grade"] not in card_store.DUPE_OK]
    if len(keys) != len(set(keys)):
        dupe_in_pull = True
        break
check("한 뽑기 안에서 에픽·레전드 중복 없음", not dupe_in_pull)

# 긴 수집에서도 에픽·레전드는 장수가 1을 안 넘어요.
rng = Random(5)
counts, since = {}, 0
for _ in range(3_000):
    drawn, since = draw_cards(counts, since, n=1, rng=rng)
    for d in drawn:
        counts[d["key"]] = counts.get(d["key"], 0) + 1
over = {k: v for k, v in counts.items() if BY_KEY[k][0] not in card_store.DUPE_OK and v > 1}
check("에픽·레전드는 2장 이상 쌓이지 않는다", not over, str(over)[:60])

dupes = [v for k, v in counts.items() if BY_KEY[k][0] in card_store.DUPE_OK and v > 1]
check("일반·레어는 중복이 쌓인다", bool(dupes), f"중복 카드 {len(dupes)}종")

# ==================================================================
print("\n[6][7][8] 등급을 다 모았을 때")
# ------------------------------------------------------------------
# 에픽만 전부 보유 -> 에픽은 더 안 나와야 해요.
epic_full = {k: 1 for k in all_keys("에픽")}
rng = Random(3)
got = Counter()
for _ in range(3_000):
    drawn, _ = draw_cards(epic_full, 0, n=1, rng=rng)
    got[drawn[0]["grade"]] += 1
check("에픽 완주자에게 에픽이 안 나온다", got["에픽"] == 0, f"에픽 {got['에픽']}회")
check("대신 다른 등급으로 재굴림된다", sum(got.values()) == 3_000)

# 에픽+레전드 전부 보유 -> 종료되어야 해요 (일반·레어만 남음).
both_full = {k: 1 for k in all_keys("에픽") + all_keys("레전드")}
drawn, _ = draw_cards(both_full, 0, n=CARDS_PER_PULL, rng=Random(11))
check(
    "에픽·레전드 완주자도 3장을 받는다",
    len(drawn) == CARDS_PER_PULL,
    f"{len(drawn)}장",
)
check(
    "그 3장은 전부 일반·레어다",
    all(d["grade"] in card_store.DUPE_OK for d in drawn),
    str([d["grade"] for d in drawn]),
)

# 레전드 완주자에게는 천장이 발동하지 않아요 (줄 카드가 없어요).
legend_full = {k: 1 for k in all_keys("레전드")}
drawn, since = draw_cards(legend_full, PITY_DRAWS + 5, n=1, rng=Random(13))
check("레전드 완주자에게 천장이 발동하지 않는다", not drawn[0]["pity"])
check("그래도 카드는 나온다", drawn[0]["grade"] != "레전드")

# 83장 전부 보유 (일반·레어도 1장씩) -> 중복 허용 등급이 있으니 여전히 뽑혀요.
everything = {k: 1 for k in BY_KEY}
drawn, _ = draw_cards(everything, 0, n=CARDS_PER_PULL, rng=Random(17))
check("도감 완성자도 뽑기가 종료된다 (무한루프 없음)", len(drawn) == CARDS_PER_PULL)

# ==================================================================
print("\n[9] 동시에 두 번 뽑으면 둘 다 반영되는가 (낙관적 동시성)")
# ------------------------------------------------------------------
class FakeCards:
    """_id 하나짜리 가짜 컬렉션. $inc/$set/upsert와 draws 필터 일치를 흉내내요."""

    def __init__(self):
        self.doc = None
        self.writes = 0
        self.rejected = 0
        # 첫 update_one 직전에 끼어들 콜백 (동시 실행 재현용)
        self.before_update = None

    def find_one(self, flt, projection=None):
        if self.doc is None:
            return None
        return dict(self.doc)

    def _matches(self, flt):
        doc = self.doc or {}
        for key, want in flt.items():
            if key == "_id":
                if doc.get("_id") != want:
                    return False
            elif key == "$or":
                if not any(self._matches(cond) for cond in want):
                    return False
            elif isinstance(want, dict) and "$exists" in want:
                if (key in doc) != want["$exists"]:
                    return False
            elif doc.get(key) != want:
                return False
        return True

    def update_one(self, flt, update, upsert=False):
        if self.before_update is not None:
            cb, self.before_update = self.before_update, None
            cb()

        class Res:
            def __init__(self, modified=0, upserted=None):
                self.modified_count = modified
                self.upserted_id = upserted

        exists = self.doc is not None
        if exists and not self._matches(flt):
            self.rejected += 1
            return Res()
        if not exists:
            if not upsert:
                return Res()
            self.doc = {"_id": flt["_id"]}

        for field, delta in (update.get("$inc") or {}).items():
            if "." in field:
                parent, child = field.split(".", 1)
                self.doc.setdefault(parent, {})
                self.doc[parent][child] = self.doc[parent].get(child, 0) + delta
            else:
                self.doc[field] = self.doc.get(field, 0) + delta
        for field, value in (update.get("$set") or {}).items():
            self.doc[field] = value

        self.writes += 1
        return Res(modified=1 if exists else 0, upserted=None if exists else flt["_id"])


fake = FakeCards()
card_store._cards = fake

first = card_store._pull_sync("u1")
check("첫 뽑기 성공", first is not None and len(first) == CARDS_PER_PULL)
check("draws가 3으로 기록", fake.doc.get("draws") == 3, f"draws={fake.doc.get('draws')}")

# 두 번째 뽑기가 계산을 끝낸 직후, 다른 뽑기가 먼저 써버리는 상황을 만들어요.
def interleave():
    fake.doc["draws"] += 3   # 남이 먼저 3장 뽑아감

fake.before_update = interleave
second = card_store._pull_sync("u1")
check("끼어들기가 있어도 재시도로 성공한다", second is not None and len(second) == CARDS_PER_PULL)
check("낡은 draws로 쓰려던 시도는 거절됐다", fake.rejected >= 1, f"거절 {fake.rejected}회")

owned_cards = sum((fake.doc.get("counts") or {}).values())
check(
    "끼어든 3장까지 합쳐 draws가 9",
    fake.doc.get("draws") == 9,
    f"draws={fake.doc.get('draws')} counts합={owned_cards}",
)

# ==================================================================
print("\n[10] 레지스트리의 모든 카드에 이미지 파일이 있는가")
# ------------------------------------------------------------------
img_dir = Path(BOT_DIR) / "assets" / "cards"
missing = [c["file"] for cards in CARDS.values() for c in cards
           if not (img_dir / c["file"]).is_file()]
check(f"{TOTAL}장 전부 이미지 존재", not missing, f"없음: {missing[:5]}")

webps = list(img_dir.glob("*.webp"))
check("남는 유령 이미지가 없다", len(webps) == TOTAL, f"파일 {len(webps)}개 vs 레지스트리 {TOTAL}장")

big = [p.name for p in webps if p.stat().st_size > 400_000]
# 256MB 머신이라 장당 수 MB짜리가 섞여 있으면 뽑기 때 메모리가 튀어요.
check("장당 400KB 이하", not big, f"큰 파일: {big[:5]}")

total_mb = sum(p.stat().st_size for p in webps) / 1024 / 1024
check("전체 20MB 이하", total_mb < 20, f"{total_mb:.1f}MB")

# ==================================================================
print("\n[11] 도감 요약이 맞는가")
# ------------------------------------------------------------------
s = card_store.summarize({})
check("빈 도감은 0/83", s["owned"] == 0 and s["total"] == TOTAL)

partial = {k: 1 for k in all_keys("레전드")[:5]}
partial[all_keys("일반")[0]] = 4      # 같은 일반 4장
s = card_store.summarize(partial)
check("보유 종류 수", s["owned"] == 6, f"owned={s['owned']}")
check("중복 포함 장수", s["cards"] == 9, f"cards={s['cards']}")
check("등급별 레전드 5/13", s["per_grade"]["레전드"] == {"owned": 5, "total": 13})
check("등급별 에픽 0/30", s["per_grade"]["에픽"] == {"owned": 0, "total": 30})

s = card_store.summarize({k: 1 for k in BY_KEY})
check("전부 모으면 83/83", s["owned"] == TOTAL and s["total"] == TOTAL)

# ==================================================================
print("\n[참고] 경제 시뮬레이션 (확정된 수치로 실제 기대값)")
# ------------------------------------------------------------------
# 사용자가 고른 수치: 10코인에 3장, 천장 30장.
rng = Random(2026)
TRIALS = 200
to_first_legend, to_epic_done, to_legend_done = [], [], []
for _ in range(TRIALS):
    counts, since, pulls = {}, 0, 0
    first_legend = epic_done = legend_done = None
    while legend_done is None and pulls < 4_000:
        drawn, since = draw_cards(counts, since, n=CARDS_PER_PULL, rng=rng)
        pulls += 1
        for d in drawn:
            counts[d["key"]] = counts.get(d["key"], 0) + 1
            if d["grade"] == "레전드" and first_legend is None:
                first_legend = pulls
        if epic_done is None and all(counts.get(k) for k in all_keys("에픽")):
            epic_done = pulls
        if all(counts.get(k) for k in all_keys("레전드")):
            legend_done = pulls
    to_first_legend.append(first_legend or pulls)
    to_epic_done.append(epic_done or pulls)
    to_legend_done.append(legend_done or pulls)


def avg(xs):
    return sum(xs) / len(xs)


print(f"  1뽑기 = {PULL_PRICE}코인 / {CARDS_PER_PULL}장 (장당 {PULL_PRICE/CARDS_PER_PULL:.2f}코인)")
print(f"  첫 레전드까지      평균 {avg(to_first_legend):6.1f}뽑기 = {avg(to_first_legend)*PULL_PRICE:7.0f}코인"
      f"  (최악 {max(to_first_legend)}뽑기)")
print(f"  에픽 30종 완주     평균 {avg(to_epic_done):6.1f}뽑기 = {avg(to_epic_done)*PULL_PRICE:7.0f}코인")
print(f"  레전드 13종 완주   평균 {avg(to_legend_done):6.1f}뽑기 = {avg(to_legend_done)*PULL_PRICE:7.0f}코인")
# 천장이 PITY_DRAWS장째를 보장하니, 최악은 그 장이 들어있는 뽑기까지예요.
worst_pulls = -(-PITY_DRAWS // CARDS_PER_PULL)   # 올림 나눗셈
check(
    f"첫 레전드가 천장 안에 보장된다 (최악 {worst_pulls}뽑기 = {worst_pulls*PULL_PRICE}코인)",
    max(to_first_legend) <= worst_pulls,
    f"최악 {max(to_first_legend)}뽑기 = {max(to_first_legend)*PULL_PRICE}코인",
)

# ==================================================================
print("\n" + "=" * 60)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
