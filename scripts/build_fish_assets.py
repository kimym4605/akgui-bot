# -*- coding: utf-8 -*-
"""🐟 Higgsfield로 뽑은 물고기 그림 → `assets/fish/<key>.webp` (512×512, 배경 투명).

    python scripts/build_fish_assets.py <원본 png 폴더>      # f01.png … f34.png

원본은 **단색 밝은 회색 배경**이에요(프롬프트로 고정). 디스코드는 어두운 화면이라 배경을
빼야 하는데, 그림에 **빛 번짐(오라)과 휘어진 몸 안쪽 빈 공간**이 있어서 단순히 "테두리에서
이어진 배경만 지우기"로는 안 돼요 — 2026-11-22 첫 판에서 황금잉어·악귀어 안쪽이 **흰 덩어리**로
남았고 오라가 허옇게 떴어요. 그래서:

1. 테두리 픽셀의 중앙값 = 배경색. 픽셀마다 배경색과의 거리(`dist`)를 재요.
2. **부드러운 구역** = 배경과 가까운(`dist < T1`) 픽셀 중
   ⒜ 테두리에서 이어진 것(바깥 배경 + 거기 닿은 빛 번짐), 그리고
   ⒝ 안쪽에 갇혀 있지만 **진짜 배경색 픽셀이 많이 섞인** 덩어리(= 휘어진 몸 사이 빈 공간).
   🚨 ⒝의 조건(`POCKET_*`)이 없으면 은어 같은 **은빛 몸통**이 통째로 뚫려요. 몸통은 배경과
      비슷해도 명암이 있어서 "진짜 배경색" 픽셀 비율이 낮아요. 그걸로 갈라요.
3. 부드러운 구역 안에서는 `dist`에 비례해 **반투명**으로 만들고(배경색이면 0, 멀수록 진하게),
   색에서 배경색 몫을 빼요(un-premultiply) → 오라가 어두운 화면에서도 빛처럼 보여요.
   구역 밖(= 굵은 선 안쪽의 물고기)은 전부 불투명이에요.
4. 먼지 같은 아주 작은 조각(`MIN_BLOB`)은 지워요. 금화·불티 같은 이펙트는 남겨요.
5. 물고기에 딱 맞게 잘라 정사각형 가운데에 다시 앉혀요.

📁 원본(1024px PNG)은 저장소에 없어요(24장 ≈ 25MB). 상위 폴더 `악귀봇프로젝트\물고기그림\`에
   `<등급>_<이름>.png`로 보관해요 — 다시 뽑을 땐 `<key>.png`로 이름을 바꿔 한 폴더에 모아 돌려요.
   화풍: Higgsfield Nano Banana 2, "애니 몬스터" 프롬프트 + 첫 악귀어 그림을 스타일 참고로.
⚠️ numpy·scipy 없이 Pillow만 써요 — 로컬 윈도우에 둘 다 없고, 한 번 돌리는 빌드라 느려도 돼요.
"""
import os
import sys
from collections import deque

from PIL import Image

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
OUT_DIR = os.path.join(BOT_DIR, "assets", "fish")
SIZE = 512
T0 = 16          # 이 거리 아래는 완전 투명 (배경의 미세한 얼룩까지 여기서 걸러요)
T1 = 64          # 이 거리 위는 "배경 비슷"이 아님 → 부드러운 구역에 안 들어가요
TRUE_BG = 12     # "진짜 배경색"으로 치는 거리
POCKET_MIN = 60          # 안쪽 빈 공간으로 인정할 최소 넓이(px)
POCKET_BG_RATIO = 0.3    # 그 덩어리에서 진짜 배경색 픽셀이 이 비율 이상이어야 빈 공간
# 종별 예외. 빈 공간에 **빛 번짐이 꽉 차서** 진짜 배경색이 거의 안 남은 그림은 기본 비율로
# 못 잡아요 → 눈으로 확인한 종만 낮춰요. 🚨 전체 기본값을 낮추면 은빛 몸통이 뚫려요.
#    실측(2026-11-22): 대왕메기 빈 공간 0.16 · 비단잉어 **흰 몸통** 0.10 · 은어 몸통 0.08 이하.
POCKET_RATIO_BY_KEY: dict[str, float] = {
    "f24": 0.12,     # 대왕메기 — 휘어진 몸 안쪽에 흰 빛이 차 있어요
}
MIN_BLOB = 30    # 이보다 작은 외딴 조각은 먼지로 보고 지워요
MARGIN = 0.04    # 다시 앉힐 때 사방 여백 (변의 4%)

