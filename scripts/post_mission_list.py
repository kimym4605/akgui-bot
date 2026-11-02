# -*- coding: utf-8 -*-
"""🎯 `#🎯｜미션-내용`의 전체 목록 핀을 **코드에서 생성해서** 제자리 수정해요.

## 왜 스크립트인가

2026-10-23에 이 글을 처음 올릴 때도 **손으로 쓰지 않고 `MISSIONS`에서 생성**했어요.
숫자를 손으로 박으면 코드와 어긋나거든요 — 실제로 2026-11-02에 희귀도 차등을 넣었을 때
`scan_guides.py`가 **"하루 최대 3코인"**(실제 15)과 **"리롤권 2코인"**(실제 4)을 잡아냈어요.
그런데 그때 생성 스크립트가 커밋돼 있지 않아서 **손으로 다시 쓸 판**이었어요. 그래서 이번엔
스크립트로 남겨요. 다음에 미션을 추가하거나 티어를 바꾸면 이걸 다시 돌리면 돼요.

## 쓰는 법

    python scripts/post_mission_list.py            # 미리보기만 (아무것도 안 보냄)
    python scripts/post_mission_list.py --send     # 실제로 PATCH

🚨 **`--send` 없이 먼저 돌려서 눈으로 볼 것.**
🚨 보내기 전에 **백업을 뜬다**(`backups/mission_list_<stamp>/`). 2026-10-31에 429를
   맞고 메시지가 깨졌을 때 그 백업이 있어서 복구했어요.
🚨 **1시간 넘은 메시지는 편집 횟수 한도가 있어요**(429 `code 30046`). 여기는 1개만
   고치니 걸릴 일이 거의 없지만, 걸리면 `retry_after`를 보고 기다렸다 한 번 더 해요.
🚨 운영 토큰은 `악귀봇프로젝트/운영봇_토큰_백업.env`예요. 배포 소스의 `.env`는
   **TEST봇**이라 403이 나요.
🚨 `urllib`로 디스코드를 부를 땐 **User-Agent가 필수**예요(없으면 Cloudflare `1010`).
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv                      # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
# mission_store가 import 시점에 Mongo 클라이언트를 만들어요(연결은 지연돼요).
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

from utils.mission_store import (                   # noqa: E402
    ADULT_ONLY_KEYS, DAILY_MISSION_COUNT, MAX_DAILY_REWARD, MISSIONS,
    ONE_TIME_MISSIONS, RARITY, REROLL_LIMIT_PER_DAY, REROLL_PRICE,
    SERVER_KEYS, VALORANT_KEYS, VOICE_MIN_MEMBERS, rarity_of, reward_of,
)

KST = timezone(timedelta(hours=9))
CHANNEL_ID = "1546034268550070364"      # #🎯｜미션-내용
DISCORD_LIMIT = 2000
LINE = "━━━━━━━━━━━━━━━"


# ------------------------------------------------------------------ 본문 생성
def _mission_line(key: str) -> str:
    """미션 한 줄. 🏅 희귀도 배지와 보상을 **코드에서** 붙여요."""
    info = MISSIONS[key]
    r = rarity_of(key)
    # ⚠️ `desc`에 이미 🔞가 들어 있는 미션이 있어요 — 그때 또 붙이면 🔞가 두 번 나와요.
    adult = " 🔞" if key in ADULT_ONLY_KEYS and "🔞" not in info["desc"] else ""
    # target이 1이면 "목표 1회"가 군더더기라 적지 않아요.
    goal = f" (목표 {info['target']}{info['unit']})" if info["target"] > 1 else ""
    return f"· {r['emoji']} **{info['title']}**{adult} — {info['desc']}{goal} **{r['reward']}코인**"


def build() -> str:
    rarity_desc = " · ".join(
        f"{r['emoji']} {r['label']} **{r['reward']}코인**" for r in RARITY.values()
    )
    parts = [
        "🎯 **미션 전체 목록**",
        f"하루 **{DAILY_MISSION_COUNT}개**가 배정되고, 깬 미션의 **희귀도만큼** 악귀코인을 받아요 "
        f"(하루 최대 {MAX_DAILY_REWARD}코인).",
        f"　└ {rarity_desc}",
        "　└ 일부러 하러 가야 하는 미션이 더 많이 줘요. 그냥 있어도 깨지는 미션은 적게 줘요.",
        "오늘 내 미션은 `/미션`으로 확인하세요.",
        "",
        LINE,
        f"🏠 **서버 미션** ({len(SERVER_KEYS)}종)",
        "조건을 채우면 **바로** 반영돼요.",
        "",
    ]
    parts += [_mission_line(k) for k in SERVER_KEYS]
    parts += [
        "",
        "　└ 🔞 미션은 **성인 인증을 받은 분에게만** 배정돼요 (인증이 없으면 아예 안 나와요)",
        f"　└ 🗣️ '같이 통화하기'는 **{VOICE_MIN_MEMBERS}명 이상** 있어야 인정돼요 (혼자 접속은 안 돼요)",
        "",
        LINE,
        f"🎮 **발로란트 미션** ({len(VALORANT_KEYS)}종)",
        "봇이 **30분마다 전적을 확인해서 자동으로** 체크해요 (깬 직후 바로는 안 뜰 수 있어요).",
        "`/전적`에 계정이 등록돼 있어야 봇이 찾을 수 있어요.",
        "",
    ]
    parts += [_mission_line(k) for k in VALORANT_KEYS]
    parts += [
        "",
        LINE,
        "🎁 **한 번만 받는 미션**",
        "",
    ]
    for key, info in ONE_TIME_MISSIONS.items():
        parts.append(f"· **{info['title']}** — {info['desc']} (**+{info['reward']}코인**)")
    parts += [
        "",
        LINE,
        "📌 **알아두면 좋은 것**",
        "",
        "· 계정을 연동하면 **발로란트 1개 + 서버 2개**를 받아요. 연동 전에는 서버 미션 3개예요.",
        f"· 마음에 안 드는 미션은 🎲 **리롤권**({REROLL_PRICE}코인 · `/악귀상점`)으로 "
        f"**서버 미션으로** 바꿔요 — 하루 {REROLL_LIMIT_PER_DAY}번.",
        "· 미션은 매일 자정(한국시간)에 새로 배정돼요.",
        "· 완료 알림이 시끄러우면 `/알림설정`에서 꺼요 (코인은 그대로 쌓여요).",
    ]
    return "\n".join(parts)


# ------------------------------------------------------------------ 디스코드
def _headers() -> dict:
    path = os.path.join(os.path.dirname(BOT_DIR), "운영봇_토큰_백업.env")
    conf = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.strip().partition("=")
                conf[k] = v
    if not conf.get("DISCORD_TOKEN"):
        sys.exit(f"🚨 {path} 에 DISCORD_TOKEN이 없어요")
    return {
        # 🚨 User-Agent가 없으면 Cloudflare 1010이 403처럼 보여요.
        "Authorization": f"Bot {conf['DISCORD_TOKEN']}",
        "User-Agent": "DiscordBot (https://github.com/akgui, 1.0)",
        "Content-Type": "application/json",
    }


def _call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"https://discord.com/api/v10{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=_headers(),
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def find_pin() -> dict:
    """미션 목록 핀을 찾아요. 🚨 **message_id를 코드에 박지 않아요** — 재게시될 때마다
    낡아서 404를 맞고 나서야 알게 돼요(메모리에 그 사고가 적혀 있어요)."""
    pins = _call("GET", f"/channels/{CHANNEL_ID}/pins")
    items = pins.get("items", pins) if isinstance(pins, dict) else pins
    cands = []
    for p in items:
        m = p.get("message", p)
        if "미션 전체 목록" in (m.get("content") or ""):
            cands.append(m)
    if len(cands) != 1:
        sys.exit(f"🚨 '미션 전체 목록' 핀이 {len(cands)}개예요 (1개여야 해요). "
                 f"핀 {len(items)}개를 직접 확인하세요.")
    return cands[0]


def backup(msg: dict) -> str:
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    out = os.path.join(BOT_DIR, "backups", f"mission_list_{stamp}")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "message.json"), "w", encoding="utf-8") as f:
        json.dump(msg, f, ensure_ascii=False, indent=2)
    return out


def patch(message_id: str, content: str):
    """🚨 429 `code 30046`(1시간 넘은 메시지 편집 한도)면 기다렸다 **한 번만** 더 해요."""
    for attempt in (1, 2):
        try:
            return _call("PATCH", f"/channels/{CHANNEL_ID}/messages/{message_id}",
                         {"content": content})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt == 1:
                wait = 5.0
                try:
                    wait = float(json.loads(raw).get("retry_after") or wait)
                except Exception:                      # noqa: BLE001
                    pass
                print(f"  ⚠️ 429 — {wait:.1f}초 기다렸다 한 번 더 할게요: {raw[:160]}")
                time.sleep(wait + 1)
                continue
            sys.exit(f"🚨 PATCH 실패 {e.code}: {raw[:400]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="실제로 PATCH해요 (없으면 미리보기)")
    args = ap.parse_args()

    body = build()
    print(body)
    print("\n" + "=" * 60)
    print(f"길이 {len(body)}자 / 한도 {DISCORD_LIMIT}자")
    # 🚨 2000자를 넘으면 PATCH가 그냥 실패해요. 보내기 전에 막아요.
    if len(body) > DISCORD_LIMIT:
        sys.exit(f"🚨 {len(body)}자로 한도({DISCORD_LIMIT})를 넘었어요. 나눠야 해요.")

    if not args.send:
        print("미리보기만 했어요. 실제로 올리려면 --send 를 붙이세요.")
        return

    msg = find_pin()
    print(f"대상 핀: {msg['id']} (현재 {len(msg.get('content') or '')}자)")
    if (msg.get("content") or "") == body:
        print("✅ 이미 같은 내용이에요 — 아무것도 안 했어요.")
        return
    print(f"백업: {backup(msg)}")

    patch(msg["id"], body)

    # 🚨 **"응답 OK"만 보고 끝내지 않아요.** 다시 읽어서 글자까지 같은지 봐요
    #    (2026-10-31에 응답은 정상인데 내용이 깨진 적이 있어요).
    again = _call("GET", f"/channels/{CHANNEL_ID}/messages/{msg['id']}")
    if (again.get("content") or "") == body:
        print("✅ 다시 읽어서 대조했어요 — 완전 일치.")
    else:
        sys.exit("🚨 반영 후 내용이 다릅니다. 백업으로 되돌릴지 확인하세요.")


if __name__ == "__main__":
    main()
