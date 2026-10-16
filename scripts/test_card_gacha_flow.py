"""🎴 카드 뽑기 **cog 흐름** 검증 - 특히 코인 환불. 실제 DB·디스코드 없이 돌아가요.

`test_card_gacha.py`가 확률·천장 같은 '수학'을 본다면, 여기는 **돈이 오가는 순서**를 봐요.

🚨 왜 따로 만들었나: [[project_akgui_casino]]에서 "게임이 시작 못 하면 코인+한도 둘 다 환불"을
놓쳐 사고를 냈어요. 뽑기도 똑같은 모양이에요 - 코인을 먼저 깎고 그 다음에 저장하는데,
저장이 실패했을 때 되돌리지 않으면 **유저 코인이 그냥 증발**해요.

여기서 확인하는 것:
  1) 정상 뽑기: 코인이 정확히 PULL_PRICE만큼 줄고, 카드 3장이 들어온다
  2) 잔액 부족: 코인이 **1개도 안 줄고** 거절된다
  3) 동시 실행에 밀림(pull -> None): **전액 환불**된다
  4) 저장 중 예외: **전액 환불**된다
  5) 도감 완성(pull -> []): **전액 환불**된다
  6) 환불 로그가 `카드뽑기:환불`이라 경제 리포트가 발행으로 오인하지 않는다
  7) 결과 임베드에 등급·새 카드·잔액·천장 안내가 들어간다
  8) 레전드 완주자에게는 "확정까지 N장"을 띄우지 않는다 (지키지 못할 약속)
"""
import asyncio
import os
import sys

BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BOT_DIR)
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGODB_DB_NAME"] = "agwi_card_test"

from utils import card_store  # noqa: E402
from utils.card_data import CARDS  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ------------------------------------------------------------------
# 가짜 지갑 / 가짜 인터랙션
# ------------------------------------------------------------------
class FakeWallet:
    def __init__(self, balance=100):
        self.balance = balance
        self.log = []          # (kind, amount, reason)

    async def spend(self, user_id, amount, *, reason=""):
        if self.balance < amount:
            return False
        self.balance -= amount
        self.log.append(("spend", amount, reason))
        return True

    async def add(self, user_id, amount, *, reason=""):
        self.balance += amount
        self.log.append(("add", amount, reason))
        return self.balance

    async def get_balance(self, user_id):
        return self.balance


class FakeUser:
    id = 12345


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, *, embed=None, file=None, view=None, ephemeral=False):
        self.sent.append({"content": content, "embed": embed, "file": file,
                          "view": view, "ephemeral": ephemeral})


class FakeResponse:
    def __init__(self):
        self.deferred_ephemeral = None

    async def defer(self, *, ephemeral=False, thinking=False):
        self.deferred_ephemeral = ephemeral


class FakeInteraction:
    def __init__(self, channel_id=None, parent_id=None):
        self.user = FakeUser()
        self.followup = FakeFollowup()
        self.response = FakeResponse()
        self.channel_id = channel_id
        self.channel = type("Ch", (), {"parent_id": parent_id})()


def run(coro):
    return asyncio.run(coro)


import cogs.card_gacha as gacha  # noqa: E402
from utils.card_store import PULL_PRICE  # noqa: E402


def setup(balance=100, pull_result="normal", counts=None, since_legend=0):
    """가짜 지갑·스토어를 끼워넣고 (wallet, interaction)을 돌려줘요."""
    wallet = FakeWallet(balance)
    gacha.coin_wallet = wallet

    state_counts = dict(counts or {})

    async def fake_pull(user_id, n=3):
        if pull_result == "none":
            return None
        if pull_result == "empty":
            return []
        if pull_result == "raise":
            raise RuntimeError("저장 실패 재현")
        drawn, _ = card_store.draw_cards(state_counts, since_legend, n=n)
        for d in drawn:
            state_counts[d["key"]] = state_counts.get(d["key"], 0) + 1
        return drawn

    async def fake_get(user_id):
        return {"counts": state_counts, "draws": 0, "since_legend": since_legend}

    gacha.card_store.pull = fake_pull
    gacha.card_store.get_collection = fake_get
    # 이미지는 이 테스트의 관심사가 아니에요(렌더는 따로 눈으로 확인했어요).
    async def no_image(drawn):
        return None
    gacha.card_render.render_pull = no_image

    return wallet, FakeInteraction()


