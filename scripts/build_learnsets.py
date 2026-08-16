"""1회성(및 재개 가능) 스크립트: PokeAPI에서 1~251번(1세대+2세대) 포켓몬의
기술표, 특성, 타입, 종족값, 진화 계보(+진화 트리거: 레벨/돌), 도감번호를 받아와서 data/ 폴더에 캐싱해요.

10마리마다 중간 저장하고, 이미 저장된 포켓몬은 건너뛰기 때문에
중간에 끊겨도 다음 실행 때 이어서 진행돼요.

포켓몬 한글 이름은 하드코딩 목록에 의존하지 않고, 매번 PokeAPI에서 직접 조회해요.

진화 계보의 각 단계는 이제 단순 레벨 숫자가 아니라
{"trigger": "level"|"stone", "level": int|None, "item": str|None} 형태로 저장돼요.
- 레벨업으로 진화하면 trigger="level", level=그 레벨
- 돌(불꽃돌/물의돌/번개돌/잎의돌/달의돌)로 진화하면 trigger="stone", item=그 돌 한글명
- 교환/친밀도 등 이 시스템에 없는 조건이면 레벨 30짜리 레벨업으로 대체해요

생성되는 파일:
    data/learnsets.json  -> {"이상해씨": {"1": [...], "7": [...]}, ...}
    data/moves.json       -> {"몸통박치기": {"type":.., "power":.., ...}, ...}
    data/abilities.json   -> {"파이리": {"normal": [...], "hidden": str|None}, ...}
    data/species.json     -> {"파이리": {"types": [...], "baseStats": {...}}, ...}
    data/evolution.json   -> {"파이리": {"family": [...], "evolutions": [{"trigger":..,"level":..,"item":..}, ...]}, ...}
    data/name_to_id.json  -> {"파이리": 4, ...}
"""
import asyncio
import json
import os
import re
import sys

import aiohttp

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LEARNSETS_PATH = os.path.join(OUTPUT_DIR, "learnsets.json")
MOVES_PATH = os.path.join(OUTPUT_DIR, "moves.json")
ABILITIES_PATH = os.path.join(OUTPUT_DIR, "abilities.json")
SPECIES_PATH = os.path.join(OUTPUT_DIR, "species.json")
EVOLUTION_PATH = os.path.join(OUTPUT_DIR, "evolution.json")
NAME_TO_ID_PATH = os.path.join(OUTPUT_DIR, "name_to_id.json")

VERSION_GROUPS = ("red-blue", "yellow", "gold-silver", "crystal")
TYPE_KO = {
    "normal": "노말", "fire": "불꽃", "water": "물", "electric": "전기", "grass": "풀",
    "ice": "얼음", "fighting": "격투", "poison": "독", "ground": "땅", "flying": "비행",
    "psychic": "에스퍼", "bug": "벌레", "rock": "바위", "ghost": "고스트", "dragon": "용",
    "dark": "악", "steel": "강철", "fairy": "페어리",
}
CATEGORY_KO = {"physical": "물리", "special": "특수", "status": "변화"}
STAT_NAME_MAP = {
    "hp": "hp", "attack": "attack", "defense": "defense",
    "special-attack": "spAttack", "special-defense": "spDefense", "speed": "speed",
}
ITEM_KO = {
    "fire-stone": "불꽃돌",
    "water-stone": "물의돌",
    "thunder-stone": "번개돌",
    "leaf-stone": "잎의돌",
    "moon-stone": "달의돌",
}

MAX_DEX_ID = 251


async def fetch_json(session: aiohttp.ClientSession, url: str) -> dict:
    timeout = aiohttp.ClientTimeout(total=10)
    async with session.get(url, timeout=timeout) as resp:
        resp.raise_for_status()
        return await resp.json()


async def fetch_ko_name(session: aiohttp.ClientSession, url: str, cache: dict) -> str:
    if url in cache:
        return cache[url]
    data = await fetch_json(session, url)
    ko = next((n["name"] for n in data["names"] if n["language"]["name"] == "ko"), data["name"])
    cache[url] = ko
    return ko


async def fetch_species_name(session: aiohttp.ClientSession, dex_id: int, cache: dict) -> str:
    return await fetch_ko_name(session, f"https://pokeapi.co/api/v2/pokemon-species/{dex_id}/", cache)


async def fetch_move_info(session: aiohttp.ClientSession, move_url: str, cache: dict) -> dict:
    if move_url in cache:
        return cache[move_url]
    data = await fetch_json(session, move_url)
    ko_name = next((n["name"] for n in data["names"] if n["language"]["name"] == "ko"), data["name"])
    info = {
        "name_ko": ko_name,
        "type": TYPE_KO.get(data["type"]["name"], data["type"]["name"]),
        "power": data["power"] or 0,
        "accuracy": data["accuracy"] or 100,
        "category": CATEGORY_KO.get(data["damage_class"]["name"], "변화"),
        "pp": data["pp"] or 0,
    }
    cache[move_url] = info
    return info


