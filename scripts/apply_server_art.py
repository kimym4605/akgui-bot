# -*- coding: utf-8 -*-
"""🖼️ 서버 배너·초대 스플래시·아이콘을 **내가 준 그림 파일로** 바꿔요.

ChatGPT(웹)에서 뽑은 고품질 그림을 그대로 쓰기 위한 도구예요. 규격 맞추기(자르기·크기·
용량)와 올리기·검증을 여기서 다 해요.

## 쓰는 법

    python scripts/apply_server_art.py banner  "C:/.../내그림.png"           # 미리보기만
    python scripts/apply_server_art.py banner  "C:/.../내그림.png" --send    # 실제 적용
    python scripts/apply_server_art.py splash  "C:/.../내그림.png" --send
    python scripts/apply_server_art.py icon    "C:/.../내그림.png" --send

    --anchor top|center|bottom   세로로 어디를 남길지 (기본 center)
    --size 1920x1080             결과 크기 (기본은 종류별 권장값)

## 🚨 미리보기를 **눈으로 보고** 보내세요

`--send` 없이 돌리면 `서버아트/_미리보기_banner.png`를 만들어요. 거기엔 **디스코드가
실제로 하는 일**이 그대로 들어 있어요 — 16:9로 자르고, 아래쪽에 어두운 그라데이션을 깔고,
**왼쪽 아래에 서버 이름을 얹어요.** 글자가 그림 위에 겹쳐서 안 읽히는지 그걸로 봐요.

## 디스코드 규격 (2026-11-04 기준)

| 종류 | 비율 | 권장 크기 | 비고 |
|---|---|---|---|
| `banner` | 16:9 | 960×540 이상 | 채널 목록 맨 위. 서버 이름이 왼쪽 아래에 얹힘 |
| `splash` | 16:9 | 1920×1080 | 초대 링크 미리보기 배경 |
| `icon`   | 1:1  | 512×512   | 서버 프로필 |

🚨 **움직이는 배너(GIF)는 레벨 3**이라 아직 안 돼요. 지금은 레벨 2예요.
🚨 그림 안에 글자를 넣지 마세요 — 서버 이름에 가려지고, 생성 AI가 글자를 자주 틀려요.
"""
import argparse
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from PIL import Image, ImageDraw, ImageFont      # noqa: E402

# 종류별 (가로비, 세로비, 기본 크기, 길드 필드 이름, 필요한 features)
KINDS = {
    "banner": (16, 9, (1920, 1080), "banner", "BANNER"),
    "splash": (16, 9, (1920, 1080), "splash", "INVITE_SPLASH"),
    "icon":   (1, 1, (512, 512),    "icon",   None),
}

# 디스코드가 받아주는 한도. 넉넉히 아래로 맞춰요(PNG가 크면 JPEG로 떨어뜨려요).
MAX_UPLOAD_BYTES = 9 * 1024 * 1024

DROP_DIR = Path(os.path.dirname(BOT_DIR)) / "서버아트"


def _conf() -> dict:
    """🚨 운영봇 토큰이에요. `discord-bot-starter-py/.env`는 TEST봇 거예요."""
    path = os.path.join(os.path.dirname(BOT_DIR), "운영봇_토큰_백업.env")
    conf = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.strip().partition("=")
                conf[k] = v.strip()
    for key in ("DISCORD_TOKEN", "GUILD_ID"):
        if not conf.get(key):
            sys.exit(f"🚨 {path} 에 {key}가 없어요")
    return conf


CONF = _conf()
GUILD_ID = CONF["GUILD_ID"]
HEADERS = {
    "Authorization": f"Bot {CONF['DISCORD_TOKEN']}",
    "User-Agent": "DiscordBot (https://github.com/akgui, 1.0)",
    "Content-Type": "application/json",
}


def _call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"https://discord.com/api/v10{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=HEADERS, method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def fit(src: Image.Image, ratio_w: int, ratio_h: int, size, anchor: str) -> Image.Image:
    """원본을 비율에 맞게 **잘라서** 목표 크기로 만들어요(찌그러뜨리지 않아요)."""
    want = ratio_w / ratio_h
    have = src.width / src.height
    if have > want:
        # 가로가 남아요 — 좌우를 잘라내요(가운데 기준)
        new_w = int(src.height * want)
        left = (src.width - new_w) // 2
        box = (left, 0, left + new_w, src.height)
    else:
        # 세로가 남아요 — anchor가 정한 쪽을 남겨요
        new_h = int(src.width / want)
        if anchor == "top":
            top = 0
        elif anchor == "bottom":
            top = src.height - new_h
        else:
            top = (src.height - new_h) // 2
        box = (0, top, src.width, top + new_h)
    return src.crop(box).resize(size, Image.LANCZOS)