# ==================================================================
print("\n[1] 정상 뽑기")
wallet, inter = setup(balance=100)
run(gacha.do_pull(inter))
check("코인이 가격만큼 줄었다", wallet.balance == 100 - PULL_PRICE, f"잔액 {wallet.balance}")
check("환불 로그가 없다", not [l for l in wallet.log if l[0] == "add"])
sent = inter.followup.sent[0]
check("결과 임베드를 보냈다", sent["embed"] is not None)
check("뽑기 버튼이 같이 붙었다", sent["view"] is not None)

# ==================================================================
print("\n[2] 잔액 부족")
wallet, inter = setup(balance=PULL_PRICE - 1)
run(gacha.do_pull(inter))
check("코인이 그대로다", wallet.balance == PULL_PRICE - 1, f"잔액 {wallet.balance}")
check("아무 거래도 안 일어났다", not wallet.log)
check("안내 메시지가 ephemeral", inter.followup.sent[0]["ephemeral"] is True)
check("가격을 알려준다", str(PULL_PRICE) in (inter.followup.sent[0]["content"] or ""))

# ==================================================================
print("\n[3] 동시 실행에 밀림 -> 전액 환불")
wallet, inter = setup(balance=100, pull_result="none")
run(gacha.do_pull(inter))
check("잔액이 원래대로 돌아왔다", wallet.balance == 100, f"잔액 {wallet.balance}")
refunds = [l for l in wallet.log if l[0] == "add"]
check("환불이 1건 있다", len(refunds) == 1, str(refunds))
check("환불 금액이 가격과 같다", refunds and refunds[0][1] == PULL_PRICE)
check("환불이라고 안내했다", "돌려" in (inter.followup.sent[0]["content"] or ""))

# ==================================================================
print("\n[4] 저장 중 예외 -> 전액 환불")
wallet, inter = setup(balance=100, pull_result="raise")
run(gacha.do_pull(inter))
check("잔액이 원래대로 돌아왔다", wallet.balance == 100, f"잔액 {wallet.balance}")
check("환불 1건", len([l for l in wallet.log if l[0] == "add"]) == 1)
check("예외가 밖으로 안 샜다", len(inter.followup.sent) == 1)

# ==================================================================
print("\n[5] 도감 완성 -> 전액 환불")
wallet, inter = setup(balance=100, pull_result="empty")
run(gacha.do_pull(inter))
check("잔액이 원래대로 돌아왔다", wallet.balance == 100, f"잔액 {wallet.balance}")
check("환불 1건", len([l for l in wallet.log if l[0] == "add"]) == 1)

# ==================================================================
print("\n[6] 환불 로그가 경제 리포트를 속이지 않는가")
# 🚨 `카드뽑기:환불`은 kind=add예요. 리포트가 이걸 '발행'으로 세면 발행량이 부풀어요.
wallet, inter = setup(balance=100, pull_result="none")
run(gacha.do_pull(inter))
spend_reason = [l[2] for l in wallet.log if l[0] == "spend"][0]
refund_reason = [l[2] for l in wallet.log if l[0] == "add"][0]
check("소비 로그가 '카드뽑기'로 시작", spend_reason.startswith("카드뽑기"), spend_reason)
check("도박으로 시작하지 않는다 (리포트가 베팅으로 오인)", not spend_reason.startswith("도박"))
check("환불 로그가 '카드뽑기:환불'", refund_reason == "카드뽑기:환불", refund_reason)

sys.path.insert(0, os.path.join(BOT_DIR, "scripts"))
# 리포트의 분류기를 직접 불러서 실제로 'refund'로 갈리는지 확인해요.
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "_report_probe", os.path.join(BOT_DIR, "scripts", "report_economy.py")
)
# ⚠️ report_economy는 임포트하면 바로 DB에 붙어서 리포트를 찍어요. 그래서 모듈을 실행하지
#    않고 **소스에서 분류 규칙만** 떼어내 확인해요.
src = open(os.path.join(BOT_DIR, "scripts", "report_economy.py"), encoding="utf-8").read()
check("리포트에 REFUND_ADD가 있다", "REFUND_ADD" in src)
check("환불을 issue보다 먼저 거른다",
      src.index("REFUND_ADD)") < src.index('return "issue"'))
check("순소각에서 환불을 뺀다", 'total("burn") - refunded' in src)

# ==================================================================
print("\n[7][8] 결과 임베드 내용")
wallet, inter = setup(balance=100)
run(gacha.do_pull(inter))
embed = inter.followup.sent[0]["embed"]
names = [f.name for f in embed.fields]
check("도감·새카드·잔액 필드가 있다",
      set(names) == {"도감", "새 카드", "남은 코인"}, str(names))
