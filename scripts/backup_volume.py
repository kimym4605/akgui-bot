# -*- coding: utf-8 -*-
"""🗄️ Fly 볼륨(`/app/data`) 백업 (2026-10-31 신설).

## 왜 따로 필요한가

DB(Atlas)와 **별개 저장소**예요. 봇의 일부 상태는 볼륨 파일에만 있어요:

| 파일 | 들어 있는 것 |
|---|---|
| `settings.json` | `/채널설정` 값 — **이게 날아가면 기능별 채널 지정이 전부 풀려요** |
| `riot_accounts.json` | 라이엇 계정 연동 |
| `rank_stats.json` | `/전적` 마지막 조회 결과(프로필 카드가 써요) |
| `valorant_wishlist.json` | 🔫 위시리스트 |
| `dynamic_rooms.json` · `team_sessions.json` | 열린 방·팀 편성(수명이 짧아요) |

🚨 **`riot_sessions.json`(라이엇 쿠키)은 일부러 받지 않아요.** 분류기가 막고(합당해요),
   유출되면 남의 계정에 들어갈 수 있는 물건이라 로컬에 두는 것 자체가 위험해요.
   → 쿠키는 **백업 대상이 아니고**, 날아가면 유저가 `/오상`에서 다시 등록하면 돼요.

🚨 `practice_rooms.json`·`rank_rooms.json`은 **옛 형식**이고 통합 때 지워졌어요
   (`cogs/room.py`의 `_migrate_legacy_stores`가 `unlink`해요). 없는 게 정상이에요.

## 🚨 되돌리는 건 **반쪽만** 가능해요

`flyctl sftp put`은 **기존 파일을 못 덮어써요**(먼저 지워야 하는데 sftp엔 `rm`이 없어요).
그래서 이 백업은 **"무슨 값이었는지 아는" 용도**예요. 복원은:
  ⒜ 파일이 **없어진 경우**엔 `sftp put`으로 바로 올릴 수 있어요
  ⒝ 파일이 **있는데 내용이 틀린 경우**엔 못 덮어써요 → `/채널설정` 같은 명령어로 다시
     넣거나, env secret으로 우회해요([[reference_akgui_channel_settings_location]])

## 쓰는 법

    python scripts/backup_volume.py          # 백업
    python scripts/backup_volume.py --list   # 지금까지 뜬 것
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ_DIR = os.path.dirname(BOT_DIR)
BACKUP_ROOT = os.path.join(PROJ_DIR, "backups")
KST = datetime.timezone(datetime.timedelta(hours=9))
APP = "akgui-bot"

# 🚨 **쿠키는 여기 넣지 마세요** (위 docstring 참고).
TARGETS = [
    "settings.json",
    "riot_accounts.json",
    "rank_stats.json",
    "valorant_wishlist.json",
    "dynamic_rooms.json",
    "team_sessions.json",
]
NEVER = {"riot_sessions.json"}      # 라이엇 쿠키 — 받지 않아요

FLYCTL_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), ".fly", "bin", "flyctl.exe"),
    r"C:\Program Files\flyctl\flyctl.exe",
    "flyctl",
]


def find_flyctl() -> str | None:
    for path in FLYCTL_CANDIDATES:
        if path == "flyctl":
            return path          # PATH에 있기를 기대해요
        if os.path.exists(path):
            return path
    return None


def fly_token() -> str | None:
    """`flyctl`이 "no access token available"로 죽는 세션이 있어요 — config에서 읽어
    `FLY_API_TOKEN`으로 넘겨요(재로그인 불필요)."""
    cfg = os.path.join(os.path.expanduser("~"), ".fly", "config.yml")
    if not os.path.exists(cfg):
        return None
    import re
    text = open(cfg, encoding="utf-8").read()
    m = re.search(r"access_token:\s*(\S+)", text)
    return m.group(1) if m else None


def do_backup() -> int:
    fly = find_flyctl()
    if fly is None:
        print("❌ flyctl.exe를 못 찾았어요 — FLYCTL_CANDIDATES에 경로를 추가하세요")
        return 1
    env = dict(os.environ)
    tok = fly_token()
    if tok:
        env["FLY_API_TOKEN"] = tok

    stamp = datetime.datetime.now(KST).strftime("%Y%m%d_%H%M")
    out_dir = os.path.join(BACKUP_ROOT, f"volume_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    print(f"🗄️ Fly 볼륨 /app/data → {out_dir}")

    got, missing, failed = [], [], []
    for name in TARGETS:
        if name in NEVER:                 # 방어 — 실수로 목록에 들어가도 막아요
            print(f"  🚫 {name}: 쿠키라 백업하지 않아요")
            continue
        dst = os.path.join(out_dir, name)
        proc = subprocess.run(
            [fly, "sftp", "get", f"/app/data/{name}", dst, "-a", APP],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=180,
        )
        blob = (proc.stdout or "") + (proc.stderr or "")
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            size = os.path.getsize(dst)
            got.append((name, size))
            print(f"  ✅ {name:24} {size:>7}바이트")
        elif "does not exist" in blob:
            missing.append(name)
            print(f"  ⚪ {name:24} 없음 (정상일 수 있어요 — 옛 형식 파일)")
            if os.path.exists(dst):
                os.remove(dst)
        else:
            failed.append((name, blob.strip()[:120]))
            print(f"  ❌ {name:24} 실패: {blob.strip()[:90]}")
            if os.path.exists(dst):
                os.remove(dst)

    # 🚨 받은 JSON을 **다시 읽어** 깨지지 않았는지 본다 ("떴다"로 끝내지 않는다)
    broken = []
    for name, _ in got:
        try:
            with open(os.path.join(out_dir, name), encoding="utf-8") as f:
                json.load(f)
        except Exception as exc:                       # noqa: BLE001
            broken.append((name, type(exc).__name__))

    meta = {
        "when_kst": datetime.datetime.now(KST).isoformat(),
        "app": APP,
        "got": {n: s for n, s in got},
        "missing": missing,
        "failed": [n for n, _ in failed],
        "skipped_cookies": sorted(NEVER),
    }
    with open(os.path.join(out_dir, "_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    print(f"\n  받음 {len(got)}개 · 없음 {len(missing)}개 · 실패 {len(failed)}개")
    if broken:
        print("❌ JSON이 깨진 파일:")
        for n, e in broken:
            print(f"  - {n} ({e})")
        return 1
    if failed:
        print("❌ 받지 못한 파일이 있어요:")
        for n, why in failed:
            print(f"  - {n}: {why}")
        return 1
    if not got:
        print("❌ 하나도 못 받았어요 — flyctl 인증이나 앱 이름을 확인하세요")
        return 1
    print("✅ 전부 받고 JSON 파싱까지 확인")
    print("🚨 `riot_sessions.json`(쿠키)은 일부러 제외했어요 — 위 docstring 참고")
    _prune()
    return 0


KEEP = 14      # 볼륨 파일은 작아서(합쳐 ~5KB) 넉넉히 둬도 돼요


def _prune(keep: int = KEEP, dry: bool = False) -> None:
    """🚨 `volume_` 로 시작하고 `_meta.json`이 있는 폴더만 지워요
    (손으로 만든 백업은 건드리지 않아요 — `backup_db.py`와 같은 규칙)."""
    if not os.path.isdir(BACKUP_ROOT):
        return
    mine = sorted(
        n for n in os.listdir(BACKUP_ROOT)
        if n.startswith("volume_")
        and os.path.isdir(os.path.join(BACKUP_ROOT, n))
        and os.path.exists(os.path.join(BACKUP_ROOT, n, "_meta.json"))
    )
    old = mine[:len(mine) - keep] if len(mine) > keep else []
    print(f"\n🧹 볼륨 백업 {len(mine)}개 · 유지 {keep}개 · 지울 것 {len(old)}개")
    for name in old:
        if dry:
            print(f"  (지울 예정) {name}")
            continue
        import shutil
        shutil.rmtree(os.path.join(BACKUP_ROOT, name))
        print(f"  🗑️ {name}")


def do_list() -> int:
    if not os.path.isdir(BACKUP_ROOT):
        print("backups 폴더가 없어요")
        return 0
    rows = []
    for name in sorted(os.listdir(BACKUP_ROOT)):
        meta_path = os.path.join(BACKUP_ROOT, name, "_meta.json")
        if not name.startswith("volume_") or not os.path.exists(meta_path):
            continue
        with open(meta_path, encoding="utf-8") as f:
            m = json.load(f)
        rows.append((m["when_kst"][:16], name, len(m.get("got", {}))))
    print(f"볼륨 백업 {len(rows)}개:")
    for when, name, n in rows:
        print(f"  {when}  {name:28} 파일 {n}개")
    if rows:
        newest = max(r[0] for r in rows)
        age = (datetime.datetime.now(KST)
               - datetime.datetime.fromisoformat(newest).replace(tzinfo=KST)).days
        print(f"\n  가장 최근: {newest} ({age}일 전)"
              + ("  🚨 오래됐어요" if age > 7 else ""))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="지금까지 뜬 볼륨 백업 보기")
    ap.add_argument("--prune", action="store_true", help="오래된 것 정리")
    ap.add_argument("--dry", action="store_true", help="--prune 미리보기")
    args = ap.parse_args()
    if args.list:
        sys.exit(do_list())
    if args.prune:
        _prune(dry=args.dry)
        sys.exit(0)
    sys.exit(do_backup())
