# -*- coding: utf-8 -*-
"""📮 **이미 올라와 있던** 테마 요청글에 📮 를 달아요 (2026-11-04, 1회성).

## 왜 필요한가

줍기는 `on_message`로 **새 글**에만 📮 를 달아요. 그런데 기능을 만든 이유가 바로
**이미 와 있던 요청**이에요 — `#🎴｜프로필`의 11-04 05:19 `"민영아 나 이거"` +
`IMG_5014.png`. 그 글은 새 글이 아니라서 영원히 안 주워져요.

`on_raw_reaction_add`는 **옛 글에도** 돌아가니(그래서 `raw`를 써요), 📮 만 달아두면
누가 누르는 순간 요청으로 들어가요. 그래서 이 스크립트가 📮 만 달아줘요.

🚨 **등록까지 대신 하지 않아요.** 요청자가 아닌 내가 DB에 넣으면 "누가 원했나"가
   흐려져요. 📮 를 달아두고 **사람이 누르게** 둬요(봇이 달아둔 📮 는 리스너가
   자기 것으로 알아보고 무시해요 — `payload.user_id == bot.user.id`).

## 쓰는 법

    python scripts/backfill_theme_pickup.py          # 미리보기
    python scripts/backfill_theme_pickup.py --send   # 실제로 📮 달기

게이트(`cogs.akgui_shop.looks_like_theme_request`)를 **그대로 재사용**해요 — 여기에
조건을 베껴 적으면 두 곳이 어긋나요.

## ✅ 반영이 끝난 요청글 닫기

    python scripts/backfill_theme_pickup.py --close <메시지ID> --send

⭐ **테마를 만들고 나면 그 글의 📮 는 쓸모가 없어져요.** 그대로 두면 누가 눌러서
**이미 만든 캐릭터를 또 요청**으로 넣어요 — `/테마요청목록`에 안 해도 될 줄이 쌓여요.
그래서 📮 를 떼고 ✅ 를 달아요(봇이 요청을 받았을 때 다는 표시와 같아요).
"""
import argparse
import json
import os
import sys
import types
import urllib.error
import urllib.parse
import urllib.request

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv                      # noqa: E402

load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

from cogs.akgui_shop import (                       # noqa: E402
    PICKED_EMOJI, PICKUP_EMOJI, THEME_PICKUP_FALLBACK, THEME_PICKUP_GROUP,
    looks_like_theme_request,
)
from utils.channel_check import get_allowed_channel_id  # noqa: E402

LOOKBACK = 100


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


