# -*- coding: utf-8 -*-
"""🧩 발로들 성공 지표 — 실제로 쓰이는지 DB 건수로 확인해요.

    python scripts/report_balodle.py            # 최근 14일
    python scripts/report_balodle.py --days 30

## 왜 있나

이 프로젝트에서는 만들고 아무도 안 쓴 기능이 여러 번 있었어요(리롤권·보호권·테마 0건).
기획서의 네 가지 지표를 한 번에 세요.

1. 하루 참여자 수 (문제별) — 연 사람(`opened_at`) / 끝낸 사람(`status`가 solved·failed)
2. 문제별 정답률·평균 시도 횟수 — 맞힌 사람 / 끝낸 사람, 맞힌 사람의 답 개수 평균
3. 2주 뒤에도 푸는 사람 — 첫 주(시작일~+6일)에 푼 사람 중 셋째 주(+14~+20일)에도 푼 사람
4. 알림 역할을 단 사람 — `balodle_users.notify == true`

코인 발행량은 `scripts/report_economy.py`에 `발로들` 사유로 잡혀요.
🚨 읽기만 해요. 운영 DB(`.env`의 `MONGODB_URI`)를 그대로 봐요.
"""
import argparse
import os
import sys
from datetime import date, timedelta

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))

from utils import balodle_data, balodle_logic as logic  # noqa: E402

KIND_NAME = {"agent": "요원", "ability": "스킬", "map": "맵"}
DONE = ("solved", "failed")


def daily_rows(plays: list[dict]) -> dict:
    """날짜 → 종류 → {opened, finished, solved, attempts(맞힌 사람의 답 개수 합)}."""
    table: dict = {}
    for play in plays:
        day = table.setdefault(play.get("date"), {
            k: {"opened": 0, "finished": 0, "solved": 0, "attempts": 0} for k in logic.KINDS})
        for kind in logic.KINDS:
            part = play.get(kind) or {}
            if part.get("opened_at"):
                day[kind]["opened"] += 1
            if part.get("status") in DONE:
                day[kind]["finished"] += 1
            if part.get("status") == "solved":
                day[kind]["solved"] += 1
                day[kind]["attempts"] += len(part.get("guesses") or [])
    return table


def totals(table: dict) -> dict:
    total = {k: {"opened": 0, "finished": 0, "solved": 0, "attempts": 0} for k in logic.KINDS}
    for day in table.values():
        for kind in logic.KINDS:
            for field in total[kind]:
                total[kind][field] += day[kind][field]
    return total


def played_uids(plays: list[dict], first: str, last: str) -> set:
    """그 기간에 한 문제라도 **끝낸** 사람."""
    return {
        p.get("uid") for p in plays
        if first <= (p.get("date") or "") <= last
        and any((p.get(k) or {}).get("status") in DONE for k in logic.KINDS)
    }


def retention(plays: list[dict], start: str) -> tuple[int, int, str, str]:
    """(첫 주에 푼 사람, 그중 셋째 주에도 푼 사람, 셋째 주 시작, 셋째 주 끝)."""
    day0 = date.fromisoformat(start)
    week1 = played_uids(plays, start, (day0 + timedelta(days=6)).isoformat())
    w3_first, w3_last = (day0 + timedelta(days=14)).isoformat(), (day0 + timedelta(days=20)).isoformat()
    week3 = played_uids(plays, w3_first, w3_last)
    return len(week1), len(week1 & week3), w3_first, w3_last


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="최근 며칠을 볼지 (기본 14)")
    args = parser.parse_args()

    from utils import balodle_store   # DB 연결은 여기서 (지표 계산 함수는 DB 없이 테스트해요)

    today = logic.today_iso()
    since = (date.fromisoformat(today) - timedelta(days=args.days - 1)).isoformat()
    start = balodle_data.SETTINGS["start_date"]
    plays = list(balodle_store._plays.find({"date": {"$gte": min(since, start)}}))
    recent = [p for p in plays if (p.get("date") or "") >= since]

    print(f"🧩 발로들 지표 — {since} ~ {today} ({args.days}일)\n")
    table = daily_rows(recent)
    if not table:
        print("  ⚠️ 이 기간에 풀이 기록이 0건이에요. 패널이 올라가 있는지, 버튼이 눌리는지 확인해 주세요.")
    else:
        print("1) 하루 참여자 수 — 연 사람 / 끝낸 사람")
        print("   날짜         " + "   ".join(f"{KIND_NAME[k]:>8}" for k in logic.KINDS))
        for day in sorted(table):
            cells = "   ".join(
                f"{table[day][k]['opened']:>3} / {table[day][k]['finished']:<3}" for k in logic.KINDS)
            print(f"   {day}   {cells}")

        print("\n2) 문제별 정답률 · 평균 시도 횟수")
        for kind, t in totals(table).items():
            rate = f"{t['solved'] * 100 / t['finished']:.0f}%" if t["finished"] else "-"
            avg = f"{t['attempts'] / t['solved']:.2f}번" if t["solved"] else "-"
            print(f"   {KIND_NAME[kind]}: 끝낸 {t['finished']}건 중 {t['solved']}건 정답 ({rate}) · "
                  f"맞힌 사람 평균 {avg}")

    week1, kept, w3_first, w3_last = retention(plays, start)
    print(f"\n3) 2주 뒤에도 푸는 사람 (시작일 {start})")
    if today < w3_first:
        print(f"   첫 주에 푼 사람 {week1}명 · 셋째 주({w3_first}~{w3_last})가 아직 안 왔어요")
    else:
        rate = f"{kept * 100 / week1:.0f}%" if week1 else "-"
        print(f"   첫 주에 푼 사람 {week1}명 중 셋째 주에도 푼 사람 {kept}명 ({rate})")

    notify = balodle_store._users.count_documents({"notify": True})
    print(f"\n4) 알림 역할을 단 사람: {notify}명")
    return 0


if __name__ == "__main__":
    sys.exit(main())
