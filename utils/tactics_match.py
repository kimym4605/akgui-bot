"""🎬 전술판 — 실제 경기의 한 라운드를 장면으로 (2026-11-25, 사용자 요청 5번).

HenrikDev v3 경기 자료의 `kills[]`에는 **킬이 난 순간 살아 있던 사람 전원의 위치와 시선**
(`player_locations_on_kill`)이 들어 있어요. 라운드 하나를 고르면 킬마다 장면 하나로 만들어서,
그 위에 스킬·화살표·메모를 그려 "이때 여기 연막을 썼어야" 같은 피드백을 할 수 있어요.

- 좌표는 `tactics.to_uv`(게임 좌표 → 미니맵 0~1) 그대로. 2026-11-25에 실제 경기 킬 146건 중 145건에서
  처치자의 시선이 피해자 쪽을 향하는 걸로 확인한 식이에요(시선 방향 = (sin r, −cos r)).
- 죽은 사람은 `player_locations_on_kill`에 없어요 → `victim_death_location`에 `dead` 표시로 놓아요.
- 경기 자료는 한 판에 1MB쯤이라 **필요한 것만 뽑아** 들고 있어요(`summarize`).
- 🚨 공격/수비는 그 라운드에 스파이크를 설치한 팀으로 알아내요. 설치가 없던 라운드는 가장 가까운
  라운드를 따라가서, 전·후반이 바뀌는 바로 그 라운드에서는 틀릴 수 있어요(화면 부제에만 쓰여요).
"""
from __future__ import annotations

from utils import tactics

MAX_KILL_SCENES = tactics.MAX_SCENES
MODE_KO = {"Competitive": "경쟁", "Unrated": "일반", "Swiftplay": "신속", "Premier": "프리미어",
           "Custom Game": "사용자 설정", "Spike Rush": "스파이크 돌격"}
END_KO = {"Eliminated": "전멸", "Bomb defused": "해체", "Bomb detonated": "폭발", "Round timer expired": "시간 종료"}


def _xy(loc) -> list[int] | None:
    if not isinstance(loc, dict) or "x" not in loc or "y" not in loc:
        return None
    return [loc["x"], loc["y"]]


def summarize(match: dict, name: str, tag: str) -> dict | None:
    """경기 하나에서 장면 만들 때 필요한 것만 뽑아요. 내 계정이 없거나 킬 위치가 없으면 None."""
    md = match.get("metadata") or {}
    players = (match.get("players") or {}).get("all_players") or []
    me = next((p for p in players
               if (p.get("name") or "").lower() == name.lower() and (p.get("tag") or "").lower() == tag.lower()), None)
    kills = match.get("kills") or []
    raw_rounds = match.get("rounds") or []
    if me is None or not kills or not raw_rounds:
        return None
    people = {p["puuid"]: {"team": p.get("team"), "agent": p.get("character") or ""}
              for p in players if p.get("puuid")}
    rounds = []
    for r in raw_rounds:
        pe = r.get("plant_events") or {}
        rounds.append({"win": r.get("winning_team"), "end": r.get("end_type"), "site": pe.get("plant_site"),
                       "plant": _xy(pe.get("plant_location")), "plant_t": pe.get("plant_time_in_round") or 0,
                       "planter": (pe.get("planted_by") or {}).get("team"), "kills": []})
    for k in kills:
        ri = k.get("round")
        vl = _xy(k.get("victim_death_location"))
        if not isinstance(ri, int) or not 0 <= ri < len(rounds) or vl is None:
            continue
        locs = []
        for p in k.get("player_locations_on_kill") or []:
            xy = _xy(p.get("location"))
            if xy and p.get("player_puuid"):
                locs.append([p["player_puuid"], xy[0], xy[1], p.get("view_radians") or 0])
        rounds[ri]["kills"].append({"t": k.get("kill_time_in_round") or 0, "k": k.get("killer_puuid"),
                                    "v": k.get("victim_puuid"), "vl": vl, "locs": locs})
    for r in rounds:
        r["kills"].sort(key=lambda x: x["t"])
    team = me.get("team")
    mine = ((match.get("teams") or {}).get((team or "").lower()) or {})
    return {"id": md.get("matchid"), "map": md.get("map") or "", "mode": md.get("mode") or "",
            "start": md.get("game_start") or 0, "me": me["puuid"], "team": team, "agent": me.get("character") or "",
            "won": bool(mine.get("has_won")), "score": (mine.get("rounds_won") or 0, mine.get("rounds_lost") or 0),
            "players": people, "rounds": rounds}


