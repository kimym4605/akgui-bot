# -*- coding: utf-8 -*-
"""🎨 도박장 그림 검사 (2026-11-22). DB·디스코드를 안 건드려요.

    python scripts/test_casino_art.py

막으려는 사고:
- **그림이 실제 결과와 다르게 나오는 것** (💎💎💎인데 릴에는 폭탄이 서 있다든지)
- 릴이 멈추기도 전에 결과가 새는 것 · 블랙잭 **뒤집힌 카드가 그림에서 새는 것**
- 그림을 못 그리거나 못 보냈을 때 **게임까지 같이 죽는 것** (코인은 이미 정산된 뒤예요)
- 블랙잭 화면을 고칠 때 지난 그림이 남는 것(한 장 전의 패가 보여요) · 연타로 화면이 뒤처지는 것
- 배당표·구간을 고쳤는데 그림만 옛 숫자로 남는 것
"""
import asyncio
import io
import logging
import os
import random
import sys
import tempfile
import types
from itertools import product
from pathlib import Path

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")     # 접속하지 않아요(전부 가짜로 바꿔요)
os.environ["MONGODB_DB_NAME"] = "agwi_casino_test"
os.environ["BIRTHDAY_DB_NAME"] = "agwi_casino_test"

from PIL import Image, ImageChops, ImageDraw, ImageStat  # noqa: E402

from utils import casino_art as art  # noqa: E402
from utils import casino_games as games  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