async def fetch_pokemon(session: aiohttp.ClientSession, dex_id: int, move_cache: dict, ability_cache: dict):
    data = await fetch_json(session, f"https://pokeapi.co/api/v2/pokemon/{dex_id}")

    by_level: dict[int, list[str]] = {}
    for entry in data["moves"]:
        matched = None
        for detail in entry["version_group_details"]:
            if detail["move_learn_method"]["name"] != "level-up":
                continue
            if detail["version_group"]["name"] not in VERSION_GROUPS:
                continue
            if detail["level_learned_at"] == 0:
                continue
            matched = detail["level_learned_at"]
            break
        if matched is None:
            continue
        move_info = await fetch_move_info(session, entry["move"]["url"], move_cache)
        by_level.setdefault(matched, [])
        if move_info["name_ko"] not in by_level[matched]:
            by_level[matched].append(move_info["name_ko"])
    learnset = {str(lvl): moves for lvl, moves in sorted(by_level.items())}

    normal_abilities, hidden_ability = [], None
    for entry in data["abilities"]:
        ko_name = await fetch_ko_name(session, entry["ability"]["url"], ability_cache)
        if entry["is_hidden"]:
            hidden_ability = ko_name
        elif ko_name not in normal_abilities:
            normal_abilities.append(ko_name)

    types = [TYPE_KO.get(t["type"]["name"], t["type"]["name"]) for t in data["types"]]

    base_stats = {}
    for s in data["stats"]:
        key = STAT_NAME_MAP.get(s["stat"]["name"])
        if key:
            base_stats[key] = s["base_stat"]

    return {
        "learnset": learnset,
        "abilities": {"normal": normal_abilities, "hidden": hidden_ability},
        "types": types,
        "baseStats": base_stats,
        "species_url": data["species"]["url"],
    }


def _extract_evolution_info(evolution_details_list) -> dict:
    """진화 조건을 {"trigger": "level"|"stone", "level":.., "item":..} 형태로 뽑아내요.
    레벨업 조건을 최우선으로 찾고, 없으면 지원하는 돌 조건을 찾고,
    둘 다 없으면(교환/친밀도 등) 레벨 30짜리 레벨업으로 대체해요."""
    for d in evolution_details_list:
        trigger = (d.get("trigger") or {}).get("name")
        if trigger == "level-up" and d.get("min_level"):
            return {"trigger": "level", "level": d["min_level"], "item": None}

    for d in evolution_details_list:
        trigger = (d.get("trigger") or {}).get("name")
        item = d.get("item")
        if trigger == "use-item" and item and item["name"] in ITEM_KO:
            return {"trigger": "stone", "level": None, "item": ITEM_KO[item["name"]]}

    return {"trigger": "level", "level": 30, "item": None}


def _extract_species_id(species_url: str):
    match = re.search(r"/pokemon-species/(\d+)/", species_url)
    return int(match.group(1)) if match else None


async def fetch_evolution_family(session: aiohttp.ClientSession, species_url: str, name_cache: dict, chain_cache: dict, name_to_id: dict):
    """해당 종의 진화 계보를 API에서 가져와요.
    1~251번(1+2세대) 범위 밖의 포켓몬은 체인 앞뒤 어디에 있든 걸러내고 그 구간만 남겨요.
    분기 진화(이브이, 요가랑 등)는 첫 번째 갈래만 따라가요 (별도 하드코딩으로 보정해요)."""
    species_data = await fetch_json(session, species_url)
    chain_url = species_data["evolution_chain"]["url"]

    if chain_url in chain_cache:
        return chain_cache[chain_url]

    chain_data = await fetch_json(session, chain_url)
    root_link = chain_data["chain"]

    raw_names: list[str] = []
    raw_ids: list[int | None] = []
    raw_evolutions: list[dict] = []

    cur = root_link
    while True:
        link_species_url = cur["species"]["url"]
        name_ko = await fetch_ko_name(session, link_species_url, name_cache)
        dex_id = _extract_species_id(link_species_url)
        raw_names.append(name_ko)
        raw_ids.append(dex_id)
        if dex_id:
            name_to_id[name_ko] = dex_id

        if not cur["evolves_to"]:
            break
        evo = cur["evolves_to"][0]
        raw_evolutions.append(_extract_evolution_info(evo["evolution_details"]))
        cur = evo

    kept_indices = [i for i, dex_id in enumerate(raw_ids) if dex_id and 1 <= dex_id <= MAX_DEX_ID]

    if not kept_indices:
        family = raw_names
        evolutions = raw_evolutions
    else:
        start_idx, end_idx = kept_indices[0], kept_indices[-1]
        family = raw_names[start_idx:end_idx + 1]
        evolutions = raw_evolutions[start_idx:end_idx]

    result = {"family": family, "evolutions": evolutions}
    chain_cache[chain_url] = result
    return result


