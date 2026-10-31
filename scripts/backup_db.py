# -*- coding: utf-8 -*-
"""🗄️ MongoDB 전체 백업 (2026-10-31 신설).

## 왜 필요한가

2026-10-31에 점검하니 **마지막 DB 백업이 9-30이었다**(31일 전 · 포켓몬 종료 때 뜬 것).
그 사이에 🎴카드 807장 · 🎣낚시 기록 · `coin_log` 3,375건 · 업적·칭호·음성레벨이
쌓였는데 **전부 무방비**였다. Atlas는 `hostInfo`가 차단된 **공유 티어**라 자동 백업이
없다 — 날아가면 복구 수단이 없다.

DB는 **2.11MB(문서 3,787건 · 27 컬렉션)**라 덤프가 몇 초다. 안 할 이유가 없다.

## 쓰는 법

    python scripts/backup_db.py              # 백업 뜨기
    python scripts/backup_db.py --list       # 지금까지 뜬 백업 보기
    python scripts/backup_db.py --verify <폴더>   # 그 백업을 다시 읽어 검증

## 🚨 주의

- 출력은 **레포 밖**(`악귀봇프로젝트/backups/`)에 쓴다. `coin_log`엔 유저 ID,
  `birthdays`엔 생일이 들어가서 **git에 들어가면 안 된다.**
- `_id`가 `ObjectId`·`datetime`인 문서가 있어서 그대로는 JSON이 안 된다 → 타입을
  적어서 저장하고(`{"$oid": ...}` 꼴) 복원 때 되살린다.
- 🚨 **"떴다"로 끝내지 말 것.** 이 스크립트는 쓰고 나서 **다시 읽어 문서 수를 대조**한다
  (응답 OK ≠ 저장됨 — [[feedback_response_ok_is_not_saved]]).
"""
import argparse
import datetime
import json
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ_DIR = os.path.dirname(BOT_DIR)
BACKUP_ROOT = os.path.join(PROJ_DIR, "backups")
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv                      # noqa: E402
load_dotenv(os.path.join(BOT_DIR, ".env"))

from bson import ObjectId                            # noqa: E402

from utils.pokemon_store import _db                  # noqa: E402

KST = datetime.timezone(datetime.timedelta(hours=9))


def encode(value):
    """JSON으로 못 가는 타입을 **되살릴 수 있게** 적어둬요."""
    if isinstance(value, ObjectId):
        return {"$oid": str(value)}
    if isinstance(value, datetime.datetime):
        return {"$date": value.isoformat()}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode(v) for v in value]
    return value


