"""
1회성 마이그레이션: attendanceStreak 필드가 없는 기존 트레이너들에게
현재 coin 잔액을 초깃값으로 채워요.

coin 시스템(2026-08-24 시작)이 하루 1개씩만 지급하는 구조라, 코인을 하나도
안 썼다면 coin == 그동안 출석한 날수와 같아요. 실제로 지금(2026-08-29, 시작
6일째)까지 매일 빠짐없이 찍은 유저들은 coin=6·attendance=6으로 정확히 맞아
떨어지는 걸 확인했어요.

중간에 하루라도 빠진 유저는 이 값이 부정확할 수 있지만 상관없어요 -
attend()의 로직상 다음 출석 때 lastAttendanceDate가 "어제"가 아니면
attendanceStreak을 무조건 1로 새로 리셋하기 때문에, 여기서 넣은 값은
"현재도 이어지고 있는 연속 출석자"에게만 실질적으로 의미가 있어요.

실행: python scripts/backfill_attendance_streak.py
"""
import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("MONGODB_DB_NAME", "pokemon_game")]
trainers = db["trainers"]

result = trainers.update_many({}, [{"$set": {"attendanceStreak": {"$ifNull": ["$coin", 0]}}}])
print(f"matched={result.matched_count} modified={result.modified_count}")

for doc in trainers.find({}, {"coin": 1, "attendanceStreak": 1, "lastAttendanceDate": 1}):
    print(doc.get("_id"), "coin=", doc.get("coin"), "streak=", doc.get("attendanceStreak"), "last=", doc.get("lastAttendanceDate"))
