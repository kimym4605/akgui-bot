"""업적 해금 상태와 판정 - "지금 이 사람이 뭘 얼마나 했는지"를 한 번에 모아와서,
`utils/achievement_data.py`의 60개와 대조하고, 새로 열린 걸 저장하고 코인을 줘요.

## 판정 데이터를 한 번에 긁는 이유

업적 60개가 보는 숫자는 사실 12개뿐이에요(출석·연속출석·코인·도감·레벨·내전 승/판/연승·
악귀력·티어·미션·기타 플래그). 그래서 업적마다 DB를 부르지 않고 `collect_stats()`가
**한 번의 to_thread 안에서 컬렉션을 훑어 12개를 채운 뒤**, 판정은 메모리에서 비교만 해요.
`/프로필`과 `/업적`이 자주 불릴 자리라 왕복 수가 그대로 체감 속도가 돼요.

## 언제 판정하나

`/프로필`, `/업적`을 볼 때와 내전 결과가 기록된 직후예요. **따로 주기적으로 돌지 않아요.**
업적은 전부 "누적값이 기준을 넘었나"라서 늦게 판정해도 결과가 달라지지 않고, 안 보는
사람 몫까지 30분마다 도는 건 256MB 머신에 낭비예요.

## 보상 지급의 원자성

같은 순간에 `/프로필`과 `/업적`을 동시에 누르면 같은 업적이 두 번 열려서 코인이 두 배로
나갈 수 있어요. 그래서 해금 기록은 `$addToSet` + 필터 `$ne`로 **그 update가 실제로 문서를
바꿨을 때만** 코인을 줘요(미션 완료 처리와 같은 방식이에요).
"""
import asyncio
import logging
from datetime import datetime, timezone

from utils import achievement_data, coin_wallet
from utils.pokemon_store import _db, _trainers

log = logging.getLogger(__name__)