def attacker_team(summary: dict, ri: int) -> str | None:
    """그 라운드의 공격팀('Red'/'Blue'). 설치한 팀 → 없으면 가장 가까운 라운드의 설치 팀."""
    rounds = summary["rounds"]
    best = None
    for i, r in enumerate(rounds):
        if r.get("planter") and (best is None or abs(i - ri) < abs(best - ri)):
            best = i
    return rounds[best]["planter"] if best is not None else None


def round_stats(summary: dict, ri: int) -> dict:
    """라운드 고르기 목록에 쓸 한 줄 값."""
    r = summary["rounds"][ri]
    me = summary["me"]
    return {"won": r.get("win") == summary["team"], "end": END_KO.get(r.get("end") or "", r.get("end") or ""),
            "site": r.get("site"), "kills": len(r["kills"]),
            "my_kills": sum(1 for k in r["kills"] if k["k"] == me),
            "died": any(k["v"] == me for k in r["kills"])}


def _clock(ms: int) -> str:
    s = max(0, int(ms) // 1000)
    return f"{s // 60}:{s % 60:02d}"


def round_scenes(summary: dict, ri: int, mapinfo: dict, agents: list[dict]) -> tuple[dict, str] | None:
    """라운드 하나 → (판 자료, 'atk'|'def'). 킬마다 장면 하나(10개까지). 만들 게 없으면 None."""
    rounds = summary["rounds"]
    if not 0 <= ri < len(rounds) or not rounds[ri]["kills"]:
        return None
    r = rounds[ri]
    by_en = {(a.get("en") or "").lower(): a for a in agents}
    people = summary["players"]
    my_team = summary["team"]

    def rel(team) -> str:
        return "ally" if team == my_team else "enemy"

    def agent_of(puuid):
        p = people.get(puuid) or {}
        return by_en.get((p.get("agent") or "").lower()), p

    scenes = []
    for k in r["kills"][:MAX_KILL_SCENES]:
        items = []
        killer_uv = None
        for puuid, x, y, rot in k["locs"]:
            a, p = agent_of(puuid)
            if a is None:
                continue
            u, v = tactics.to_uv(mapinfo, {"x": x, "y": y})
            it = {"type": "agent", "id": tactics.new_id(), "agent": a["id"], "team": rel(p.get("team")),
                  "u": u, "v": v, "rot": rot}
            if puuid == summary["me"]:
                it["me"] = True
            if puuid == k["k"]:
                killer_uv = (u, v)
            items.append(it)
        va, vp = agent_of(k["v"])
        vu, vv = tactics.to_uv(mapinfo, {"x": k["vl"][0], "y": k["vl"][1]})
        if va is not None:
            it = {"type": "agent", "id": tactics.new_id(), "agent": va["id"], "team": rel(vp.get("team")),
                  "u": vu, "v": vv, "dead": True}
            if k["v"] == summary["me"]:
                it["me"] = True
            items.append(it)
        ka, kp = agent_of(k["k"])
        if killer_uv is not None and (killer_uv[0], killer_uv[1]) != (vu, vv):
            items.append({"type": "arrow", "id": tactics.new_id(), "team": rel(kp.get("team")),
                          "u": killer_uv[0], "v": killer_uv[1], "u2": vu, "v2": vv})
        if r.get("plant") and r.get("plant_t") and k["t"] >= r["plant_t"]:
            pu, pv = tactics.to_uv(mapinfo, {"x": r["plant"][0], "y": r["plant"][1]})
            items.append({"type": "text", "id": tactics.new_id(), "team": rel(r.get("planter")),
                          "u": pu, "v": pv, "text": "스파이크"})
        who = f"{(ka or {}).get('name') or '?'}→{(va or {}).get('name') or '?'}"
        scenes.append({"sid": tactics.new_id(), "title": f"{_clock(k['t'])} {who}"[:tactics.MAX_TITLE],
                       "items": items})
    atk = attacker_team(summary, ri)
    side = "def" if atk and atk != my_team else "atk"
    data = tactics.clean_data({"scenes": scenes, "side": side})
    if data is None:
        return None
    return data, side