check("천장 안내가 푸터에 있다", "레전드" in (embed.footer.text or ""), embed.footer.text)

# 레전드를 전부 모은 사람에게는 "확정까지 N장"을 띄우면 안 돼요 - 천장이 발동하지 않거든요.
legend_full = {c["key"]: 1 for c in CARDS["레전드"]}
wallet, inter = setup(balance=100, counts=legend_full, since_legend=99)
run(gacha.do_pull(inter))
footer = inter.followup.sent[0]["embed"].footer.text or ""
check("레전드 완주자에게 '확정까지'를 안 띄운다", "확정까지" not in footer, footer)
check("대신 완주를 축하한다", "전부 모으" in footer, footer)

# ==================================================================
print("\n[9] 결과를 누구에게 보여주는가 (뽑기방이면 공개)")
# ------------------------------------------------------------------
# 🚨 2026-10-17에 사용자가 발견한 문제예요. 버튼 결과를 무조건 본인에게만 보여줬더니,
#    뽑기방에서 `/카드뽑기`로 공개 뽑기를 한 뒤 **같은 메시지의 "한 번 더"를 누르면
#    그때부터 비공개**가 됐어요. 같은 자리, 같은 행동인데 첫 판만 보이는 모순이에요.
CARD_CH, OTHER_CH = 1560678667686912040, 1504865376960254044   # 뽑기방 / 출석체크
os.environ["CARD_CHANNEL_ID"] = str(CARD_CH)

check("뽑기방에서 누르면 공개",
      gacha._is_card_channel(FakeInteraction(channel_id=CARD_CH)) is True)
check("출석체크에서 누르면 비공개",
      gacha._is_card_channel(FakeInteraction(channel_id=OTHER_CH)) is False)
check("뽑기방 안의 스레드도 공개",
      gacha._is_card_channel(FakeInteraction(channel_id=999, parent_id=CARD_CH)) is True)

# 채널 지정이 아예 없으면 제한이 없는 상태 -> 결과도 전부 공개로 봐요.
os.environ.pop("CARD_CHANNEL_ID")
check("채널 지정이 없으면 공개로 본다",
      gacha._is_card_channel(FakeInteraction(channel_id=OTHER_CH)) is True)
os.environ["CARD_CHANNEL_ID"] = str(CARD_CH)

# ⚠️ `do_pull`을 직접 부르면 **버튼의 배선은 검증이 안 돼요**(플래그를 테스트가 직접
#    계산해 넘기게 되니까요). 그래서 진짜 `GachaButton.callback`을 호출해요 - 콜백이
#    다시 "무조건 ephemeral=True"로 돌아가면 여기서 잡혀요.
button = gacha.GachaButton(FakeUser.id)

wallet, _ = setup(balance=100)
inter = FakeInteraction(channel_id=CARD_CH)
run(button.callback(inter))
check("뽑기방 버튼 결과가 공개", inter.followup.sent[0]["ephemeral"] is False)
check("defer도 공개로 했다", inter.response.deferred_ephemeral is False)

wallet, _ = setup(balance=100)
inter = FakeInteraction(channel_id=OTHER_CH)
run(button.callback(inter))
check("다른 채널 버튼 결과는 본인에게만", inter.followup.sent[0]["ephemeral"] is True)
check("defer도 비공개로 했다", inter.response.deferred_ephemeral is True)

# 🚨 실패·환불 안내는 **장소와 무관하게 늘 본인에게만** 가야 해요.
wallet, _ = setup(balance=0)
inter = FakeInteraction(channel_id=CARD_CH)
run(gacha.do_pull(inter, ephemeral=False))
check("뽑기방이어도 잔액부족 안내는 본인에게만",
      inter.followup.sent[0]["ephemeral"] is True)

wallet, _ = setup(balance=100, pull_result="none")
inter = FakeInteraction(channel_id=CARD_CH)
run(gacha.do_pull(inter, ephemeral=False))
check("뽑기방이어도 환불 안내는 본인에게만",
      inter.followup.sent[0]["ephemeral"] is True)

# ==================================================================
print("\n[10] 연속뽑기")
# ------------------------------------------------------------------
import re  # noqa: E402

from utils.card_store import CARDS_PER_PULL, MAX_PULLS  # noqa: E402