def diff(a: Image.Image, b: Image.Image) -> float:
    """두 그림의 평균 차이(채널당 0~255)."""
    return sum(ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB"))).mean) / 3


EMOJI = [e for e, _ in games.SLOT_SYMBOLS]
A, B, C, D = EMOJI


def mult_of(symbols) -> int:
    return games._slot_payout_multiplier(tuple(EMOJI.index(s) for s in symbols))


# ══════════════════════════════════════════════════════════════════
print("[1] 그림 재료 (assets/casino)")
import build_casino_assets as build  # noqa: E402

names = ["hall", "felt", "cardback", *build.SYMBOLS]
missing = [n for n in names if not (art.ART_DIR / f"{n}.webp").exists()]
check("재료 7장이 전부 있다", not missing, str(missing))
check("슬롯 심볼 그림이 배당표의 심볼과 **이모지로** 짝이 맞는다",
      set(art.SLOT_ART) == set(EMOJI), f"{sorted(art.SLOT_ART)} vs {sorted(EMOJI)}")
check("심볼 그림 파일이 빌드 스크립트가 만드는 것과 같다",
      sorted(art.SLOT_ART.values()) == sorted(build.SYMBOLS), str(sorted(art.SLOT_ART.values())))
bad = []
for n in build.SYMBOLS:
    im = Image.open(art.ART_DIR / f"{n}.webp").convert("RGBA")
    s = im.width
    corners = [im.getpixel(xy)[3] for xy in ((0, 0), (s - 1, 0), (0, s - 1), (s - 1, s - 1))]
    solid = sum(1 for a in im.getchannel("A").tobytes() if a > 200) / (im.width * im.height)
    if im.size != (build.SYMBOL_SIZE,) * 2 or max(corners) > 0 or not 0.15 < solid < 0.92:
        bad.append(f"{n} size={im.size} 모서리={corners} 불투명비율={solid:.2f}")
check("심볼은 정사각형 · 네 모서리 투명 · 그림이 차 있다", not bad, str(bad))
felt, back, hall = (Image.open(art.ART_DIR / f"{n}.webp") for n in ("felt", "cardback", "hall"))
check("테이블 그림 크기 = 블랙잭 그림 크기 (어긋나면 금테가 잘려요)",
      felt.size == (art.BJ_W, art.BJ_H) == build.FELT_SIZE, f"{felt.size} / {build.FELT_SIZE}")
check("카드 뒷면 = 카드 크기의 2배",
      back.size == (art.CARD_W * 2, art.CARD_H * 2) == build.CARDBACK_SIZE, f"{back.size}")
check("도박장 배경이 제일 큰 그림(현황 배너)보다 작지 않다 (늘리면 뿌예져요)",
      hall.width >= art.LOBBY_W and hall.height >= max(art.SLOT_H, art.HL_H, art.LOBBY_H), str(hall.size))
total = sum((art.ART_DIR / f"{n}.webp").stat().st_size for n in names if n not in missing)
check(f"재료 합계 {total // 1024}KB (배포 꾸러미에 얹는 무게 500KB 이하)", total < 500 * 1024)
check("`_load`가 WebP의 info(loop·background)를 지운다 (GIF 저장으로 새요)",
      art._load("hall", "RGB").info == {} and art._load("sym_bomb").info == {})

# ══════════════════════════════════════════════════════════════════
print("[2] 🎰 슬롯 — 릴이 **진짜 결과**에 선다")
combos = [list(c) for c in product(EMOJI, repeat=3)]
wrong, near, start = [], [], []
for syms in combos:
    for r, (stop, cells, seq) in enumerate(art._slot_reels(syms)):
        if seq[cells] != syms[r]:
            wrong.append((syms, r))
        if syms[r] in (seq[cells - 1], seq[cells + 1]):
            near.append((syms, r))
        if art._reel_offset(stop, stop, cells) != (cells * art.CELL, False) or art._reel_offset(0, stop, cells)[0] < art.CELL:
            start.append((syms, r))
check(f"{len(combos)}가지 결과 전부: 멈추는 칸 = 그 릴의 결과", not wrong, str(wrong[:3]))
check("멈춘 칸 위아래는 다른 심볼 (걸쳐 보여도 '일치'로 안 읽힌다)", not near, str(near[:3]))
check("릴은 정확히 멈추는 칸에서 서고, 시작할 때도 칸 목록 안이다", not start, str(start[:3]))
check("멈추는 시각이 프레임 간격의 배수 · 왼쪽부터 차례로",
      all(t % art.FRAME_MS == 0 for t in art.REEL_STOP_MS) and list(art.REEL_STOP_MS) == sorted(set(art.REEL_STOP_MS)))
back_moves = []
for stop, cells, _seq in art._slot_reels([A, B, C]):
    offs = [art._reel_offset(t, stop, cells)[0] for t in range(0, stop + 1, 10)]
    if any(b < a for a, b in zip(offs, offs[1:])):
        back_moves.append(stop)
check("릴이 뒤로 돌지 않는다", not back_moves, str(back_moves))
texts = {m: art.slot_banner(m)[0] for m in {mult_of(s) for s in combos}}
check("띠 문구가 배당을 그대로 말한다 (꽝 · 본전 · N배)",
      texts[0] == "꽝" and "본전" in texts[games.SLOT_PAIR_PAYOUT]
      and all(f"{m}배" in texts[m] for _e, m in games.SLOT_SYMBOLS), str(texts))


def reel_box(r: int, inset: int = 9):
    x = art.REEL_LEFT + r * (art.REEL_W + art.REEL_GAP)
    return (x + inset, art.REEL_TOP + inset, x + art.REEL_W - inset, art.REEL_TOP + art.REEL_H - inset)


def windows(syms) -> list[bytes]:
    still = art._slot_build(list(syms), mult_of(syms))[2]
    return [still.crop(reel_box(r)).tobytes() for r in range(3)]


# 정지 그림의 릴 창을 **픽셀로** 견줘요. 같은 심볼·같은 상태(맞음/안 맞음)면 창 안이 똑같이 나와요.
lit = {}                                    # 심볼 → 맞은 릴의 창
for s in EMOJI:
    w = windows([s, s, s])
    lit[s] = w[0]
    check(f"세 개 일치 {s}: 세 창이 똑같다", w[0] == w[1] == w[2])
check("심볼 4종의 창이 서로 다르다 (견주는 게 의미가 있다)", len(set(lit.values())) == len(EMOJI))
dim = {}                                    # 심볼 → 안 맞은 릴의 창
pair_ok = True
for i, s in enumerate(EMOJI):
    odd = EMOJI[(i + 1) % len(EMOJI)]
    w = windows([s, odd, s])
    pair_ok &= w[0] == lit[s] and w[2] == lit[s] and w[1] != lit[odd]
    dim[odd] = w[1]
check("두 개 일치: 맞은 두 릴은 밝게, 안 맞은 릴은 어둡게 - 심볼도 제자리", pair_ok)
bust_bad = []
for syms in ([A, B, C], [D, C, B], [B, D, A], [C, A, D]):
    w = windows(syms)
    if any(w[r] != dim[syms[r]] for r in range(3)):
        bust_bad.append(syms)
check("꽝: 세 릴 모두 제 심볼이 (어둡게) 서 있다", not bust_bad, str(bust_bad))

print("[3] 🎰 슬롯 GIF")
for label, syms in (("세 개 일치", [D, D, D]), ("두 개 일치", [A, B, A]), ("꽝", [B, C, D])):
    m = mult_of(syms)
    gif, jpg = art.render_slot(syms, m)
    im = Image.open(io.BytesIO(gif))
    frames, durs = [], []
    for i in range(im.n_frames):
        im.seek(i)
        frames.append(im.convert("RGB"))
        durs.append(im.info["duration"])
    still = Image.open(io.BytesIO(jpg))
    check(f"{label}: GIF {len(gif) // 1024}KB · {len(frames)}장 · {art.SLOT_W}×{art.SLOT_H} · 1MB 이하",
          im.size == (art.SLOT_W, art.SLOT_H) == still.size and len(gif) < 1024 * 1024 and len(frames) > 20,
          f"{im.size} {len(gif)}")
    check(f"{label}: 한 번만 돈다 (loop 없음) · 마지막 장을 {art.HOLD_MS // 1000}초 붙든다",
          im.info.get("loop") is None and durs[-1] == art.HOLD_MS, f"loop={im.info.get('loop')} 끝={durs[-1]}")
    check(f"{label}: 마지막 장 전까지의 길이 = slot_seconds ({art.slot_seconds(m):.2f}초)",
          sum(durs[:-1]) == round(art.slot_seconds(m) * 1000), f"{sum(durs[:-1])}")
    check(f"{label}: GIF 마지막 장 ≈ 정지 그림 (바꿔 끼워도 안 튄다)", diff(frames[-1], still) < 8,
          f"{diff(frames[-1], still):.1f}")
    # 🚨 릴이 다 멈추기 전에는 결과 띠 자리가 비어 있어야 해요.
    band = (art.SLOT_BAY[0], art.SLOT_BAY[3] + 2, art.SLOT_BAY[2], art.SLOT_DYN[3])
    spinning, t = [], 0
    for f, d in zip(frames, durs):
        if t < art.REEL_STOP_MS[-1]:
            spinning.append(f)
        t += d
    leak = [i for i, f in enumerate(spinning) if f.crop(band).tobytes() != spinning[0].crop(band).tobytes()]
    check(f"{label}: 🚨 릴이 다 멈추기 전에는 결과 띠가 안 뜬다 ({len(spinning)}장)", not leak and len(spinning) >= 20, str(leak))
    check(f"{label}: 결과 띠는 마지막에 뜬다", frames[-1].crop(band).tobytes() != spinning[0].crop(band).tobytes())
    early = [r for r in range(3) if diff(frames[0].crop(reel_box(r)), frames[-1].crop(reel_box(r))) < 10]
    check(f"{label}: 첫 장은 결과를 안 보여준다 (세 릴 다 도는 중)", not early, str(early))
    check(f"{label}: 같은 결과는 늘 같은 그림 (바이트까지)", art.render_slot(syms, m) == (gif, jpg))
check("재료에 없는 심볼이 오면 None (부른 쪽이 글만 보낸다)", art.render_slot(["🍒", A, B], 0) is None)
check("세 개 일치만 번쩍임만큼 더 길다",
      art.slot_seconds(max(m for _e, m in games.SLOT_SYMBOLS)) > art.slot_seconds(0) == art.slot_seconds(games.SLOT_PAIR_PAYOUT)
      == art.REEL_STOP_MS[-1] / 1000)

# ══════════════════════════════════════════════════════════════════
print("[4] 🎲 하이로우")


class FixedRng:
    def __init__(self, n):
        self.n = n

    def randint(self, _a, _b):
        return self.n


banner_bad = []
for n in range(1, games.HIGHLOW_MAX + 1):
    for choice in ("high", "low"):
        number, m, note = games.roll_highlow(choice, FixedRng(n))
        text, _color = art.highlow_banner(number, m)
        want = "하우스" if "하우스" in note else ("맞혔" if m > 0 else "빗나")
        if want not in text or (m > 0 and f"{m}배" not in text):
            banner_bad.append((n, choice, text))
check("1~100 × 높다/낮다 전부: 띠 문구가 규칙의 판정과 같다", not banner_bad, str(banner_bad[:3]))

x0, y0, x1, y1 = art.HL_BAR
at = lambda n: x0 + n * (x1 - x0) / games.HIGHLOW_MAX      # noqa: E731  (숫자 n 칸의 오른쪽 끝)
mid_y = (y0 + y1) // 2
zone_of = lambda n: ("low" if n <= games.HIGHLOW_LOW_MAX else "high" if n >= games.HIGHLOW_HIGH_MIN else "house")   # noqa: E731
color_of = {"low": art.HL_LOW, "house": art.HL_HOUSE, "high": art.HL_HIGH}
pin_bad = []
edges = sorted({1, games.HIGHLOW_LOW_MAX, games.HIGHLOW_LOW_MAX + 1, games.HIGHLOW_HIGH_MIN - 1,
                games.HIGHLOW_HIGH_MIN, games.HIGHLOW_MAX})
for n in edges:
    zone = zone_of(n)
    choice = zone if zone != "house" else "low"            # 고른 쪽·하우스는 제 색 그대로 칠해져요
    img = art._highlow_image(n, choice, games.roll_highlow(choice, FixedRng(n))[1])
    cx = at(n - 0.5)
    near = {img.getpixel((round(cx + dx), mid_y)) for dx in (-7, 7) if x0 + 2 <= cx + dx <= x1 - 2}
    if color_of[zone] not in near:
        pin_bad.append((n, zone, near))
check(f"구간 경계 숫자 {edges}: 핀이 제 구간 색 위에 꽂힌다", not pin_bad, str(pin_bad))
img = art._highlow_image(50, "low", 0)
cuts = [(at(games.HIGHLOW_LOW_MAX) - 2, art.HL_LOW), (at(games.HIGHLOW_LOW_MAX) + 2, art.HL_HOUSE),
        (at(games.HIGHLOW_HIGH_MIN - 1) - 2, art.HL_HOUSE)]
check("막대의 구간 경계가 `casino_games` 상수 자리에 있다",
      all(img.getpixel((round(x), y0 + 3)) == c for x, c in cuts if abs(x - at(49.5)) > 6),
      str([img.getpixel((round(x), y0 + 3)) for x, _c in cuts]))
a, b = art._highlow_image(83, "high", 2), art._highlow_image(83, "low", 0)
check("같은 숫자라도 고른 쪽에 따라 그림이 다르다 (내가 고른 쪽이 밝다)", diff(a, b) > 3, f"{diff(a, b):.1f}")
jpg = art.render_highlow(83, "high", 2)
check(f"JPEG {len(jpg) // 1024}KB · {art.HL_W}×{art.HL_H}",
      Image.open(io.BytesIO(jpg)).size == (art.HL_W, art.HL_H) and len(jpg) < 200 * 1024)

# ══════════════════════════════════════════════════════════════════
print("[5] 🃏 블랙잭")
kw = dict(player_suits=["heart", "club"], bet=10)
hid1 = art._blackjack_image([13, 6], [10, 7], dealer_suits=["spade", "heart"], reveal=False, **kw)
hid2 = art._blackjack_image([13, 9], [10, 7], dealer_suits=["spade", "diamond"], reveal=False, **kw)
shown = art._blackjack_image([13, 6], [10, 7], dealer_suits=["spade", "heart"], reveal=True, **kw)
check("🚨 뒤집힌 카드를 바꿔도 그림이 **똑같다** (숫자·무늬·합계 어디로도 안 샌다)", hid1.tobytes() == hid2.tobytes())
check("공개하면 달라진다", diff(hid1, shown) > 1, f"{diff(hid1, shown):.2f}")
hid3 = art._blackjack_image([13, 6, 5], [10, 7], dealer_suits=["spade", "heart", "club"], reveal=False, **kw)
hid4 = art._blackjack_image([13, 2, 9], [10, 7], dealer_suits=["spade", "club", "heart"], reveal=False, **kw)
check("딜러가 세 장이어도 둘째 장부터는 전부 뒷면", hid3.tobytes() == hid4.tobytes())

book = art.SuitBook(random.Random(3))
deck, hand, suits = games.new_deck(random.Random(3)), [], []
dup = False
while deck:                                           # cog처럼 **한 장씩** 늘려요
    hand.append(deck.pop())
    before = list(suits)
    book.extend(suits, hand)
    dup |= suits[:len(before)] != before
pairs = list(zip(hand, suits))
check("무늬 장부: 덱 52장을 다 뽑아도 같은 카드(숫자+무늬)가 두 번 안 나온다",
      len(set(pairs)) == 52 == len(pairs), f"{len(set(pairs))}/{len(pairs)}")
check("무늬 장부: 이미 정한 무늬는 안 바뀐다 (히트해도 앞 카드가 그대로)", not dup)
check("무늬 장부: 장부가 꽉 찬 숫자를 또 줘도 안 터진다", len(book.extend(suits, hand + [1, 1])) == 54)

row_bad = []
for n in range(1, 12):                                # 블랙잭에서 한 손 최대 11장(A×4 2×4 3×3 = 21)
    x, step = art._bj_row(n)
    if x < art.BJ_CARDS_LEFT or x + step * (n - 1) + art.CARD_W > art.BJ_CARDS_RIGHT or (n > 1 and step < 39):
        row_bad.append((n, x, step))
check("카드 1~11장: 줄 안에 들어가고, 겹쳐도 왼쪽 위 숫자는 보인다(39px)", not row_bad, str(row_bad))
check("5장까지는 안 겹친다", all(art._bj_row(n)[1] >= art.CARD_W for n in range(2, 6)))

outcomes = {
    "블랙잭": ([1, 13], [9, 8]), "버스트": ([10, 6, 8], [5, 11]), "딜러 버스트": ([10, 7], [10, 6, 9]),
    "승리": ([10, 9], [10, 7]), "패배": ([10, 7], [10, 9]), "무승부": ([10, 10], [13, 12]),
}
ban_bad, tag_bad = [], []
for label, (player, dealer) in outcomes.items():
    m, note = games.settle_blackjack(player, dealer)
    text, color = art.blackjack_banner(note, m)
    want = art.WIN if m > games.BJ_PUSH_PAYOUT else (art.TEXT if m == games.BJ_PUSH_PAYOUT else art.LOSE)
    if not text or len(text) > 20 or any(ch in text for ch in "*🃏🎉—") or color != want or label.split()[0] not in text:
        ban_bad.append((label, text, color))
    b2 = art.SuitBook(random.Random(1))
    args = dict(dealer_suits=b2.extend([], dealer), player_suits=b2.extend([], player), reveal=True, bet=30)
    with_note = art._blackjack_image(dealer, player, note=note, outcome=m, **args)
    plain = art._blackjack_image(dealer, player, **args)
    tag_box = (art.BJ_W - 148, art.BJ_H // 2 - 16, art.BJ_W - 22, art.BJ_H // 2 + 16)
    if with_note.crop(tag_box).tobytes() != plain.crop(tag_box).tobytes() or diff(with_note, plain) < 0.3:
        tag_bad.append(label)
check("결과 띠: 6가지 판정 모두 짧은 글 · 마크다운/이모지 없음 · 색이 승패와 맞다", not ban_bad, str(ban_bad))
check("결과 띠가 베팅 꼬리표를 덮지 않는다 (제일 긴 금액 30코인으로)", not tag_bad, str(tag_bad))
check("진행 중에는 띠가 없다", art.blackjack_banner("", None)[0] == "")
big = art.render_blackjack([1, 1, 1, 1, 2, 2, 2, 2, 3], [3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 1],
                           dealer_suits=[], player_suits=[], reveal=True, note="버스트! (22)", outcome=0, bet=5)
check(f"카드가 제일 많은 판 · 무늬 목록이 비어도 그린다 ({len(big) // 1024}KB · {art.BJ_W}×{art.BJ_H})",
      Image.open(io.BytesIO(big)).size == (art.BJ_W, art.BJ_H) and len(big) < 300 * 1024)
suit_px = {s: art._suit_icon(s, 40).tobytes() for s in art.SUITS}
check("무늬 4종의 그림이 서로 다르다", len(set(suit_px.values())) == 4)
faces = {(r, s): art._card_face(r, s).tobytes() for r in range(1, 14) for s in art.SUITS}
check("카드 52장의 앞면이 전부 다르다", len(set(faces.values())) == 52)

print("[6] 현황 배너")
lobby = art.render_lobby()
check(f"JPEG {len(lobby) // 1024}KB · {art.LOBBY_W}×{art.LOBBY_H}",
      Image.open(io.BytesIO(lobby)).size == (art.LOBBY_W, art.LOBBY_H) and len(lobby) < 300 * 1024)

# ══════════════════════════════════════════════════════════════════
print("[7] 🚨 재료가 없거나 깨져도 게임은 돈다")
real_dir = art.ART_DIR
logging.disable(logging.CRITICAL)                          # 일부러 낸 실패의 경고는 숨겨요
try:
    with tempfile.TemporaryDirectory() as tmp:
        art.ART_DIR = Path(tmp)
        check("재료 없음: 슬롯은 None (글만 보낸다)", art.render_slot([A, B, C], 0) is None
              and asyncio.run(art.slot_card([A, B, C], 0)) is None)
        check("재료 없음: 하이로우·블랙잭·현황은 단색 바탕으로 그린다",
              len(art.render_highlow(50, "low", 0)) > 1000 and len(art.render_lobby()) > 1000
              and len(art.render_blackjack([13, 6], [10, 7], dealer_suits=[], player_suits=[], reveal=False)) > 1000)
        for n in names:
            (Path(tmp) / f"{n}.webp").write_bytes(b"not an image")
        check("재료가 깨짐: 똑같이 물러난다", art.render_slot([A, B, C], 0) is None
              and len(art.render_highlow(50, "low", 0)) > 1000
              and len(art.render_blackjack([13, 6], [10, 7], dealer_suits=[], player_suits=[], reveal=False)) > 1000)
    art.ART_DIR = real_dir

    def _boom(*_a, **_kw):
        raise RuntimeError("일부러 낸 오류")

    saved = (art.render_slot, art.render_highlow, art.render_blackjack, art.render_lobby)
    art.render_slot = art.render_highlow = art.render_blackjack = art.render_lobby = _boom
    try:
        got = [asyncio.run(art.slot_card([A, B, C], 0)), asyncio.run(art.highlow_card(1, "low", 2)),
               asyncio.run(art.blackjack_card([1], [2], dealer_suits=[], player_suits=[], reveal=True)),
               asyncio.run(art.lobby_card())]
        check("그리다 터지면 `*_card()`는 None을 돌려준다 (예외를 밖으로 안 던진다)", got == [None] * 4, str(got))
    finally:
        art.render_slot, art.render_highlow, art.render_blackjack, art.render_lobby = saved
finally:
    art.ART_DIR = real_dir
    logging.disable(logging.NOTSET)

# ══════════════════════════════════════════════════════════════════
print("[8] `/도박`에 붙었나 — 정산이 먼저, 그림은 나중")
import discord  # noqa: E402

import cogs.casino as cas  # noqa: E402

events: list = []


class _HTTP:
    status, reason = 400, "Bad Request"


def _http_error():
    return discord.HTTPException(_HTTP(), "일부러 낸 전송 실패")


def _names(kw) -> list[str]:
    files = list(kw.get("files") or kw.get("attachments") or []) + ([kw["file"]] if kw.get("file") else [])
    return [f.filename for f in files]


class FakeMessage:
    def __init__(self, fail_art=False):
        self.edits, self.fail_art = [], fail_art

    async def edit(self, **kw):
        self.edits.append(kw)
        events.append(("timeout-edit", _names(kw)))
        if self.fail_art and _names(kw):
            raise _http_error()


class FakeFollowup:
    def __init__(self, inter):
        self.inter = inter

    async def send(self, content=None, **kw):
        kw["content"] = content
        self.inter.sent.append(kw)
        events.append(("send", _names(kw)))
        fail = self.inter.fail          # "art" = 그림 붙인 전송만 실패 · "view" = 버튼 달린 전송(판)은 다 실패
        if (fail == "art" and _names(kw)) or (fail == "view" and kw.get("view") is not None):
            raise _http_error()
        return FakeMessage()


class FakeResponse:
    async def defer(self, **_kw):
        events.append(("defer",))


class FakeInteraction:
    type = "component"

    def __init__(self, fail=None, slow=0.0):
        self.user = types.SimpleNamespace(id=1)
        self.response, self.followup = FakeResponse(), FakeFollowup(self)
        self.sent, self.edits, self.fail, self.slow = [], [], fail, slow
        self.view = None                     # 블랙잭: 고치는 순간의 손패 장수를 적어둬요

    async def edit_original_response(self, **kw):
        self.edits.append(kw)
        events.append(("edit", _names(kw), len(self.view.player) if self.view else None))
        if self.slow:
            await _real_sleep(self.slow)
        if self.fail == "art" and _names(kw):
            raise _http_error()


def fields(embed) -> str:
    return (embed.description or "") + " ".join(f"{f.name} {f.value}" for f in embed.fields)


async def _take_bet(_inter, _amount):
    return True, "", False


async def _pay_out(_uid, bet, multiplier):
    events.append(("pay_out", bet, multiplier))
    return bet * multiplier, 100


_real_sleep = asyncio.sleep
slept: list[float] = []


async def _fake_sleep(sec, *a, **k):
    slept.append(sec)
    events.append(("sleep", sec))
    await _real_sleep(0)


async def _no_art(*_a, **_kw):
    events.append(("art", None))
    return None


def spied(fn):
    async def wrap(*a, **k):
        out = await fn(*a, **k)
        events.append(("art", "ok" if out else None))
        return out
    return wrap


def order(*kinds) -> bool:
    """events에 kinds가 **그 순서로** 나오는가."""
    seen = [e[0] for e in events]
    pos = -1
    for k in kinds:
        if k not in seen[pos + 1:]:
            return False
        pos = seen.index(k, pos + 1)
    return True


cog = cas.Casino(None)
saved_cas = (cas.take_bet, cas.pay_out, games.spin_slot, games.roll_highlow, games.new_deck,
             art.slot_card, art.highlow_card, art.blackjack_card, art.lobby_card)
cas.take_bet, cas.pay_out = _take_bet, _pay_out
asyncio.sleep = _fake_sleep
logging.disable(logging.CRITICAL)
try:
    # ── 슬롯 ──
    games.spin_slot = lambda: ([D, D, D], 7, "**세 개 일치!** 💎 7배")
    art.slot_card = spied(saved_cas[5])
    events.clear(), slept.clear()
    it = FakeInteraction()
    asyncio.run(cog.slot.callback(cog, it, 5))
    check("슬롯: 정산 → 그림 → GIF 전송 → 기다림 → 결과로 교체 순서", order("pay_out", "art", "send", "sleep", "edit"),
          str([e[0] for e in events]))
    first, last = it.sent[0], it.edits[-1]
    check("슬롯: 처음엔 도는 GIF 한 장", len(it.sent) == 1 and _names(first) == [cas.SLOT_SPIN_FILE]
          and first["embed"].image.url == f"attachment://{cas.SLOT_SPIN_FILE}"
          and first["file"].fp.read(6) == b"GIF89a")
    check("슬롯: 🚨 도는 동안의 글에는 결과가 없다 (심볼·배당·잔액 어느 것도)",
          not first["embed"].fields and not any(s in fields(first["embed"]) for s in (D, "일치", "7배", "꽝", "100")),
          fields(first["embed"]))
    check(f"슬롯: 릴이 멈출 때까지 기다린다 ({art.slot_seconds(7):.2f}초 + 여유 {cas.SLOT_REVEAL_PAD}초)",
          slept == [art.slot_seconds(7) + cas.SLOT_REVEAL_PAD] and cas.SLOT_REVEAL_PAD >= 0.5, str(slept))
    check("슬롯: 끝나면 멈춘 그림 + 결과 글로 바뀐다",
          len(it.edits) == 1 and _names(last) == [cas.SLOT_FILE] and last["embed"].image.url == f"attachment://{cas.SLOT_FILE}"
          and "결과" in fields(last["embed"]) and "+30코인" in fields(last["embed"]) and D in fields(last["embed"])
          and last["attachments"][0].fp.read(3) == b"\xff\xd8\xff", fields(last["embed"]))

    art.slot_card = _no_art
    events.clear(), slept.clear()
    it = FakeInteraction()
    asyncio.run(cog.slot.callback(cog, it, 5))
    check("슬롯: 🚨 그림을 못 그리면 예전처럼 글 한 번 (기다림·교체 없음)",
          len(it.sent) == 1 and not _names(it.sent[0]) and not it.edits and not slept
          and "결과" in fields(it.sent[0]["embed"]) and not it.sent[0]["embed"].image.url)

    art.slot_card = spied(saved_cas[5])
    events.clear(), slept.clear()
    it = FakeInteraction(fail="art")
    asyncio.run(cog.slot.callback(cog, it, 5))
    check("슬롯: 🚨 GIF 전송이 실패하면 글만 다시 보낸다",
          len(it.sent) == 2 and _names(it.sent[0]) and not _names(it.sent[1])
          and "결과" in fields(it.sent[1]["embed"]) and not it.sent[1]["embed"].image.url and not slept)

    events.clear(), slept.clear()
    it = FakeInteraction()

    async def _edit_fails_with_art(**kw):
        it.edits.append(kw)
        if _names(kw):
            raise _http_error()
    it.edit_original_response = _edit_fails_with_art
    asyncio.run(cog.slot.callback(cog, it, 5))
    check("슬롯: 🚨 결과 그림으로 못 바꾸면 그림을 떼고 글만 고친다 (GIF가 남지 않는다)",
          len(it.edits) == 2 and it.edits[1]["attachments"] == [] and not it.edits[1]["embed"].image.url
          and "결과" in fields(it.edits[1]["embed"]))
    check("슬롯: 어느 경우든 정산은 한 번", sum(1 for e in events if e[0] == "pay_out") == 1)

    # ── 하이로우 ──
    games.roll_highlow = lambda choice: (83, 2, "**83** — 맞혔어요!")
    art.highlow_card = spied(saved_cas[6])
    events.clear()
    it = FakeInteraction()
    asyncio.run(cog.highlow.callback(cog, it, 5, "high"))
    e = it.sent[0]["embed"]
    check("하이로우: 정산 뒤에 그림 한 장이 붙는다", order("pay_out", "art", "send") and _names(it.sent[0]) == [cas.HIGHLOW_FILE]
          and e.image.url == f"attachment://{cas.HIGHLOW_FILE}" and "결과" in fields(e) and "# 83" not in fields(e))
    art.highlow_card = _no_art
    it = FakeInteraction()
    asyncio.run(cog.highlow.callback(cog, it, 5, "high"))
    e = it.sent[0]["embed"]
    check("하이로우: 🚨 그림이 없으면 예전 글(큰 숫자 줄 포함)", len(it.sent) == 1 and not _names(it.sent[0])
          and "# 83" in fields(e) and not e.image.url)
    art.highlow_card = spied(saved_cas[6])
    it = FakeInteraction(fail="art")
    asyncio.run(cog.highlow.callback(cog, it, 5, "high"))
    check("하이로우: 🚨 그림 붙인 전송이 실패하면 글만 다시", len(it.sent) == 2 and not _names(it.sent[1])
          and not it.sent[1]["embed"].image.url and "결과" in fields(it.sent[1]["embed"]))

    # ── 블랙잭 ──
    # 덱은 **뒤에서부터** 뽑아요: 나 [10, 5] · 딜러 [10, 6] → 히트 2 → 히트 2 → 딜러가 9를 뽑아 25
    def _deck():
        return [4, 4, 4, 9, 2, 2, 6, 10, 5, 10]
    games.new_deck = _deck
    art.blackjack_card = spied(saved_cas[7])
    events.clear()
    it = FakeInteraction()
    asyncio.run(cog.blackjack.callback(cog, it, 5))
    deal = it.sent[0]
    view = deal["view"]
    check("블랙잭: 판을 띄울 때 테이블 그림이 붙는다", _names(deal) == [cas.BJ_FILE]
          and deal["embed"].image.url == f"attachment://{cas.BJ_FILE}" and isinstance(view, cas.BlackjackView))
    check("블랙잭: 🚨 처음 글에 딜러 둘째 장(6)·합계(16)가 없다", "`6`" not in fields(deal["embed"]) and "16" not in fields(deal["embed"]),
          fields(deal["embed"]))
    check("블랙잭: 무늬가 카드 수만큼 정해졌다", (len(view.player_suits), len(view.dealer_suits)) == (2, 2))
    suits0 = list(view.player_suits)

    hit1 = FakeInteraction()
    hit1.view = view
    asyncio.run(view.hit.callback(hit1))
    check("블랙잭 히트: 그림을 새로 갈아 끼운다 (attachments에 새 그림 한 장)",
          len(hit1.edits) == 1 and _names(hit1.edits[0]) == [cas.BJ_FILE] and hit1.edits[0]["view"] is view
          and hit1.edits[0]["embed"].image.url == f"attachment://{cas.BJ_FILE}" and len(view.player) == 3)
    check("블랙잭 히트: 앞 카드의 무늬가 그대로다", view.player_suits[:2] == suits0 and len(view.player_suits) == 3)

    art.blackjack_card = _no_art
    hit2 = FakeInteraction()
    hit2.view = view
    asyncio.run(view.hit.callback(hit2))
    check("블랙잭 히트: 🚨 그림을 못 그리면 `attachments=[]`로 **지난 그림을 지운다** (한 장 전의 패가 남으면 안 돼요)",
          len(hit2.edits) == 1 and hit2.edits[0]["attachments"] == [] and not hit2.edits[0]["embed"].image.url
          and len(view.player) == 4)

    art.blackjack_card = spied(saved_cas[7])
    events.clear()
    stand = FakeInteraction()
    stand.view = view
    asyncio.run(view.stand.callback(stand))
    fin = stand.edits[-1]
    check("블랙잭 스탠드: 정산 → 그림 → 화면 순서, 정산은 한 번", order("defer", "pay_out", "art", "edit")
          and sum(1 for e in events if e[0] == "pay_out") == 1 and view.done, str([e[0] for e in events]))
    check("블랙잭 스탠드: 공개된 테이블 그림 + 결과 글 + 버튼 꺼짐",
          _names(fin) == [cas.BJ_FILE] and "결과" in fields(fin["embed"]) and "`6`" in fields(fin["embed"])
          and all(b.disabled for b in view.children) and len(view.dealer_suits) == len(view.dealer) == 3)
    late = FakeInteraction()
    late.view = view
    asyncio.run(view.hit.callback(late))
    check("블랙잭: 🚨 끝난 판에 늦게 온 히트는 아무것도 안 한다 (카드도 화면도)", len(view.player) == 4 and not late.edits)

    # 연타: 두 번의 히트가 겹쳐 들어와도 화면은 한 장씩 차례로 바뀌어야 해요.
    async def _double_click():
        v = cas.BlackjackView(None, 1, 5, [2, 2, 2, 2, 2], [2, 3], [10, 6])
        a, b = FakeInteraction(slow=0.03), FakeInteraction()
        a.view = b.view = v
        events.clear()
        await asyncio.gather(v.hit.callback(a), v.hit.callback(b))
        return [e[2] for e in events if e[0] == "edit"], v
    counts, v2 = asyncio.run(_double_click())
    check("블랙잭 연타: 🚨 화면이 손패 3장 → 4장 순서로 바뀐다 (뒤처진 판으로 덮이지 않는다)", counts == [3, 4], str(counts))

    # 타임아웃: 처음 띄운 메시지를 직접 고쳐요.
    events.clear()
    v3 = cas.BlackjackView(None, 1, 5, [9, 9, 9], [10, 5], [10, 6])
    v3.message = FakeMessage()
    asyncio.run(v3.on_timeout())
    check("블랙잭 타임아웃: 자동 정산하고 그림까지 갈아 끼운다",
          v3.done and sum(1 for e in events if e[0] == "pay_out") == 1 and len(v3.message.edits) == 1
          and _names(v3.message.edits[0]) == [cas.BJ_FILE])
    v4 = cas.BlackjackView(None, 1, 5, [9, 9, 9], [10, 5], [10, 6])
    v4.message = FakeMessage(fail_art=True)
    asyncio.run(v4.on_timeout())
    check("블랙잭: 🚨 그림 붙인 화면 고치기가 실패하면 그림을 떼고 한 번 더",
          len(v4.message.edits) == 2 and v4.message.edits[1]["attachments"] == []
          and not v4.message.edits[1]["embed"].image.url and "결과" in fields(v4.message.edits[1]["embed"]))

    def _raises(*_a, **_kw):
        raise RuntimeError("일부러 낸 오류")
    art.blackjack_card = _raises
    v5 = cas.BlackjackView(None, 1, 5, [9, 9, 9], [10, 5], [10, 6])
    check("블랙잭: 🚨 `table_art`는 무슨 일이 있어도 예외를 안 올린다 (판 여는 자리에서 터지면 코인만 빠져요)",
          asyncio.run(v5.table_art(reveal=False)) is None)
    art.blackjack_card = spied(saved_cas[7])

    # 처음부터 21 - 버튼 없이 바로 정산
    games.new_deck = lambda: [9, 9, 6, 10, 13, 1]
    events.clear()
    it = FakeInteraction()
    asyncio.run(cog.blackjack.callback(cog, it, 5))
    check("블랙잭 즉시 21: 정산 뒤 공개된 그림 한 장, 버튼 없음",
          order("pay_out", "art", "send") and _names(it.sent[0]) == [cas.BJ_FILE] and "view" not in it.sent[0]
          and "결과" in fields(it.sent[0]["embed"]))

    # 판을 못 띄우면 환불 (원래 있던 안전장치가 그림 뒤에도 살아 있는지)
    refunds = []

    async def _refund(uid, amount):
        refunds.append((uid, amount))
    saved_refund, cas.refund_bet = cas.refund_bet, _refund
    try:
        games.new_deck = _deck
        it = FakeInteraction(fail="view")
        asyncio.run(cog.blackjack.callback(cog, it, 5))
        check("블랙잭: 🚨 그림을 떼고도 판을 못 띄우면 코인·한도를 돌려준다",
              refunds == [(1, 5)] and len(it.sent) == 3 and _names(it.sent[0]) and not _names(it.sent[1]),
              f"{refunds} / 전송 {len(it.sent)}번")
        refunds.clear()
        it = FakeInteraction(fail="art")
        asyncio.run(cog.blackjack.callback(cog, it, 5))
        check("블랙잭: 그림 때문에만 실패한 거면 글만으로 판을 열고 환불하지 않는다",
              refunds == [] and len(it.sent) == 2 and isinstance(it.sent[1].get("view"), cas.BlackjackView)
              and not it.sent[1]["embed"].image.url)
    finally:
        cas.refund_bet = saved_refund

    # ── 현황 ──
    async def _state(_uid):
        return 20, 20

    async def _zero(_uid):
        return 0

    async def _bet_limit(_uid):
        return 5, 0

    async def _balance(_uid):
        return 33
    saved_store = (cas.casino_store.state_today, cas.casino_store.extend_count, cas.casino_store.bet_limit_today,
                   cas.coin_wallet.get_balance)
    cas.casino_store.state_today, cas.casino_store.extend_count = _state, _zero
    cas.casino_store.bet_limit_today, cas.coin_wallet.get_balance = _bet_limit, _balance
    try:
        it = FakeInteraction()
        asyncio.run(cog.status.callback(cog, it))
        s = it.sent[0]
        check("현황: 도박장 그림이 붙고 본인에게만 보인다 · 한도를 다 쓰면 🔓 버튼도 그대로",
              _names(s) == [cas.LOBBY_FILE] and s["ephemeral"] is True and isinstance(s.get("view"), cas.ExtendLimitView)
              and s["embed"].image.url == f"attachment://{cas.LOBBY_FILE}" and "환수율" in fields(s["embed"]))
        art.lobby_card = _no_art
        it = FakeInteraction()
        asyncio.run(cog.status.callback(cog, it))
        check("현황: 🚨 그림이 없어도 글은 나간다", len(it.sent) == 1 and not _names(it.sent[0])
              and "환수율" in fields(it.sent[0]["embed"]))
    finally:
        (cas.casino_store.state_today, cas.casino_store.extend_count, cas.casino_store.bet_limit_today,
         cas.coin_wallet.get_balance) = saved_store
finally:
    asyncio.sleep = _real_sleep
    logging.disable(logging.NOTSET)
    (cas.take_bet, cas.pay_out, games.spin_slot, games.roll_highlow, games.new_deck,
     art.slot_card, art.highlow_card, art.blackjack_card, art.lobby_card) = saved_cas

# 그림 파일 이름이 서로 달라야 해요(같으면 한 메시지에서 그림이 뒤바뀌어요).
file_names = [cas.SLOT_SPIN_FILE, cas.SLOT_FILE, cas.HIGHLOW_FILE, cas.BJ_FILE, cas.LOBBY_FILE]
check("첨부 이름 5개가 서로 다르고 확장자가 내용과 맞다",
      len(set(file_names)) == 5 and cas.SLOT_SPIN_FILE.endswith(".gif")
      and all(n.endswith(".jpg") for n in file_names[1:]), str(file_names))

print("\n" + ("✅ 전부 통과" if not fails else f"❌ 실패 {fails}건"))
sys.exit(1 if fails else 0)