def encode(im: Image.Image) -> tuple[bytes, str]:
    """용량 한도 안에 들어가는 바이트를 만들어요. PNG가 크면 JPEG로 떨어뜨려요."""
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG", optimize=True)
    raw = buf.getvalue()
    if len(raw) <= MAX_UPLOAD_BYTES:
        return raw, "image/png"
    for q in (92, 85, 78, 70):
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=q, optimize=True)
        raw = buf.getvalue()
        if len(raw) <= MAX_UPLOAD_BYTES:
            print(f"   ℹ️ PNG가 커서 JPEG 품질 {q}로 줄였어요.")
            return raw, "image/jpeg"
    sys.exit("🚨 아무리 줄여도 용량 한도를 못 맞췄어요.")


def _font(size: int):
    for path in ("C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def write_preview(im: Image.Image, kind: str, guild_name: str) -> Path:
    """디스코드가 실제로 보여주는 모양을 그려요 — 그라데이션 + 왼쪽 아래 서버 이름."""
    DROP_DIR.mkdir(parents=True, exist_ok=True)
    out = DROP_DIR / f"_미리보기_{kind}.png"
    prev = im.convert("RGBA").resize((960, int(960 * im.height / im.width)), Image.LANCZOS)
    if kind == "banner":
        w, h = prev.size
        shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        for i in range(h // 2):
            a = int(175 * (i / (h / 2)) ** 1.6)
            sd.line([(0, h - 1 - i), (w, h - 1 - i)], fill=(0, 0, 0, a))
        prev.alpha_composite(shade)
        d = ImageDraw.Draw(prev)
        d.text((30, h - 86), guild_name, font=_font(48), fill=(255, 255, 255, 255))
        d.text((30, h - 30), "← 서버 이름이 여기 얹혀요. 글자가 묻히면 다른 그림을 쓰세요.",
               font=_font(18), fill=(200, 200, 205, 255))
    prev.convert("RGB").save(out)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=sorted(KINDS))
    p.add_argument("image", help="쓸 그림 파일 경로")
    p.add_argument("--send", action="store_true", help="실제로 적용해요")
    p.add_argument("--anchor", default="center", choices=["top", "center", "bottom"],
                   help="세로로 잘라낼 때 어느 쪽을 남길지 (기본 center)")
    p.add_argument("--size", help="결과 크기 (예: 1920x1080). 기본은 종류별 권장값")
    args = p.parse_args()

    src_path = Path(args.image)
    if not src_path.exists():
        sys.exit(f"🚨 파일이 없어요: {src_path}")

    rw, rh, default_size, field, need_feature = KINDS[args.kind]
    size = default_size
    if args.size:
        try:
            w, h = (int(v) for v in args.size.lower().split("x"))
            size = (w, h)
        except ValueError:
            sys.exit("🚨 --size 는 1920x1080 꼴로 주세요")

    guild = _call("GET", f"/guilds/{GUILD_ID}")
    feats = guild.get("features") or []
    if need_feature and need_feature not in feats:
        sys.exit(f"🚨 `{need_feature}`가 해금되지 않았어요 — 지금은 {args.kind}를 못 바꿔요.")

    src = Image.open(src_path)
    print(f"원본   : {src_path.name} {src.width}×{src.height} ({src_path.stat().st_size/1024/1024:.1f}MB)")
    out_im = fit(src.convert("RGBA"), rw, rh, size, args.anchor)
    raw, mime = encode(out_im)
    print(f"맞춤   : {size[0]}×{size[1]} · {len(raw)/1024/1024:.2f}MB · {mime}"
          f" · 세로 기준 '{args.anchor}'")

    preview = write_preview(out_im, args.kind, guild.get("name") or "서버")
    print(f"미리보기: {preview}")

    before = guild.get(field)
    print(f"현재 {args.kind}: {'있음' if before else '❌ 없음'}")

    if not args.send:
        print("\n🚨 미리보기를 **눈으로 보고** 괜찮으면 --send 를 붙여 다시 돌리세요.")
        return

    data_uri = f"data:{mime};base64," + base64.b64encode(raw).decode()
    try:
        _call("PATCH", f"/guilds/{GUILD_ID}", {field: data_uri})
    except urllib.error.HTTPError as error:
        sys.exit(f"🚨 적용 실패 (HTTP {error.code}): {error.read().decode('utf-8', 'replace')}")

    # 🚨 `200 ok`는 저장의 증거가 아니에요 — 다시 읽어서 확인해요.
    after = _call("GET", f"/guilds/{GUILD_ID}")
    now = after.get(field)
    if not now or now == before:
        sys.exit(f"🚨 PATCH는 성공했는데 {args.kind}가 안 바뀌었어요 (before={before} after={now})")
    ext = "gif" if str(now).startswith("a_") else "png"
    # ⚠️ CDN 경로는 단순 복수형이 아니에요 — splash는 `splashes`예요.
    cdn_dir = {"banner": "banners", "splash": "splashes", "icon": "icons"}[args.kind]
    print(f"✅ 적용됐어요. 다시 읽어서 확인했어요.")
    print(f"   https://cdn.discordapp.com/{cdn_dir}/{GUILD_ID}/{now}.{ext}?size=1024")


if __name__ == "__main__":
    main()