_N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def cutout(src: str, ratio: float = POCKET_BG_RATIO) -> Image.Image:
    im = Image.open(src).convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    W = H = SIZE
    N = W * H
    px = list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())
    border = [px[i] for i in range(W)] + [px[(H - 1) * W + i] for i in range(W)] + \
             [px[j * W] for j in range(H)] + [px[j * W + W - 1] for j in range(H)]
    bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))
    dist = [_dist(c, bg) for c in px]
    soft = bytearray(1 if d < T1 else 0 for d in dist)

    def flood(seeds, ok, mark, value):
        q = deque(seeds)
        for i in seeds:
            mark[i] = value
        members = list(seeds)
        while q:
            i = q.popleft()
            x, y = i % W, i // W
            for dx, dy in _N4:
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H:
                    j = ny * W + nx
                    if not mark[j] and ok[j]:
                        mark[j] = value
                        q.append(j)
                        members.append(j)
        return members

    # 2-⒜ 테두리에서 이어진 부드러운 구역
    zone = bytearray(N)
    edge = [i for i in range(N) if (i < W or i >= N - W or i % W in (0, W - 1)) and soft[i]]
    flood(edge, soft, zone, 1)

    # 2-⒝ 안쪽에 갇힌 빈 공간
    seen = bytearray(zone)
    pockets = 0
    rejected: list[tuple[int, float]] = []
    for s in range(N):
        if seen[s] or not soft[s]:
            continue
        members = flood([s], soft, seen, 1)
        true_bg = sum(1 for i in members if dist[i] < TRUE_BG)
        if len(members) >= POCKET_MIN and true_bg >= len(members) * ratio:
            for i in members:
                zone[i] = 1
            pockets += 1
        elif len(members) >= 400:
            # 진단용: 빈 공간 후보였지만 떨어진 큰 덩어리 (넓이, 진짜 배경색 비율)
            rejected.append((len(members), round(true_bg / len(members), 2)))

    # 3) 알파 + 배경색 몫 빼기
    alpha = [255] * N
    out_px = list(px)
    for i in range(N):
        if not zone[i]:
            continue
        a = (dist[i] - T0) / (T1 - T0)
        if a <= 0:
            alpha[i] = 0
            continue
        a = min(1.0, a)
        alpha[i] = int(255 * a)
        c = px[i]
        out_px[i] = tuple(max(0, min(255, int(bg[k] + (c[k] - bg[k]) / a))) for k in range(3))

    # 4) 먼지 지우기 — 보이는 픽셀(알파 > 0) 덩어리 중 아주 작은 것
    vis = bytearray(1 if a > 0 else 0 for a in alpha)
    seen = bytearray(N)
    for s in range(N):
        if seen[s] or not vis[s]:
            continue
        members = flood([s], vis, seen, 1)
        if len(members) < MIN_BLOB:
            for i in members:
                alpha[i] = 0

    out = Image.new("RGBA", (W, H))
    out.putdata([c + (a,) for c, a in zip(out_px, alpha)])

    # 5) 딱 맞게 잘라 가운데에 — 안 그러면 원본 여백 때문에 도감 칸에서 콩알만 해져요.
    box = out.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
    if box:
        fish = out.crop(box)
        inner = int(SIZE * (1 - 2 * MARGIN))
        scale = inner / max(fish.width, fish.height)
        fish = fish.resize((max(1, int(fish.width * scale)), max(1, int(fish.height * scale))), Image.LANCZOS)
        out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        out.alpha_composite(fish, ((SIZE - fish.width) // 2, (SIZE - fish.height) // 2))
    out.info["pockets"] = pockets
    out.info["rejected"] = sorted(rejected, reverse=True)[:5]
    return out


def main():
    """`python build_fish_assets.py <폴더> [키 ...]` — 키를 주면 그 종만 다시 만들어요."""
    src_dir = sys.argv[1]
    only = set(sys.argv[2:])
    os.makedirs(OUT_DIR, exist_ok=True)
    for fn in sorted(os.listdir(src_dir)):
        if not (fn.startswith("f") and fn.endswith(".png")):
            continue
        key = fn[:-4]
        if only and key not in only:
            continue
        out = cutout(os.path.join(src_dir, fn), POCKET_RATIO_BY_KEY.get(key, POCKET_BG_RATIO))
        path = os.path.join(OUT_DIR, f"{key}.webp")
        pockets = out.info.pop("pockets", 0)
        rejected = out.info.pop("rejected", [])
        out.save(path, "WEBP", quality=90, method=6)
        print(f"✅ {key} → {os.path.getsize(path) // 1024}KB (안쪽 빈 공간 {pockets}곳)"
              + (f" · 떨어진 큰 후보(넓이, 배경색 비율): {rejected}" if rejected else ""))


if __name__ == "__main__":
    main()
