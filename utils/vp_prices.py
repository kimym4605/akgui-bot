"""
발로란트 VP 충전 팩 가격표와 "목표 VP를 채우는 가장 싼 조합" 계산기예요.
cogs/vp.py(/vp계산)가 써요.

⚠️ 가격은 코드에 박아두지 않고 `config/vp_prices.json`에서 읽어요. 라이엇이 가격을 바꾸거나
지역/이벤트에 따라 달라져도 봇 코드를 고칠 필요 없이 JSON만 바꾸면 되게 하려고요.
실제 돈이 오가는 숫자라, 값이 비어있으면 계산을 아예 안 하고 안내만 해요.

⚠️⚠️ `data/`가 아니라 `config/`에 두는 이유: Fly.io에서 `/app/data`는 볼륨이 마운트되는
경로라, 이미지에 넣어 배포한 파일이 볼륨 내용에 가려져서 서버에서는 안 보여요(2026-09-02에
실제로 확인함 - 볼륨에 없는 data/*.json은 프로덕션에 존재하지 않았음). 가격표는 유저가
쌓는 데이터가 아니라 코드와 같이 배포되는 정적 설정이니 볼륨 밖에 둬야 해요.

JSON 형식:
  {
    "currency": "원",
    "updated": "2026-09-02",          ← 이 가격표를 언제 확인했는지(안내에 같이 보여줘요)
    "packs": [ {"vp": 475, "price": 6500}, ... ]
  }
"""
import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DATA_FILE = CONFIG_DIR / "vp_prices.json"


def load() -> dict:
    """{"currency", "updated", "packs"} 를 돌려줘요. 파일이 없거나 깨졌으면 packs가 빈 목록."""
    if not DATA_FILE.exists():
        return {"currency": "원", "updated": "", "packs": []}
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"currency": "원", "updated": "", "packs": []}

    packs = []
    for entry in data.get("packs") or []:
        try:
            vp, price = int(entry["vp"]), int(entry["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if vp > 0 and price > 0:
            packs.append({"vp": vp, "price": price})

    packs.sort(key=lambda p: p["vp"])
    return {
        "currency": data.get("currency") or "원",
        "updated": data.get("updated") or "",
        "packs": packs,
    }


def is_configured() -> bool:
    return bool(load()["packs"])


def cheapest_combo(target_vp: int, packs: list[dict]) -> dict | None:
    """목표 VP **이상**을 만드는 조합 중 총 결제금액이 가장 싼 걸 찾아요.
    금액이 같으면 **VP를 더 많이 받는 쪽**을 골라요 — 남는 VP는 버려지는 게 아니라 계정에
    남아서 다음에 쓰니까, 같은 돈이면 많이 받는 게 이득이에요. (실제 가격표 기준으로
    1,775 VP 목표일 때 475×4=1,900VP 와 2,050×1 이 둘 다 26,000원인데, 후자가 150 VP를
    더 주고 결제도 한 번만 하면 돼요.)

    한 팩을 여러 번 살 수 있으니 무한 배낭(동전 교환) 문제예요. 목표보다 조금 넘겨서
    사는 게 더 쌀 수 있어서(예: 1,000 VP짜리 2개보다 2,050 VP짜리 1개가 쌈) dp를
    "정확히 v"가 아니라 "v 이상"으로 정의해요.

    돌려주는 값: {"cost", "vp", "leftover", "counts": {팩VP: 개수}}  못 찾으면 None.
    """
    if target_vp <= 0 or not packs:
        return None

    INF = float("inf")
    # dp[v] = v VP 이상을 확보하는 (최소 비용, -받는 총 VP)
    # 튜플 비교라 비용이 먼저, 같으면 -VP가 작은 쪽(=VP가 많은 쪽)이 이겨요.
    dp: list[tuple[float, int]] = [(INF, 0)] * (target_vp + 1)
    pick: list[dict | None] = [None] * (target_vp + 1)
    dp[0] = (0, 0)

    for v in range(1, target_vp + 1):
        for pack in packs:
            prev = max(0, v - pack["vp"])  # 팩이 목표를 넘겨버리면 prev=0(=여기서 끝)
            prev_cost, prev_neg_vp = dp[prev]
            if prev_cost == INF:
                continue
            candidate = (prev_cost + pack["price"], prev_neg_vp - pack["vp"])
            if candidate < dp[v]:
                dp[v] = candidate
                pick[v] = pack

    if dp[target_vp][0] == INF:
        return None

    counts: dict[int, int] = {}
    total_vp = 0
    v = target_vp
    while v > 0:
        pack = pick[v]
        if pack is None:  # 이론상 안 나오지만 무한루프 방지용이에요.
            return None
        counts[pack["vp"]] = counts.get(pack["vp"], 0) + 1
        total_vp += pack["vp"]
        v = max(0, v - pack["vp"])

    return {
        "cost": dp[target_vp][0],
        "vp": total_vp,
        "leftover": total_vp - target_vp,
        "counts": counts,
    }