def decode(value):
    if isinstance(value, dict):
        if set(value) == {"$oid"}:
            return ObjectId(value["$oid"])
        if set(value) == {"$date"}:
            return datetime.datetime.fromisoformat(value["$date"])
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def do_backup() -> int:
    stamp = datetime.datetime.now(KST).strftime("%Y%m%d_%H%M")
    out_dir = os.path.join(BACKUP_ROOT, f"db_{_db.name}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    names = sorted(_db.list_collection_names())
    counts = {}
    total = 0
    print(f"🗄️ {_db.name} → {out_dir}")
    for name in names:
        docs = [encode(d) for d in _db[name].find({})]
        counts[name] = len(docs)
        total += len(docs)
        with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=1)
        print(f"  {name:22} {len(docs):>6}건")

    meta = {
        "db": _db.name,
        "when_kst": datetime.datetime.now(KST).isoformat(),
        "collections": counts,
        "total_docs": total,
    }
    with open(os.path.join(out_dir, "_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    # 🚨 **다시 읽어 대조한다** — "떴다"로 끝내지 않는다.
    bad = []
    for name, n in counts.items():
        with open(os.path.join(out_dir, f"{name}.json"), encoding="utf-8") as f:
            back = json.load(f)
        if len(back) != n:
            bad.append(f"{name}: 썼을 때 {n} · 다시 읽으니 {len(back)}")
        # 한 건을 실제로 복원해 본다 (타입 인코딩이 되살아나는지)
        if back:
            decode(back[0])
    size = sum(os.path.getsize(os.path.join(out_dir, f))
               for f in os.listdir(out_dir)) / 1024
    print(f"\n  문서 {total}건 · {len(names)}개 컬렉션 · {size:.0f}KB")
    if bad:
        print("❌ 대조 실패:")
        for b in bad:
            print("  -", b)
        return 1
    print("✅ 다시 읽어 대조까지 통과")
    print(f"\n🚨 이 폴더는 **레포 밖**이고 유저 ID·생일이 들어 있어요. git에 넣지 마세요.")
    # 🚨 정리를 **백업 성공 뒤에만** 한다. 앞에 두면 백업이 실패한 날 오래된 것까지
    #    지워져서 "새 백업도 없고 옛 백업도 없는" 상태가 된다.
    print()
    do_prune()
    return 0


def do_list() -> int:
    if not os.path.isdir(BACKUP_ROOT):
        print("backups 폴더가 없어요")
        return 0
    rows = []
    for name in sorted(os.listdir(BACKUP_ROOT)):
        path = os.path.join(BACKUP_ROOT, name)
        if not os.path.isdir(path):
            continue
        meta_path = os.path.join(path, "_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                m = json.load(f)
            rows.append((m.get("when_kst", "?")[:16], name,
                         f"{m.get('total_docs', '?')}건",
                         f"{len(m.get('collections', {}))}컬렉션"))
        else:
            rows.append(("(메타 없음)", name, "", ""))
    print(f"백업 {len(rows)}개:")
    for when, name, docs, cols in rows:
        print(f"  {when}  {name:38} {docs:>8} {cols}")
    if rows:
        newest = max(r[0] for r in rows if r[0] != "(메타 없음)") if any(
            r[0] != "(메타 없음)" for r in rows) else None
        if newest:
            age = (datetime.datetime.now(KST)
                   - datetime.datetime.fromisoformat(newest).replace(tzinfo=KST)).days
            mark = " 🚨 오래됐어요" if age > 7 else ""
            print(f"\n  가장 최근 DB 백업: {newest} ({age}일 전){mark}")
    return 0


def do_verify(folder: str) -> int:
    path = folder if os.path.isabs(folder) else os.path.join(BACKUP_ROOT, folder)
    meta_path = os.path.join(path, "_meta.json")
    if not os.path.exists(meta_path):
        print(f"❌ {path} 에 _meta.json이 없어요")
        return 1
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    print(f"백업: {meta['db']} · {meta['when_kst'][:16]} · {meta['total_docs']}건")
    bad = []
    for name, n in meta["collections"].items():
        p = os.path.join(path, f"{name}.json")
        if not os.path.exists(p):
            bad.append(f"{name}: 파일이 없어요")
            continue
        with open(p, encoding="utf-8") as f:
            docs = json.load(f)
        if len(docs) != n:
            bad.append(f"{name}: 메타 {n} · 파일 {len(docs)}")
        for d in docs[:3]:
            decode(d)          # 복원이 되는지
    print(f"  컬렉션 {len(meta['collections'])}개 검사")
    if bad:
        print("❌ 문제:")
        for b in bad:
            print("  -", b)
        return 1
    print("✅ 파일·건수·복원 전부 정상")
    return 0


def do_restore(folder: str, target_db: str, wipe: bool) -> int:
    """백업을 **다른 DB 이름으로** 되살려요.

    🚨🚨 **프로덕션 이름으로는 복원하지 않아요.** 사고가 났을 때 운영 DB에 직접 쏘면
       절반만 들어간 상태에서 터질 수 있어요. 먼저 임시 DB로 복원해 눈으로 확인한 뒤,
       Atlas 콘솔에서 이름을 바꾸거나 운영 설정을 그 DB로 돌리는 쪽이 안전해요.
    ⭐ **복원해보지 않은 백업은 백업이 아니에요.** 그래서 이 기능이 있어요 —
       `--restore <폴더> --to <임시DB이름>`으로 아무 때나 연습할 수 있어요."""
    path = folder if os.path.isabs(folder) else os.path.join(BACKUP_ROOT, folder)
    meta_path = os.path.join(path, "_meta.json")
    if not os.path.exists(meta_path):
        print(f"❌ {path} 에 _meta.json이 없어요")
        return 1
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    prod = meta["db"]
    if target_db == prod:
        print(f"❌ 운영 DB 이름(`{prod}`)으로는 복원하지 않아요. `--to` 에 임시 이름을 주세요.")
        print("   (먼저 임시 DB로 되살려 눈으로 확인한 뒤 운영 설정을 옮기세요)")
        return 1

    from utils.pokemon_store import _client
    target = _client[target_db]
    existing = target.list_collection_names()
    if existing and not wipe:
        print(f"❌ `{target_db}` 에 이미 컬렉션 {len(existing)}개가 있어요. "
              f"덮어쓰려면 --wipe 를 주세요.")
        return 1
    if existing and wipe:
        for name in existing:
            target[name].drop()
        print(f"  (기존 컬렉션 {len(existing)}개를 비웠어요)")

    print(f"🔁 {path}\n   → DB `{target_db}` (원본 `{prod}` · {meta['when_kst'][:16]})")
    restored = {}
    for name, n in meta["collections"].items():
        with open(os.path.join(path, f"{name}.json"), encoding="utf-8") as f:
            docs = [decode(d) for d in json.load(f)]
        if docs:
            target[name].insert_many(docs)
        restored[name] = target[name].count_documents({})
        mark = "" if restored[name] == n else f"  ❌ 기대 {n}"
        print(f"  {name:22} {restored[name]:>6}건{mark}")

    bad = [f"{k}: 기대 {v} · 실제 {restored.get(k)}"
           for k, v in meta["collections"].items() if restored.get(k) != v]
    total = sum(restored.values())
    print(f"\n  복원 {total}건 / 백업 {meta['total_docs']}건")
    if bad:
        print("❌ 건수가 안 맞아요:")
        for b in bad:
            print("  -", b)
        return 1
    print("✅ 전 컬렉션 건수 일치 — **이 백업은 되살릴 수 있어요**")
    print(f"\n🧹 연습이었으면 지워주세요: python scripts/backup_db.py --drop {target_db}")
    return 0


KEEP_BACKUPS = 30          # 매일 돌리면 한 달. 하나가 ~730KB라 30개도 22MB뿐이에요.


def do_prune(keep: int = KEEP_BACKUPS, dry: bool = False) -> int:
    """오래된 DB 백업을 지워요. **이 스크립트가 뜬 것만** 건드려요.

    🚨 `db_` 로 시작하고 `_meta.json`이 있는 폴더만 지워요. 손으로 만든
       `pokemon_game_full_20260930`·`channel_snapshot_*` 같은 건 **절대 안 건드려요**
       (그게 유일본일 수 있어요)."""
    if not os.path.isdir(BACKUP_ROOT):
        return 0
    mine = []
    for name in os.listdir(BACKUP_ROOT):
        path = os.path.join(BACKUP_ROOT, name)
        if not os.path.isdir(path) or not name.startswith("db_"):
            continue
        if not os.path.exists(os.path.join(path, "_meta.json")):
            continue        # 우리가 뜬 게 아니면 건드리지 않아요
        mine.append(name)
    mine.sort()             # 이름에 stamp가 들어 있어 사전순 = 시간순
    # 🚨 `mine[:-keep]`만 쓰면 keep=0에서 **아무것도 안 지운다** — 파이썬에서 `-0 == 0`
    #    이라 `[:-0]`이 `[:0]`(빈 리스트)이 된다. 역방향 확인이 그래서 한 번 무효가 됐다.
    old = mine[:len(mine) - keep] if len(mine) > keep else []
    print(f"🧹 자동 백업 {len(mine)}개 · 유지 {keep}개 · 지울 것 {len(old)}개")
    for name in old:
        path = os.path.join(BACKUP_ROOT, name)
        if dry:
            print(f"  (지울 예정) {name}")
            continue
        import shutil
        shutil.rmtree(path)
        print(f"  🗑️ {name}")
    return 0


def do_drop(target_db: str) -> int:
    """연습용으로 만든 DB를 지워요. 🚨 운영 이름은 거부해요."""
    from utils.pokemon_store import _client, MONGODB_DB_NAME
    if target_db == MONGODB_DB_NAME:
        print(f"❌ 운영 DB(`{target_db}`)는 지울 수 없어요.")
        return 1
    _client.drop_database(target_db)
    print(f"🧹 `{target_db}` 삭제")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="지금까지 뜬 백업 보기")
    ap.add_argument("--verify", metavar="폴더", help="그 백업을 다시 읽어 검증")
    ap.add_argument("--restore", metavar="폴더", help="백업을 되살려요 (--to 필요)")
    ap.add_argument("--to", metavar="DB이름", help="복원할 DB 이름 (운영 이름은 거부)")
    ap.add_argument("--wipe", action="store_true", help="--to 의 기존 컬렉션을 비우고 복원")
    ap.add_argument("--drop", metavar="DB이름", help="연습용 DB 삭제")
    ap.add_argument("--prune", action="store_true",
                    help=f"오래된 자동 백업 정리 (최근 {KEEP_BACKUPS}개만 남겨요)")
    ap.add_argument("--dry", action="store_true", help="--prune 미리보기")
    args = ap.parse_args()
    if args.prune:
        sys.exit(do_prune(dry=args.dry))
    if args.list:
        sys.exit(do_list())
    if args.verify:
        sys.exit(do_verify(args.verify))
    if args.drop:
        sys.exit(do_drop(args.drop))
    if args.restore:
        if not args.to:
            print("❌ `--to <임시DB이름>` 을 같이 주세요 (운영 이름은 거부돼요)")
            sys.exit(1)
        sys.exit(do_restore(args.restore, args.to, args.wipe))
    sys.exit(do_backup())
