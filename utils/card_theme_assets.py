"""🎴 캐릭터 카드 테마 - **폴더에 그림을 넣으면 상점에 뜨는** 구조예요.

## 왜 이렇게 만들었나 (2026-11-03)

🎨 색 테마는 6종을 깔았는데 **전체 기간 1건만 팔렸어요**(10-23 `숲`, 한 사람).
10-27에 🪙 상설 패널까지 깔고 재봤는데 **그 뒤로도 0건**이에요. 같은 날 만든 🧊 보호권은
2건 움직였으니 **발견 문제가 아니라 동기 문제**예요 - "어두운 색 배경"에는 욕심이 안 나요.
반면 🎴 카드뽑기는 127건 팔려요. 차이는 **수집·표현 동기**예요.
→ 그래서 "좋아하는 캐릭터로 카드를 꾸민다"로 품목 자체를 바꿔요.

⭐ **카탈로그를 코드에 박지 않아요.** 서버원이 캐릭터를 요청하면 방장이 그림을
`assets/card_themes/`에 넣고 `themes.json`에 한 줄 적으면 끝이에요. 코드 수정도,
배포 스크립트 수정도 필요 없어요. (그림 출처는 넣는 사람이 정해요 - 이 모듈은
파일을 읽을 뿐이고, 봇이 그림을 만들지 않아요.)

## 🚨 파일이 없는 항목은 **카탈로그에서 빼요**

`themes.json`에 적혀 있는데 PNG가 없으면, 그 테마는 `/프로필`에서 **조용히 기본 테마로**
그려져요. 그러면 **25코인을 받고 아무 일도 안 일어나는** 상품을 파는 거예요.
그래서 불러올 때 파일 존재를 확인해서 **없는 건 빼고 경고를 남겨요.**
⚠️ 빼는 쪽으로 틀리는 게 안전해요 - 안 보이는 상품은 민원이 나지만, 깨진 상품은 환불 사고예요.
🚨 `scripts/check_card_themes.py`가 양방향으로 대조해요(파일↔목록).

## 🚨 `data/`가 아니라 `assets/`예요

`data/`는 Fly 볼륨이 덮어써서, 거기 넣고 배포하면 **서버에 반영되지 않아요**
(육아방 알 생성이 이것 때문에 두 달 죽어 있었어요). `assets/`는 `COPY . .`로 이미지에
들어가고 볼륨이 안 가려요 - `assets/fonts`가 같은 이유로 거기 있어요.
"""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

THEME_DIR = Path(__file__).resolve().parent.parent / "assets" / "card_themes"
MANIFEST = THEME_DIR / "themes.json"

# 카드 크기(profile_card.CARD_WIDTH/HEIGHT와 같아야 해요). 여기 두는 이유는
# profile_card가 이 모듈을 import하는데 반대로도 하면 순환 import가 되기 때문이에요.
CARD_SIZE = (1000, 560)

# 🚨 터무니없이 큰 그림을 막아요(디코딩 폭탄 + 512MB 머신). 4K면 충분해요.
MAX_PIXELS = 4000 * 4000

# 그림에서 패널 색을 못 뽑았을 때 쓰는 기본값. 어두운 남색이에요.
FALLBACK_TOP = (18, 18, 26)
FALLBACK_BOTTOM = (34, 34, 48)


def _load_manifest() -> list[dict]:
    if not MANIFEST.exists():
        # 캐릭터 테마가 아직 없는 상태예요. 색 테마만 팔려요(정상).
        return []
    try:
        raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 🚨 목록이 깨져도 프로필 카드는 그려져야 해요. 캐릭터 테마만 빠져요.
        log.exception("🎴 card_themes/themes.json을 읽을 수 없어요 - 캐릭터 테마를 건너뛰어요")
        return []
    if isinstance(raw, dict):               # {"themes": [...]} 꼴도 받아줘요
        raw = raw.get("themes") or []
    if not isinstance(raw, list):
        log.error("🎴 themes.json이 목록이 아니에요(%s) - 건너뛰어요", type(raw).__name__)
        return []
    return [e for e in raw if isinstance(e, dict)]


def _cap(color: tuple, ceiling: int) -> tuple:
    """가장 밝은 채널이 `ceiling`을 넘으면 **세 채널을 같은 비율로** 줄여요.
    채널마다 따로 자르면 색조가 틀어져요(붉은 그림이 회색이 되는 식)."""
    peak = max(color)
    if peak <= ceiling:
        return color
    scale = ceiling / peak
    return tuple(max(6, int(c * scale)) for c in color)