def _load_existing(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _name_registered(evolution_db: dict, name: str) -> bool:
    for data in evolution_db.values():
        if name in data.get("family", []):
            return True
    return False


def _purge_stale_entries(learnsets, abilities_db, species_db, evolution_db, name_to_id, valid_names: set):
    learnsets_clean = {k: v for k, v in learnsets.items() if k in valid_names}
    abilities_clean = {k: v for k, v in abilities_db.items() if k in valid_names}
    species_clean = {k: v for k, v in species_db.items() if k in valid_names}

    evolution_clean = {}
    for base_name, data in evolution_db.items():
        if base_name not in valid_names:
            continue
        family = [n for n in data.get("family", []) if n in valid_names]
        if not family:
            continue
        evolutions = data.get("evolutions", [])[: max(0, len(family) - 1)]
        evolution_clean[base_name] = {"family": family, "evolutions": evolutions}

    name_to_id_clean = {k: v for k, v in name_to_id.items() if k in valid_names}

    return learnsets_clean, abilities_clean, species_clean, evolution_clean, name_to_id_clean


def _save_all(learnsets, move_cache, abilities_db, species_db, evolution_db, name_to_id):
    moves_db_existing = _load_existing(MOVES_PATH)
    moves_db_new = {
        info["name_ko"]: {
            "type": info["type"], "power": info["power"], "accuracy": info["accuracy"],
            "category": info["category"], "pp": info["pp"],
        }
        for info in move_cache.values()
    }
    moves_db = {**moves_db_existing, **moves_db_new}

    with open(LEARNSETS_PATH, "w", encoding="utf-8") as f:
        json.dump(learnsets, f, ensure_ascii=False, indent=2)
    with open(MOVES_PATH, "w", encoding="utf-8") as f:
        json.dump(moves_db, f, ensure_ascii=False, indent=2)
    with open(ABILITIES_PATH, "w", encoding="utf-8") as f:
        json.dump(abilities_db, f, ensure_ascii=False, indent=2)
    with open(SPECIES_PATH, "w", encoding="utf-8") as f:
        json.dump(species_db, f, ensure_ascii=False, indent=2)
    with open(EVOLUTION_PATH, "w", encoding="utf-8") as f:
        json.dump(evolution_db, f, ensure_ascii=False, indent=2)
    with open(NAME_TO_ID_PATH, "w", encoding="utf-8") as f:
        json.dump(name_to_id, f, ensure_ascii=False, indent=2)


async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    learnsets = _load_existing(LEARNSETS_PATH)
    abilities_db = _load_existing(ABILITIES_PATH)
    species_db = _load_existing(SPECIES_PATH)
    evolution_db = _load_existing(EVOLUTION_PATH)
    name_to_id = _load_existing(NAME_TO_ID_PATH)
    move_cache, ability_cache, name_cache, chain_cache = {}, {}, {}, {}

    valid_names: set[str] = set()

    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(connector=connector) as session:
        for dex_id in range(1, MAX_DEX_ID + 1):
            try:
                name = await asyncio.wait_for(fetch_species_name(session, dex_id, name_cache), timeout=10)
            except Exception as e:
                print(f"[{dex_id}/{MAX_DEX_ID}] 이름 조회 실패: {e}", flush=True)
                continue

            valid_names.add(name)
            name_to_id.setdefault(name, dex_id)

            if name in learnsets and name in species_db and _name_registered(evolution_db, name):
                print(f"[{dex_id}/{MAX_DEX_ID}] {name} 이미 있음, 건너뜀", flush=True)
                continue

            print(f"[{dex_id}/{MAX_DEX_ID}] {name} 수집 중...", flush=True)
            try:
                info = await asyncio.wait_for(
                    fetch_pokemon(session, dex_id, move_cache, ability_cache), timeout=15
                )
                learnsets[name] = info["learnset"]
                abilities_db[name] = info["abilities"]
                species_db[name] = {"types": info["types"], "baseStats": info["baseStats"]}

                evo = await asyncio.wait_for(
                    fetch_evolution_family(session, info["species_url"], name_cache, chain_cache, name_to_id),
                    timeout=15,
                )
                base_name = evo["family"][0]
                evolution_db[base_name] = evo
                valid_names.update(evo["family"])
            except Exception as e:
                print(f"  ! {name} 실패: {e}", flush=True)

            if dex_id % 10 == 0:
                _save_all(learnsets, move_cache, abilities_db, species_db, evolution_db, name_to_id)
                print(f"  💾 {dex_id}마리까지 중간 저장 완료", flush=True)

            await asyncio.sleep(0.2)

    learnsets, abilities_db, species_db, evolution_db, name_to_id = _purge_stale_entries(
        learnsets, abilities_db, species_db, evolution_db, name_to_id, valid_names
    )
    _save_all(learnsets, move_cache, abilities_db, species_db, evolution_db, name_to_id)
    print(f"\n완료! 6개 파일 생성됐어요: learnsets/moves/abilities/species/evolution/name_to_id.json", flush=True)


if __name__ == "__main__":
    asyncio.run(main())