# --- 비용과 장수 ---
wallet, inter = setup(balance=100)
run(gacha.do_pull(inter, pulls=5))
check("5연속은 50코인", wallet.balance == 50, f"잔액 {wallet.balance}")
spend = [l for l in wallet.log if l[0] == "spend"][0]
check("한 번에 전액 차감", spend[1] == 50, str(spend))
check("소비 로그에 횟수가 남는다", spend[2] == "카드뽑기x5", spend[2])
check("리포트가 여전히 '카드뽑기'로 집계", spend[2].startswith("카드뽑기"))

# --- 상한 ---
wallet, inter = setup(balance=1000)
run(gacha.do_pull(inter, pulls=99))
check(f"{MAX_PULLS}연속을 넘지 않는다",
      wallet.balance == 1000 - 10 * MAX_PULLS, f"잔액 {wallet.balance}")
wallet, inter = setup(balance=1000)
run(gacha.do_pull(inter, pulls=0))
check("0회를 넣어도 최소 1회", wallet.balance == 990, f"잔액 {wallet.balance}")

# --- 잔액 부족이면 한 푼도 안 나간다 ---
wallet, inter = setup(balance=30)
run(gacha.do_pull(inter, pulls=5))
check("5연속을 못 사면 차감이 없다", wallet.balance == 30, f"잔액 {wallet.balance}")
check("몇 연속까지 가능한지 알려준다", "3연속" in (inter.followup.sent[0]["content"] or ""),
      inter.followup.sent[0]["content"])

# --- 실패하면 전액 환불 (부분 환불이면 코인이 증발해요) ---
wallet, inter = setup(balance=100, pull_result="none")
run(gacha.do_pull(inter, pulls=5))
check("5연속 실패 시 50코인 전액 환불", wallet.balance == 100, f"잔액 {wallet.balance}")
refund = [l for l in wallet.log if l[0] == "add"][0]
check("환불액이 1회분이 아니라 전액", refund[1] == 50, str(refund))

# --- 🚨 옛 버튼이 죽지 않아야 해요 ---
# custom_id 패턴을 바꾸면 **이미 디스코드에 떠 있는 버튼**이 정규식에 안 맞아 무반응이 돼요
# (2026-09-29에 프로필 카드 버튼이 정확히 이렇게 죽었어요). 옛 형식도 계속 맞아야 해요.
# ⚠️ **discord.py가 실제로 쓰는 컴파일된 정규식**을 읽어야 해요. 여기에 직접 패턴을
#    적어두면 cog 쪽 template을 고쳐도 테스트는 통과해버려서 검증이 무의미해져요
#    (처음에 폴백 패턴을 넣었다가 그 상태였어요).
pattern = gacha.GachaButton.__discord_ui_compiled_template__
check("실제 컴파일된 템플릿을 읽었다", hasattr(pattern, "fullmatch"), str(type(pattern)))
old = pattern.fullmatch("gacha:pull:12345")
check("옛 custom_id가 여전히 매치된다", old is not None)
if old:
    check("옛 버튼은 1회로 해석", int(old["pulls"] or 1) == 1)
new = pattern.fullmatch("gacha:pull:12345:5")
check("새 custom_id도 매치된다", new is not None)
if new:
    check("새 버튼은 횟수를 읽는다", int(new["pulls"]) == 5 and new["user_id"] == "12345")

# 버튼 두 개가 실제로 1회·5회로 만들어지는지
view = gacha.GachaView(FakeUser.id)
pulls_on_view = sorted(i.pulls for i in view.children if isinstance(i, gacha.GachaButton))
check("뷰에 1회·5회 버튼이 있다", pulls_on_view == [1, gacha.QUICK_PULLS],
      str(pulls_on_view))
ids = [i.item.custom_id for i in view.children if isinstance(i, gacha.GachaButton)]
check("두 버튼의 custom_id가 다르다", len(set(ids)) == 2, str(ids))

# --- 5연 버튼을 실제로 눌러보기 ---
os.environ["CARD_CHANNEL_ID"] = str(CARD_CH)
wallet, _ = setup(balance=100)
inter = FakeInteraction(channel_id=CARD_CH)
run(gacha.GachaButton(FakeUser.id, 5).callback(inter))
check("5연 버튼이 50코인을 쓴다", wallet.balance == 50, f"잔액 {wallet.balance}")
check("5연 결과도 뽑기방에선 공개", inter.followup.sent[0]["ephemeral"] is False)

# ==================================================================
print("\n" + "=" * 60)
if failures:
    print(f"❌ 실패 {len(failures)}건")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 전부 통과")