_unlocks = _db["achievements"]
_guest = _db["attendance_guest"]
_missions = _db["missions"]
_titles = _db["titles"]
_coin_log = _db["coin_log"]
_scrim = _db["scrim_records"]
_weekly = _db["agwi_weekly"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# 판정에 쓸 숫자 모으기
# ------------------------------------------------------------------
def _collect_sync(user_id, tier_index: int | None, riot_linked: bool, birthday_set: bool) -> dict:
    """업적 60개가 보는 숫자 전부를 한 번에 모아요.

    tier_index/riot_linked/birthday_set은 DB가 아니라 디스코드 역할·파일에서 오는 값이라
    호출하는 쪽에서 미리 구해 넘겨줘요(여기서 discord를 import하지 않으려고요)."""
    uid = str(user_id)

    stats = {
        "attendance": 0, "attendance_streak": 0, "coin": 0,
        "pokedex": 0, "level": 0, "pokemon_started": 0,
        "scrim_wins": 0, "scrim_losses": 0, "scrim_matches": 0, "scrim_best_streak": 0,
        "agwi_best": 0, "tier_index": tier_index or 0,
        "mission_total": 0, "title_owned": 0,
        "riot_linked": 1 if riot_linked else 0,
        "birthday_set": 1 if birthday_set else 0,
    }

    # --- 포켓몬 트레이너 (없으면 게스트 출석 기록에서 출석만 가져와요) ---
    trainer = _trainers.find_one(
        {"_id": uid},
        {"attendance": 1, "attendanceStreak": 1, "coin": 1, "pokedex": 1,
         "level": 1, "starterChosen": 1, "basePokemon": 1},
    )
    if trainer:
        stats["attendance"] = int(trainer.get("attendance", 0) or 0)
        stats["attendance_streak"] = int(trainer.get("attendanceStreak", 0) or 0)
        stats["coin"] = int(trainer.get("coin", 0) or 0)
        stats["pokedex"] = len(trainer.get("pokedex", []) or [])
        stats["level"] = int(trainer.get("level", 0) or 0)
        stats["pokemon_started"] = 1
    else:
        guest = _guest.find_one({"_id": uid}, {"attendance": 1, "attendanceStreak": 1})
        if guest:
            stats["attendance"] = int(guest.get("attendance", 0) or 0)
            stats["attendance_streak"] = int(guest.get("attendanceStreak", 0) or 0)
        wallet = _db["coin_reset_backup"].find_one({"_id": uid}, {"coin": 1})
        if wallet:
            stats["coin"] = int(wallet.get("coin", 0) or 0)

    # --- 내전 (통산) ---
    record = _scrim.find_one({"_id": f"all:{uid}"})
    if record:
        stats["scrim_wins"] = int(record.get("wins", 0) or 0)
        stats["scrim_losses"] = int(record.get("losses", 0) or 0)
        stats["scrim_matches"] = stats["scrim_wins"] + stats["scrim_losses"]
        stats["scrim_best_streak"] = int(record.get("bestStreak", 0) or 0)

    # --- 역대 최고 주간 악귀력 ---
    best = list(_weekly.find({"userId": uid}, {"score": 1}).sort([("score", -1)]).limit(1))
    if best:
        stats["agwi_best"] = int(best[0].get("score", 0) or 0)

    # --- 누적 미션 ---
    mission_doc = _missions.find_one({"_id": uid}, {"totalDone": 1})
    if mission_doc:
        stats["mission_total"] = int(mission_doc.get("totalDone", 0) or 0)

    # --- 칭호: 지금 달고 있거나, 예전에 사본 적 있으면 인정 ---
    #
    # 칭호는 기간이 끝나면 문서가 지워져서(title_store._delete_sync) 현재 보유만 보면
    # "한 달 달았다가 만료된 사람"이 업적을 잃어버려요. 구매 기록은 코인 로그에 영구히
    # 남으니까 그걸 같이 봐요.
    if _titles.find_one({"_id": uid}, {"_id": 1}):
        stats["title_owned"] = 1
    elif _coin_log.find_one({"from": uid, "note": "칭호구매"}, {"_id": 1}):
        stats["title_owned"] = 1

    return stats


def _unlocked_sync(user_id) -> dict:
    doc = _unlocks.find_one({"_id": str(user_id)})
    return (doc or {}).get("unlocked", {}) or {}


def _try_unlock_sync(user_id, key: str) -> bool:
    """이번 호출로 **처음** 열렸으면 True. 이미 열려 있었으면 False(코인 중복 지급 방지).

    ⚠️ 이걸 "조건부 필터 + upsert=True" 한 방으로 쓰면 안 돼요. 이미 열린 업적은 필터
    (`$exists: False`)에 안 걸리는데, 그때 upsert가 같은 _id로 새 문서를 만들려다
    DuplicateKeyError를 던져요. 그러면 `/프로필`을 두 번 누른 것만으로 판정이 통째로
    터져요. 그래서 '문서 보장'과 '해금 표시'를 나눠서 해요."""
    uid = str(user_id)

    # 1) 문서가 없으면 빈 문서를 만들어둬요. 필터가 _id 하나뿐이라 upsert가 안전해요
    #    (이미 있으면 $setOnInsert가 아무것도 안 바꿔요).
    _unlocks.update_one({"_id": uid}, {"$setOnInsert": {"unlocked": {}}}, upsert=True)

    # 2) 아직 안 열린 업적일 때만 시각을 찍어요. modified_count가 1이면 이번 호출이 최초예요.
    result = _unlocks.update_one(
        {"_id": uid, f"unlocked.{key}": {"$exists": False}},
        {"$set": {f"unlocked.{key}": _now_iso()}},
    )
    return result.modified_count == 1


# ------------------------------------------------------------------
# 공개 API (전부 async)
# ------------------------------------------------------------------
async def collect_stats(user_id, *, tier_index=None, riot_linked=False, birthday_set=False) -> dict:
    return await asyncio.to_thread(_collect_sync, user_id, tier_index, riot_linked, birthday_set)


async def unlocked_keys(user_id) -> dict:
    """{업적키: 해금시각ISO} 형태예요."""
    return await asyncio.to_thread(_unlocked_sync, user_id)


async def evaluate(user_id, stats: dict, *, give_reward: bool = True) -> list[dict]:
    """조건을 만족한 업적 중 **이번에 처음 열린 것들**을 돌려주고, 보상 코인을 줘요.

    이미 열려 있던 건 목록에 없어요. 돌려주는 건 achievement_data의 업적 dict 그대로예요."""
    already = await unlocked_keys(user_id)
    newly = []

    for achievement in achievement_data.ACHIEVEMENTS:
        if achievement["key"] in already:
            continue
        if not achievement_data.is_unlocked(achievement, stats):
            continue
        if not await asyncio.to_thread(_try_unlock_sync, user_id, achievement["key"]):
            continue  # 그 찰나에 다른 호출이 먼저 열었어요 - 코인은 그쪽이 줘요
        newly.append(achievement)

    if newly and give_reward:
        total = sum(a["reward"] for a in newly)
        try:
            await coin_wallet.add(user_id, total, reason=f"업적 {len(newly)}개 달성")
        except Exception:
            # 코인 지급이 실패해도 해금 자체는 유지해요(다시 열리진 않지만, 기록이
            # 뒤로 돌아가는 것보다 낫고 수동 보정이 가능해요).
            log.exception("업적 보상 지급 실패 (user=%s, %d코인)", user_id, total)
        log.info("🏆 업적 해금: user=%s %s (+%d코인)",
                 user_id, ", ".join(a["name"] for a in newly), total)

    return newly


async def summary(user_id, stats: dict) -> dict:
    """카드/목록에 쓸 요약이에요. {unlocked: 23, total: 60, keys: {...}}"""
    keys = await unlocked_keys(user_id)
    return {"unlocked": len(keys), "total": achievement_data.TOTAL, "keys": keys}
