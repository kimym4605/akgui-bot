# -*- coding: utf-8 -*-
"""📋 디스코드 안내문이 코드와 어긋났는지 훑어요 (2026-10-31 신설).

## 왜 필요한가 — 같은 사고가 **네 번** 났어요

| 날짜 | 사고 |
|---|---|
| 10-18 | topic·핀 **8곳**이 거짓이었다 |
| 10-20 | `🎣낚시터` topic에 없어진 '늦었다' 판정이 남아 있었다 (+핀 4곳) |
| 10-23 | `#🤖봇-사용법`의 낚시 등급표가 **7일간 수익을 1/3 낮게** 말했다 |
| 10-30 | `/방만들기` 안내가 "승인해야 들어올 수 있어요"로 거짓말했다 |

메모리에 *"배포할 때마다 `scan_guides` 식으로 한 번 훑을 것"*이라 적어뒀는데 **그 도구가
없어서** 매번 손으로 훑었어요. 이게 그 도구예요.

## 어떻게 — **상수를 손으로 나열하지 않아요**

손으로 적은 목록은 그것도 썩어요(그게 애초의 문제예요). 그래서:

1. 기능 모듈에서 **숫자 상수를 자동으로 긁어** '정본 숫자 집합'을 만들어요
   (`card_store`·`fish_data`·`mission_store`·`casino_store` …의 대문자 int/float)
2. 디스코드 topic·핀에서 **`숫자+단위`**(코인·장·종·회·분·%·마리·판)를 뽑아요
3. 정본 집합에 **없는 숫자**를 의심으로 올려요

⚠️ 자동 판정이 아니라 **사람이 읽는 보고서**예요. 정본에 없어도 멀쩡한 숫자가 있어요
   (날짜·순위·예시). 그래서 "틀렸다"가 아니라 "확인해 보라"로 보고해요.

🚨 `--strict`를 주면 **알려진 옛 값**(아래 `STALE`)이 하나라도 있으면 종료코드 1이에요.
   그건 오탐이 아니라 확실한 거짓이라 배포 관문에 넣을 수 있어요.

## 쓰는 법

    python scripts/scan_guides.py              # 전체 훑기
    python scripts/scan_guides.py --only 낚시   # 그 채널만
    python scripts/scan_guides.py --strict     # 옛 값이 있으면 exit 1
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)
from dotenv import load_dotenv                      # noqa: E402
load_dotenv(os.path.join(BOT_DIR, ".env"))
os.environ.setdefault("MONGODB_DB_NAME", "agwi_profile_test")

# ------------------------------------------------------------------ 정본 숫자 모으기
# 🚨 **모듈을 손으로 나열하지 않아요.** `utils/*.py`를 전부 긁어요.
#    처음엔 7개만 적었는데 `title_store.TITLE_PLANS[10]`(=12)와
#    `card_market.MAX_PRICE`(=1000)가 목록에 없어서 **멀쩡한 안내문을 의심으로 올렸어요**
#    (2026-10-31). 목록을 손으로 유지하면 그것도 썩어요 — 그게 애초의 문제예요.
# ⚠️ DB·네트워크를 건드리는 모듈은 임포트가 무거우니 건너뛰어요.
SKIP_MODULES = {"pokemon_store"}


def _truth_modules() -> list[str]:
    names = []
    for fn in sorted(os.listdir(os.path.join(BOT_DIR, "utils"))):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        stem = fn[:-3]
        if stem in SKIP_MODULES:
            continue
        names.append(f"utils.{stem}")
    return names


TRUTH_MODULES = _truth_modules()

# 🚨 임포트가 깨진 모듈 — 하나라도 있으면 그 기능 검사는 무력화돼요(`--strict`가 exit 1).
IMPORT_FAILS: list = []


def _add_normalized_percents(d: dict, nums: set, where: dict, src: str) -> None:
    """dict 안의 숫자(또는 `weight` 키)를 **합으로 나눈 퍼센트**를 정본에 넣어요.

    확률 안내문은 상수를 그대로 쓰지 않고 정규화해서 적어요:
    `GRADES[일반][weight] = 135` · 합 149.2 → **90.5%**.
    소수 0·1·2자리로 반올림한 값을 다 넣어요(안내문마다 자리수가 달라요)."""
    vals = {}
    for k, v in d.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals[k] = float(v)
        elif isinstance(v, dict):
            w = v.get("weight")
            if isinstance(w, (int, float)) and not isinstance(w, bool):
                vals[k] = float(w)
    total = sum(vals.values())
    if total <= 0 or len(vals) < 2:
        return
    for k, v in vals.items():
        pct = v / total * 100
        for digits in (0, 1, 2):
            nums.add(round(pct, digits))
            where.setdefault(round(pct, digits), []).append(f"{src}[{k}] 정규화 %")


def collect_truth(only: list | None = None) -> tuple[set, dict]:
    """기능 모듈의 **대문자 숫자 상수**를 모아요. (숫자 집합, 출처 표)

    `only`에 모듈 **짧은 이름** 목록을 주면 그것만 봐요 — 채널별로 좁히는 데 써요."""
    nums, where = set(), {}
    import importlib
    mods = ([f"utils.{m}" for m in only] if only else TRUTH_MODULES)
    for mod_name in mods:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:                      # noqa: BLE001
            # 🚨🚨 **조용히 넘기면 안 돼요.** 그 기능의 정본이 비어서 안내문이
            #    **전부 ✅로 보여요** — 모듈명 오타 하나로 검사가 통째로 무력화돼요.
            #    2026-10-31에 `attend_store`(실제는 `attend_service`)로 적어 실제로 그랬어요.
            IMPORT_FAILS.append((mod_name, type(exc).__name__))
            print(f"  🔴 {mod_name} 임포트 실패: {type(exc).__name__}"
                  f" — 이 기능 검사가 무력화됩니다")
            continue
        for name in dir(mod):
            if not name.isupper():
                continue
            val = getattr(mod, name)
            if isinstance(val, bool):
                continue
            if isinstance(val, (int, float)):
                nums.add(float(val))
                where.setdefault(float(val), []).append(f"{mod_name.split('.')[-1]}.{name}")
            elif isinstance(val, dict):
                # 🚨 **가중치를 정규화한 퍼센트도 정본이에요.** 안내문엔 확률이
                #    `135/149.2*100 = 90.5%` 꼴로 적히는데, 그 90.5는 어떤 상수에도
                #    없어서 전부 의심으로 올라왔어요(2026-10-31 실측: 낚시 등급표 4건이
                #    그렇게 오탐이었고 **값은 전부 정확했어요**).
                _add_normalized_percents(val, nums, where,
                                         f"{mod_name.split('.')[-1]}.{name}")
                # 가중치·가격표처럼 dict 안에 든 숫자도 정본이에요
                for k, v in val.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        nums.add(float(v))
                        where.setdefault(float(v), []).append(f"{mod_name.split('.')[-1]}.{name}[{k}]")
                    elif isinstance(v, dict):
                        for k2, v2 in v.items():
                            if isinstance(v2, (int, float)) and not isinstance(v2, bool):
                                nums.add(float(v2))
                                where.setdefault(float(v2), []).append(
                                    f"{mod_name.split('.')[-1]}.{name}[{k}][{k2}]")
                    elif isinstance(v, (list, tuple)):
                        for v2 in v:
                            if isinstance(v2, (int, float)) and not isinstance(v2, bool):
                                nums.add(float(v2))
            elif isinstance(val, (list, tuple)):
                for v in val:
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        nums.add(float(v))
                        where.setdefault(float(v), []).append(f"{mod_name.split('.')[-1]}.{name}")
    # 종 수·개수처럼 len()으로 나오는 정본도 넣어요 (범위를 좁혔으면 그 기능만)
    def _want(mod):
        return only is None or mod in only
    try:
        if not _want("card_data"):
            raise ImportError
        from utils import card_data
        for grade, lst in card_data.CARDS.items():
            nums.add(float(len(lst)))
            where.setdefault(float(len(lst)), []).append(f"card_data.CARDS[{grade}] 종수")
        nums.add(float(card_data.TOTAL))
    except Exception:                                  # noqa: BLE001
        pass
    try:
        if not _want("achievement_data"):
            raise ImportError
        from utils import achievement_data as ad
        for attr in ("ACHIEVEMENTS", "CATEGORIES"):
            v = getattr(ad, attr, None)
            if v is not None:
                nums.add(float(len(v)))
                where.setdefault(float(len(v)), []).append(f"achievement_data.{attr} 개수")
    except Exception:                                  # noqa: BLE001
        pass
    try:
        if not _want("fish_data"):
            raise ImportError
        from utils import fish_data
        for attr in ("FISH", "GRADE_ORDER"):
            v = getattr(fish_data, attr, None)
            if v is not None:
                nums.add(float(len(v)))
    except Exception:                                  # noqa: BLE001
        pass
    return nums, where


# 🔴 **알려진 옛 값** — 하나라도 보이면 확실한 거짓이에요(`--strict`가 exit 1).
#    🚨 여기엔 "지금 쓰이지 않는다고 확인한 값"만 넣어요. 애매한 건 넣지 마세요.
STALE = {
    "10연 = 레전드": "천장이 240장이 된 뒤로 거짓 (card_store.MAX_PULLS 주석)",
    "10연=레전드": "같음",
    "2.5초 안에": "🎣 '늦었다' 판정은 2026-10-19에 없어졌다",
    "늦으면 놓": "같음",
    "152종": "카드가 83종이다",
    "174종": "같음",
    "업적 60": "업적은 50개다",
    "승인해야 들어올 수 있어요": "🚪 운영진은 초대 없이 들어온다(2026-10-30)",
}

# ------------------------------------------------------------------ ⭐ 의미 연결 검사
# 🚨🚨 **이게 주 검사예요.** 아래 '숫자 집합' 방식은 보조일 뿐이에요 — 역방향 확인에서
#    7방향 중 4개를 놓쳤어요(2026-10-31). 이유가 분명해요: `PULL_PRICE`를 10→12로
#    바꿔도 같은 모듈의 `MAX_PULLS = 10`이 남아서 안내문의 **"10코인"이 정본으로
#    통과**해요. 단위가 같은 다른 상수가 숫자를 가려주는 거예요.
#
# ⭐ 그래서 **"이 문구의 이 숫자는 이 상수다"**를 적어요. 손으로 적는 건 **값이 아니라
#    연결**이라, 상수가 바뀌면 기대값이 자동으로 따라와요(안내문만 안 고치면 잡혀요).
#
# 형식: (채널 조각, 설명, 정규식, 기대값 함수 → 숫자 튜플)
#   정규식의 캡처 그룹 수와 기대값 길이가 같아야 해요.
def _asserts() -> list:
    out = []

    def add(ch, what, pattern, fn):
        out.append((ch, what, re.compile(pattern), fn))

    try:
        from utils import card_store as cs
        add("뽑기방", "뽑기 가격·장수", r"\*\*(\d+)코인에 (\d+)장\*\*",
            lambda: (cs.PULL_PRICE, cs.CARDS_PER_PULL))
        add("뽑기방", "전체 종수", r"\*\*(\d+)종\*\*", lambda: (cs.TOTAL,))
        add("뽑기방", "천장", r"\*\*(\d+)장\((\d+)뽑기\)\*\*",
            lambda: (cs.PITY_DRAWS, cs.PITY_DRAWS // cs.CARDS_PER_PULL))
        add("도감", "전체 종수", r"전체 (\d+)종", lambda: (cs.TOTAL,))
        add("뽑기방", "합성 재료", r"중복 \*\*?(\d+)장", lambda: (cs.FUSE_N,))
    except Exception:                                  # noqa: BLE001
        pass
    try:
        from utils import fish_data as fd
        # 🚨 `\*\*?` 는 "별표 0~2개"가 **아니에요** — 별표 1개 필수 + 1개 선택이에요.
        #    실제 문구가 `**낚시대 10코인**`처럼 별표가 **숫자 앞에 없어서** 전부
        #    매치가 안 됐어요(2026-10-31 역방향 확인에서 2건을 놓친 원인).
        #    별표를 건너뛰려면 `\*{0,2}` 로 쓰세요.
        add("낚시터", "낚시대 값", r"낚시대 \*{0,2}(\d+)코인", lambda: (fd.ROD_PRICE,))
        add("낚시터", "하루 상한", r"기본 (?:하루 )?\*{0,2}(\d+)번",
            lambda: (fd.DAILY_CAST_CAP,))
        add("낚시터", "낚시대 내구도", r"낚시대 \d+코인\*{0,2}[^\n]{0,6}?\*{0,2}(\d+)번",
            lambda: (fd.ROD_DURABILITY,))
        # 🚨 단위가 "회"가 아니라 **"번"**이에요(안내문을 직접 읽고 맞춰야 해요).
        add("낚시터", "연속 보너스", r"연속 출석 (\d+)일마다 \+(\d+)번",
            lambda: (fd.STREAK_CAST_EVERY, fd.STREAK_CAST_BONUS))
        add("낚시터", "연속 보너스 상한", r"최대 \+(\d+)번 = 하루 (\d+)번",
            lambda: (fd.STREAK_CAST_MAX,
                     fd.DAILY_CAST_CAP + fd.STREAK_CAST_MAX))
        add("악귀상점", "소형 낚시대 값", r"소형\*{0,2}\)?\s*\*{0,2}(\d+)코인",
            lambda: (fd.SMALL_ROD_PRICE,))
    except Exception:                                  # noqa: BLE001
        pass
    try:
        from utils import mission_store as ms
        add("미션-내용", "하루 미션 개수", r"하루 \*\*(\d+)개\*\*",
            lambda: (ms.DAILY_MISSION_COUNT,))
        add("미션-내용", "리롤 가격", r"리롤[^\n]{0,20}?(\d+)코인",
            lambda: (ms.REROLL_PRICE,))
    except Exception:                                  # noqa: BLE001
        pass
    try:
        from utils import title_store as ts
        add("악귀상점", "칭호 가격", r"칭호 — (\d+)코인\(10일\) / (\d+)코인\(30일\)",
            lambda: (ts.TITLE_PLANS[10], ts.TITLE_PRICE))
    except Exception:                                  # noqa: BLE001
        pass
    try:
        from utils import card_market as cm
        add("거래장터", "가격 범위", r"\*\*(\d+)~(\d+)코인\*\*",
            lambda: (cm.MIN_PRICE, cm.MAX_PRICE))
    except Exception:                                  # noqa: BLE001
        pass
    return out


ASSERTS = _asserts()

# 단위가 붙은 숫자만 본다 — 날짜·ID 같은 건 애초에 안 뽑는다
UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(코인|장|종|회|분|초|%|마리|판|개|명|일)")

# ------------------------------------------------------------------ 채널 ↔ 정본 범위
# 🚨🚨 **정본을 좁혀야 탐지가 된다.** 처음엔 `utils/*` 전체를 긁어 '전역 숫자 집합'으로
#    대조했는데, 역방향 확인에서 **6방향 중 1개만 잡혔다**(2026-10-31). `10`이
#    `ROD_PRICE`·`MAX_PULLS`·`ROD_DURABILITY`에도 있어서 **카드 가격이 틀려도 통과**했다.
#    오탐을 줄이려던 변경이 탐지력을 죽인 것이다.
# → 채널마다 **그 기능 모듈만** 본다. `None`이면 전역(여러 기능을 한 글에 담는 채널).
SCOPES = {
    "뽑기방": ["card_store", "card_data"],
    "도감": ["card_store", "card_data"],
    "거래장터": ["card_market", "card_store", "card_data"],
    "낚시터": ["fish_data", "fishing_store"],
    "도박장": ["casino_store"],
    "미션-내용": ["mission_store"],
    "출석체크": ["attend_service", "coin_ledger", "mission_store"],
    "악귀상점": ["title_store", "fish_data", "mission_store", "cosmetic_store",
               "casino_store", "inventory_store"],
    "프로필": ["achievement_data", "agwi_weekly_store"],
    # 아래는 여러 기능을 한 글에 담아서 전역으로 본다(그만큼 탐지력이 낮다)
    "봇-사용법": None,
    "랭크-파티구인": None,
    "폐관수련-모집": None,
    "내전모집": None,
    "프리미어-모집": None,
    "주간결산": None,
    "전적검색": None,
}
CHANNELS = list(SCOPES)

# ------------------------------------------------------------------ 디스코드에서 긁기
conf = {}
with open(os.path.join(os.path.dirname(BOT_DIR), "운영봇_토큰_백업.env"), encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip().strip('"').strip("'")
HDR = {"Authorization": f"Bot {conf['DISCORD_TOKEN']}",
       "User-Agent": "DiscordBot (https://example.com, 1.0)"}
API = "https://discord.com/api/v10"
GUILD = conf["GUILD_ID"]


def get(path):
    req = urllib.request.Request(API + path, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"__error__": e.code}


def flatten(msg) -> str:
    text = msg.get("content") or ""
    for e in msg.get("embeds") or []:
        text += "\n" + (e.get("title") or "") + "\n" + (e.get("description") or "")
        for fl in e.get("fields") or []:
            text += "\n" + fl.get("name", "") + " " + fl.get("value", "")
        text += "\n" + ((e.get("footer") or {}).get("text") or "")
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="이 이름이 들어간 채널만")
    ap.add_argument("--strict", action="store_true",
                    help="알려진 옛 값이 있으면 종료코드 1")
    args = ap.parse_args()

    print("=== 정본 숫자 모으기 (코드에서 자동) ===")
    global_truth, _gw = collect_truth()
    print(f"  전역: 모듈 {len(TRUTH_MODULES)}개에서 숫자 {len(global_truth)}개")
    scoped = {}
    for key, mods in SCOPES.items():
        if mods is None:
            scoped[key] = global_truth
        else:
            t, _ = collect_truth(mods)
            scoped[key] = t
            print(f"  {key}: {', '.join(mods)} → 숫자 {len(t)}개")

    chans = get(f"/guilds/{GUILD}/channels")
    if not isinstance(chans, list):
        print("채널 목록 실패:", chans)
        return 1

    targets = [c for c in chans
               if c["type"] in (0, 5)
               and any(n in c["name"] for n in CHANNELS)
               and (args.only is None or args.only in c["name"])]
    print(f"  대상 채널 {len(targets)}개\n")

    stale_hits, suspects = [], []
    for ch in sorted(targets, key=lambda c: c["name"]):
        blobs = [("topic", ch.get("topic") or "")]
        pins = get(f"/channels/{ch['id']}/pins")
        for m in pins if isinstance(pins, list) else []:
            blobs.append((f"핀 {m['id'][-6:]}", flatten(m)))
        # 봇-사용법은 핀이 아니라 본문에 있어요
        if "봇-사용법" in ch["name"]:
            msgs = get(f"/channels/{ch['id']}/messages?limit=30")
            for m in msgs if isinstance(msgs, list) else []:
                blobs.append((f"글 {m['id'][-6:]}", flatten(m)))

        # 🚨 이 채널의 **좁힌 정본**을 쓴다 (전역으로 대조하면 거의 안 잡힌다)
        scope_key = next((k for k in SCOPES if k in ch["name"]), None)
        truth = scoped.get(scope_key, global_truth)
        ch_stale, ch_susp = [], []
        for label, text in blobs:
            if not text.strip():
                continue
            for bad, why in STALE.items():
                if bad in text:
                    ch_stale.append((label, bad, why))
            # ⭐ 주 검사: 그 문구의 숫자가 **그 상수**와 같은지
            for a_ch, what, pat, fn in ASSERTS:
                if a_ch not in ch["name"]:
                    continue
                for mt in pat.finditer(text):
                    got = tuple(int(g) for g in mt.groups())
                    try:
                        want = tuple(int(x) for x in fn())
                    except Exception as exc:           # noqa: BLE001
                        ch_stale.append((label, f"{what}: 기대값을 못 읽음",
                                         f"{type(exc).__name__}"))
                        continue
                    if got != want:
                        ch_stale.append((
                            label,
                            f"{what}: 안내문 {got} ≠ 코드 {want}",
                            f"\"{mt.group(0)[:50]}\" 를 고쳐야 해요"))
            for m in UNIT_RE.finditer(text):
                num_s, unit = m.group(1), m.group(2)
                val = float(num_s)
                if val in truth:
                    continue
                # 1 같은 흔한 수나 순위·날짜성 표현은 소음이라 건너뛴다
                if unit in ("명", "일", "개") and val <= 31:
                    continue
                if val in (0.0, 1.0, 2.0):
                    continue
                # 🚨 **파생값은 코드 상수에 없는 게 당연해요.** "평균 21코인"·"약 460코인"·
                #    "환급률 90.6%"는 상수를 계산한 결과라 여기 걸리면 전부 오탐이에요.
                #    앞뒤 24자에 그런 수식어가 있으면 건너뛰어요.
                around = text[max(0, m.start() - 24):m.end() + 12]
                if any(w in around for w in ("평균", "약 ", "기대", "환급", "확률",
                                              "최대", "최소", "총 ", "합계", "까지")):
                    continue
                ch_susp.append((label, f"{num_s}{unit}"))

        if not ch_stale and not ch_susp:
            print(f"  ✅ #{ch['name']}")
            continue
        print(f"  {'🔴' if ch_stale else '⚠️'} #{ch['name']}")
        for label, bad, why in ch_stale:
            print(f"       🔴 {label}: \"{bad}\" — {why}")
            stale_hits.append((ch["name"], label, bad))
        seen = set()
        for label, tok in ch_susp:
            if (label, tok) in seen:
                continue
            seen.add((label, tok))
            print(f"       ⚠️ {label}: {tok} ← 코드 상수에 없는 값")
            suspects.append((ch["name"], label, tok))

    print("\n" + "=" * 60)
    if IMPORT_FAILS:
        print(f"🔴 임포트 실패 {len(IMPORT_FAILS)}개 — **그 기능 검사는 무력화됐어요**:")
        for mod, err in IMPORT_FAILS:
            print(f"     {mod} ({err}) ← SCOPES의 모듈 이름을 확인하세요")
    print(f"🔴 확실한 옛 값 {len(stale_hits)}건 · ⚠️ 확인 필요 {len(suspects)}건")
    if stale_hits:
        print("\n🔴 반드시 고칠 것:")
        for name, label, bad in stale_hits:
            print(f"  #{name} {label}: \"{bad}\"")
    if suspects:
        print("\n⚠️ 코드 상수에 없는 숫자 (멀쩡한 것도 섞여 있어요 — 눈으로 보세요):")
        for name, label, tok in suspects[:40]:
            print(f"  #{name} {label}: {tok}")
        if len(suspects) > 40:
            print(f"  … 외 {len(suspects) - 40}건")
    # 🚨 임포트 실패도 exit 1 — 검사가 무력화된 상태로 "정상"을 보고하면 안 돼요.
    if args.strict and (stale_hits or IMPORT_FAILS):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