def _call(method: str, path: str):
    req = urllib.request.Request(f"https://discord.com/api/v10{path}",
                                 headers=_headers(), method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def _as_message(raw: dict, owner_id: int):
    """게이트에 넣을 수 있게 REST 응답을 감싸요. (게이트가 쓰는 칸만 채워요)"""
    author = raw.get("author") or {}
    return types.SimpleNamespace(
        author=types.SimpleNamespace(bot=bool(author.get("bot")),
                                     id=int(author.get("id") or 0)),
        guild=types.SimpleNamespace(owner_id=owner_id),
        mention_everyone=bool(raw.get("mention_everyone")),
        attachments=[types.SimpleNamespace(filename=a.get("filename"),
                                           content_type=a.get("content_type"))
                     for a in (raw.get("attachments") or [])],
        content=raw.get("content") or "",
    )


def _close(channel_id: str, message_id: str, send: bool) -> None:
    """반영이 끝난 요청글: 📮 를 떼고 ✅ 를 달아요.

    🚨 **떼는 건 봇이 단 📮 하나(`/@me`)뿐이에요.** 사람이 누른 📮 까지 지우면
    (`/reactions/📮` 전체 삭제) 누가 원했는지 기록이 사라져요.
    """
    msg = _call("GET", f"/channels/{channel_id}/messages/{message_id}")
    author = (msg.get("author") or {}).get("username")
    marks = [(r["emoji"]["name"], r["count"], r.get("me"))
             for r in (msg.get("reactions") or [])]
    print(f"대상: {msg['timestamp'][:16]} {author} "
          f"{(msg.get('content') or '')[:40]!r}\n  지금 리액션: {marks}")
    if not send:
        print(f"\n미리보기만 했어요. 실제로 바꾸려면 --close {message_id} --send")
        return

    pick, done = urllib.parse.quote(PICKUP_EMOJI), urllib.parse.quote(PICKED_EMOJI)
    for method, path, what in (
        ("PUT", f"/reactions/{done}/@me", f"{PICKED_EMOJI} 달기"),
        ("DELETE", f"/reactions/{pick}/@me", f"{PICKUP_EMOJI} 떼기"),
    ):
        try:
            _call(method, f"/channels/{channel_id}/messages/{message_id}{path}")
            print(f"  ✅ {what}")
        except urllib.error.HTTPError as e:
            print(f"  🚨 {what} 실패 {e.code}: "
                  f"{e.read().decode('utf-8', 'replace')[:200]}")

    again = _call("GET", f"/channels/{channel_id}/messages/{message_id}")
    print("  재대조:", [(r["emoji"]["name"], r["count"], r.get("me"))
                      for r in (again.get("reactions") or [])])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    # 🚨 **로컬 `data/settings.json`은 프로덕션과 다릅니다.** 원본은 Fly 볼륨이고,
    #    로컬 사본엔 `pokemonChannel:profile`이 아예 없었어요(2026-11-04 확인).
    #    그래서 봇 안에서 도는 리스너는 제대로 채널을 잡는데, **이 스크립트만**
    #    못 잡아요. 볼륨을 받아오거나(`scripts/backup_volume.py`) 여기서 직접 줘요.
    ap.add_argument("--channel", help="줍기 채널 ID를 직접 지정 (로컬 설정이 낡았을 때)")
    ap.add_argument("--close", metavar="메시지ID",
                    help="반영이 끝난 요청글의 📮 를 떼고 ✅ 를 달아요")
    args = ap.parse_args()

    channel_id = args.channel or get_allowed_channel_id(
        THEME_PICKUP_GROUP, fallback_group=THEME_PICKUP_FALLBACK)
    if not channel_id:
        sys.exit("🚨 줍기 채널이 안 잡혀요. `python scripts/backup_volume.py`로 받아온 "
                 "`backups/volume_*/settings.json`의 `pokemonChannel:profile` 값을 "
                 "`--channel`로 주세요.")

    channel = _call("GET", f"/channels/{channel_id}")
    guild_id = channel["guild_id"]
    owner_id = int(_call("GET", f"/guilds/{guild_id}")["owner_id"])
    me_id = _call("GET", "/users/@me")["id"]
    print(f"채널 #{channel['name']} ({channel_id}) · 소유자 {owner_id}\n")

    if args.close:
        return _close(channel_id, args.close, args.send)

    msgs = _call("GET", f"/channels/{channel_id}/messages?limit={LOOKBACK}") or []
    hits = [m for m in msgs if looks_like_theme_request(_as_message(m, owner_id))]
    print(f"최근 {len(msgs)}개 중 줍을 글 {len(hits)}개")

    todo = []
    for m in hits:
        marks = [r for r in (m.get("reactions") or [])
                 if (r.get("emoji") or {}).get("name") == PICKUP_EMOJI]
        done = " (📮 이미 달려 있음)" if marks else ""
        atts = ",".join(a.get("filename") or "" for a in (m.get("attachments") or []))
        print(f"  {m['timestamp'][:16]} {(m.get('author') or {}).get('username')}"
              f" [{atts}] {(m.get('content') or '')[:50]!r}{done}")
        if not marks:
            todo.append(m)

    if not args.send:
        print(f"\n미리보기만 했어요(달 것 {len(todo)}개). 실제로 달려면 --send")
        return

    em = urllib.parse.quote(PICKUP_EMOJI)
    for m in todo:
        try:
            _call("PUT", f"/channels/{channel_id}/messages/{m['id']}"
                         f"/reactions/{em}/@me")
            print(f"  ✅ 📮 달았어요 — {m['id']}")
        except urllib.error.HTTPError as e:
            print(f"  🚨 실패 {e.code} — {m['id']}: "
                  f"{e.read().decode('utf-8', 'replace')[:200]}")

    # 🚨 "200 ok"를 믿지 말고 **다시 읽어서** 확인해요.
    for m in todo:
        again = _call("GET", f"/channels/{channel_id}/messages/{m['id']}")
        got = [(r['emoji']['name'], r['count'], r.get('me'))
               for r in (again.get("reactions") or [])]
        print(f"  재대조 {m['id']}: {got}")

    print(f"\n✅ {len(todo)}개에 📮 를 달았어요 (bot={me_id}). "
          "누가 누르면 그 글이 테마 요청으로 들어가요.")


if __name__ == "__main__":
    main()