def _dominant(path: Path) -> tuple[tuple, tuple] | None:
    """그림에서 패널·진행바에 쓸 어두운 두 색을 뽑아요.

    ⭐ **이걸 뽑아두는 이유**: 이미지 테마도 `top`/`bottom`을 갖고 있으면 `_panel_colors`·
       `_progress_bar` 같은 기존 코드가 **하나도 안 바뀌어요.** 색 테마용으로 짜둔
       파생 로직을 그대로 재사용해요(테마마다 패널 색을 손으로 적으면 꼭 어긋나요).
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGB").resize((2, 2))
            px = [im.getpixel((x, y)) for x in (0, 1) for y in (0, 1)]
    except Exception:                        # noqa: BLE001
        log.warning("🎴 %s 에서 색을 못 뽑았어요 - 기본 남색으로 둬요", path.name, exc_info=True)
        return None
    avg = tuple(sum(c[i] for c in px) // len(px) for i in range(3))
    # 글씨가 흰색이라 배경 파생 색은 **반드시 어두워야** 해요. 0.22/0.38로 눌러요.
    top = tuple(max(8, int(avg[i] * 0.22)) for i in range(3))
    bottom = tuple(max(14, int(avg[i] * 0.38)) for i in range(3))
    # 🚨🚨 **비율만으로는 부족해요 — 상한을 걸어야 해요.**
    #    흰 배경 그림(avg≈250)을 넣어보니 (55,53,53)/(94,93,93)이 나왔어요. 패널이
    #    **중간 회색**이 되어서 ⒜불투명 패널이 그림을 거의 다 가리고 ⒝그 위의
    #    보조 글씨(TEXT_DIM)가 회색 위 회색이라 **안 읽혔어요.** 실제로 카드를
    #    뽑아보고 찾았어요(색 값만 봤으면 못 봤어요).
    # ⭐ 색조(hue)는 살리고 **밝기만** 눌러요 — 전체를 같은 비율로 줄이면 그림의
    #    분위기는 남고 어두워지기만 해요. 기본 테마가 (15,17,25)/(26,29,46)이라
    #    그 언저리로 맞춰요.
    top = _cap(top, 30)
    bottom = _cap(bottom, 52)
    return top, bottom


def _validate(path: Path) -> str:
    """쓸 수 있는 그림인지 본다. 빈 문자열이면 OK, 아니면 사유."""
    try:
        from PIL import Image
    except ImportError:
        return ""                            # Pillow가 없으면 카드를 아예 못 그려요(별도 경고)
    try:
        with Image.open(path) as im:         # 헤더만 읽어요(전체 디코딩 안 해요)
            w, h = im.size
    except Exception as exc:                 # noqa: BLE001
        return f"열 수 없는 그림이에요 ({type(exc).__name__})"
    if w * h > MAX_PIXELS:
        return f"너무 커요 ({w}x{h}) - {MAX_PIXELS:,}픽셀 이하로 줄여주세요"
    if w < CARD_SIZE[0] // 2 or h < CARD_SIZE[1] // 2:
        return f"너무 작아요 ({w}x{h}) - 늘리면 뭉개져요. {CARD_SIZE[0]}x{CARD_SIZE[1]} 권장"
    return ""


def load() -> dict[str, dict]:
    """`{테마이름: {emoji, desc, image, top, bottom, kind}}`.

    🚨 **파일이 없거나 못 읽는 항목은 빼요**(위 설명 참고). 뺀 건 경고로 남겨요.
    """
    out: dict[str, dict] = {}
    for entry in _load_manifest():
        key = str(entry.get("key") or "").strip()
        image = str(entry.get("image") or "").strip()
        if not key or not image:
            log.error("🎴 themes.json 항목에 key 또는 image가 없어요: %r", entry)
            continue
        # 🚨 경로 탈출을 막아요(`../../`). 파일 이름만 받아요.
        if Path(image).name != image:
            log.error("🎴 image는 파일 이름만 적어주세요(폴더 경로 금지): %r", image)
            continue
        path = THEME_DIR / image
        if not path.exists():
            log.error("🎴 '%s' 테마의 그림이 없어요: %s - 상점에서 빼요", key, path.name)
            continue
        why = _validate(path)
        if why:
            log.error("🎴 '%s' 테마의 그림을 쓸 수 없어요(%s) - 상점에서 빼요", key, why)
            continue

        colors = _dominant(path)
        top, bottom = colors if colors else (FALLBACK_TOP, FALLBACK_BOTTOM)
        out[key] = {
            "kind": "character",
            "emoji": str(entry.get("emoji") or "🎴"),
            "desc": str(entry.get("desc") or f"{key} 테마"),
            "image": str(path),
            # 목록에 적어두면 그걸 쓰고, 없으면 그림에서 뽑은 값을 써요.
            "top": tuple(entry["top"]) if entry.get("top") else top,
            "bottom": tuple(entry["bottom"]) if entry.get("bottom") else bottom,
        }
    if out:
        log.info("🎴 캐릭터 카드 테마 %d종 불러왔어요: %s", len(out), ", ".join(out))
    return out


CHARACTER_THEMES: dict[str, dict] = load()
