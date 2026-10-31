"""🔊 방 패널 — `/방만들기` 세트를 버튼으로 (2026-10-31).

## 왜 만들었나 (실측이 가설을 뒤집었다)

사용자 제안("방만들기 기능들이랑 사용하기 쉽게 버튼식으로 바꾸면 어떨까?")에서 나왔어요.
처음엔 `#🏆랭크-파티구인`의 "열어달라" 4건을 보고 **"명령어가 문턱"**이라고 봤는데,
감사 로그로 재보니 **틀렸어요** — `/방만들기`는 **41일간 119건(하루 2.9건)**으로 이미
활발히 쓰이고 있어요. 🪙상점(22일 0건)·💡건의함(0건)과는 상황이 완전히 달라요.

그래서 이 패널의 목표는 "더 많이 만들기"가 **아니에요.** 실측이 가리키는 건 둘이에요.

| 실측 (41일) | |
|---|---|
| 🔒 랭크방 | **96건 (81%)** |
| 🥋 폐관수련방 | 20건 |
| ⚔️ 내전방 | **3건** |
| 🏆 프리미어방 | **0건 — 한 번도 안 쓰임** |
| 정원을 정한 방 | **19/119 = 16%** |

① **안 쓰이는 종류의 발견성** — 프리미어 0건·내전 3건은 "있는 줄 모른다"에 가까워요.
   버튼으로 늘어놓으면 보여요.
② **딸린 기능 4개**(`/방초대`·`/방신청`·`/방장넘기기`·`/방닫기`)는 **사용량을 측정할
   길이 없어요**(채널 생성이 아니라 감사 로그에 안 남아요). "열어달라"가 혹시 *남의 방에
   들어가는 법을 모르는* 것이면 진짜 문턱은 여기예요.

정원은 **84%가 무제한**이라 버튼은 그냥 무제한으로 바로 만들고, 필요한 사람만
⚙️ 로 정해요. 그게 16%를 위해 전원에게 단계를 더하지 않는 길이에요.

## 🚨🚨 engine이 **자기 안에서 defer를 해요**

`DynamicRoomEngine.create_room`·`invite`·`request_join`·`transfer_owner`·`close_room`은
전부 첫 줄이 `await interaction.response.defer(ephemeral=True)`예요.
→ **패널에서 미리 defer하면 `InteractionResponded`로 터져요.** 🎴 카드 패널과 정반대예요
   (`do_fuse`는 defer가 끝나 있어야 했어요). `scripts/test_room_panel.py`가 이걸 봐요.

## 🚨 영속 뷰 3요소 (하나만 빠져도 재시작 뒤 버튼이 조용히 죽어요)
1. `timeout=None`
2. 버튼마다 고정 `custom_id` (`akgui:room:*`)
3. `cog_load`에서 `bot.add_view(RoomPanelView(engine))`

## 🚨 상태를 `self`에 담지 마세요 — 단 engine은 예외예요
이 뷰는 **봇 전체에 하나뿐**이라 모든 사람이 공유해요. 누른 사람은 `interaction.user`로만
알아내요. `self.engine`은 **사용자 상태가 아니라 서비스 참조**라 괜찮아요(없으면 영속
뷰에서 engine에 닿을 길이 없어요).

## 사람 고르기는 ephemeral 뷰로 (영속이 아니에요)
`/방초대 대상:@사람`처럼 Member를 받아야 하는 건 버튼만으로 안 돼요. 버튼을 누르면
**누른 사람에게만 보이는** `discord.ui.UserSelect` 한 줄을 띄우고, 고르는 순간 engine을
불러요. 이 뷰는 한 사람 한 번만 쓰고 버려지니 `self`에 담아도 안전해요.
"""
import logging

import discord

log = logging.getLogger(__name__)

# ⚙️ 정원 드롭다운에 올릴 값. 🚨 실측에서 정원을 정한 19건의 분포가 5·8·10 쪽이라
#    거기에 맞춰요(1~99를 다 늘어놓으면 드롭다운 한도 25를 넘어요).
CAPACITY_CHOICES = [2, 3, 4, 5, 6, 8, 10, 12, 16, 20]


class _PickMemberView(discord.ui.View):
    """사람 하나를 골라 engine 메서드에 넘기는 **일회용** ephemeral 뷰.

    ⚠️ 영속 뷰가 아니에요 — 누른 사람에게만 뜨고 3분 뒤 사라져요. 그래서 `self`에
       상태(engine·action)를 담아도 섞이지 않아요."""

    def __init__(self, engine, action: str, placeholder: str):
        super().__init__(timeout=180)
        self.engine = engine
        self.action = action
        select = discord.ui.UserSelect(placeholder=placeholder, min_values=1, max_values=1)
        select.callback = self._picked
        self.add_item(select)
        self._select = select

    async def _picked(self, interaction: discord.Interaction):
        member = self._select.values[0]
        # UserSelect는 Member가 아니라 User를 줄 수 있어요(길드 캐시에 없을 때).
        # engine들은 Member를 기대하니 길드에서 다시 찾아요.
        if not isinstance(member, discord.Member) and interaction.guild is not None:
            member = interaction.guild.get_member(member.id) or member

        # 🚨 여기서 defer하지 않아요 — engine이 자기 안에서 defer해요(위 docstring).
        if self.action == "invite":
            await self.engine.invite(interaction, member)
        elif self.action == "request":
            await self.engine.request_join(interaction, member)
        elif self.action == "transfer":
            await self.engine.transfer_owner(interaction, member)
        else:                                    # pragma: no cover - 방어
            log.warning("알 수 없는 방 패널 동작: %s", self.action)
            return
        self.stop()


class _OptionsView(discord.ui.View):
    """⚙️ 종류·정원·뮤트를 고른 뒤 만드는 **일회용** ephemeral 뷰.

    ⚠️ 모달(`send_modal`)로는 못 해요 — 모달엔 **텍스트 입력만** 들어가서 종류를
       글자로 받아야 하고, 그러면 오타가 바로 실패가 돼요. 드롭다운이 맞아요."""

    def __init__(self, engine, room_kinds: dict):
        super().__init__(timeout=180)
        self.engine = engine
        self.kind: str | None = None
        self.capacity: int | None = None
        self.mute = False

        self._kind_select = discord.ui.Select(
            placeholder="① 어떤 방을 만들까요?",
            options=[
                discord.SelectOption(label=cfg["label"], value=key, emoji=cfg["emoji"],
                                     description=cfg["choice_name"])
                for key, cfg in room_kinds.items()
            ],
            row=0,
        )
        self._kind_select.callback = self._pick_kind
        self.add_item(self._kind_select)

        self._cap_select = discord.ui.Select(
            placeholder="② 최대 인원 (안 고르면 무제한)",
            options=([discord.SelectOption(label="무제한", value="0")]
                     + [discord.SelectOption(label=f"{n}명", value=str(n))
                        for n in CAPACITY_CHOICES]),
            row=1,
        )
        self._cap_select.callback = self._pick_cap
        self.add_item(self._cap_select)

    async def _pick_kind(self, interaction: discord.Interaction):
        self.kind = self._kind_select.values[0]
        await interaction.response.edit_message(view=self)

    async def _pick_cap(self, interaction: discord.Interaction):
        value = int(self._cap_select.values[0])
        self.capacity = value or None
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="입장시 마이크 막기: 꺼짐", emoji="🔇",
                       style=discord.ButtonStyle.secondary, row=2)
    async def toggle_mute(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mute = not self.mute
        button.label = f"입장시 마이크 막기: {'켜짐' if self.mute else '꺼짐'}"
        button.style = (discord.ButtonStyle.primary if self.mute
                        else discord.ButtonStyle.secondary)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="이 설정으로 만들기", emoji="✅",
                       style=discord.ButtonStyle.success, row=3)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.kind is None:
            # 🚨 engine을 부르기 전에 막아요. 안 막으면 KeyError로 터져요.
            await interaction.response.send_message(
                "먼저 **① 어떤 방을 만들까요?** 에서 종류를 골라주세요.", ephemeral=True
            )
            return
        # 🚨 defer하지 않아요 — engine이 해요.
        await self.engine.create_room(interaction, self.kind, self.capacity, self.mute)
        self.stop()


class RoomPanelView(discord.ui.View):
    """🔊 통화방 패널. 위 모듈 docstring의 규칙을 반드시 지켜주세요."""

    def __init__(self, engine, room_kinds: dict):
        super().__init__(timeout=None)
        self.engine = engine
        self.room_kinds = room_kinds

        # 종류 버튼은 **ROOM_KINDS에서 만들어요.** 손으로 4개를 늘어놓으면 종류를
        # 추가했을 때 패널만 옛날 것으로 남아요(cogs/room.py 맨 위 설명과 같은 약속).
        for key, cfg in room_kinds.items():
            self.add_item(_CreateButton(key, cfg))

    @discord.ui.button(label="정원·뮤트 정해서 만들기", emoji="⚙️",
                       style=discord.ButtonStyle.secondary,
                       custom_id="akgui:room:options", row=1)
    async def options(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "⚙️ **정해서 만들기** — 종류를 고르고 ✅ 를 누르세요.\n"
            "-# 정원을 안 고르면 무제한이에요. 그냥 바로 만들려면 위 패널의 방 버튼을 누르세요.",
            view=_OptionsView(self.engine, self.room_kinds),
            ephemeral=True,
        )

    @discord.ui.button(label="내 방에 초대", emoji="👥",
                       style=discord.ButtonStyle.primary,
                       custom_id="akgui:room:invite", row=2)
    async def invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "👥 **내 방에 초대할 사람**을 고르세요. 고른 사람은 바로 입장할 수 있어요.",
            view=_PickMemberView(self.engine, "invite", "초대할 사람"),
            ephemeral=True,
        )

    @discord.ui.button(label="남의 방에 입장 신청", emoji="🙋",
                       style=discord.ButtonStyle.primary,
                       custom_id="akgui:room:request", row=2)
    async def request(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🙋 들어가고 싶은 방의 **방장**을 고르세요. 방장이 수락하면 입장할 수 있어요.",
            view=_PickMemberView(self.engine, "request", "그 방의 방장"),
            ephemeral=True,
        )

    @discord.ui.button(label="방장 넘기기", emoji="👑",
                       style=discord.ButtonStyle.secondary,
                       custom_id="akgui:room:transfer", row=3)
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "👑 **방장을 넘겨줄 사람**을 고르세요. 그 사람이 지금 방에 들어와 있어야 해요.",
            view=_PickMemberView(self.engine, "transfer", "방장을 넘길 사람"),
            ephemeral=True,
        )

    @discord.ui.button(label="내 방 닫기", emoji="🚪",
                       style=discord.ButtonStyle.danger,
                       custom_id="akgui:room:close", row=3)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 🚨 defer하지 않아요 — engine이 해요.
        await self.engine.close_room(interaction)


class _CreateButton(discord.ui.Button):
    """방 종류 하나를 **즉시** 만드는 버튼(정원 무제한·뮤트 없음).

    🚨 `custom_id`에 종류 키를 박아요(`akgui:room:new:rank`). 그래야 재시작 뒤에도
       어느 버튼인지 알아봐요."""

    def __init__(self, kind: str, cfg: dict):
        super().__init__(
            label=cfg["label"],
            emoji=cfg["emoji"],
            style=discord.ButtonStyle.success,
            custom_id=f"akgui:room:new:{kind}",
            row=0,
        )
        self.kind = kind

    async def callback(self, interaction: discord.Interaction):
        # 🚨 defer하지 않아요 — engine이 해요(모듈 docstring 참고).
        await self.view.engine.create_room(interaction, self.kind, None, False)


def _short_desc(cfg: dict) -> str:
    """`choice_name`에서 설명만 떼요.

    🚨 `choice_name`은 `"랭크방 (게임 랭크용)"`처럼 **label을 이미 품고 있어요.**
       그대로 쓰면 패널에 `랭크방 — 랭크방 (게임 랭크용)`으로 두 번 나와요
       (2026-10-31 게시 미리보기에서 잡았어요)."""
    name = cfg["choice_name"]
    if "(" in name and name.endswith(")"):
        return name[name.index("(") + 1:-1]
    return name.replace(cfg["label"], "").strip() or name


def panel_embed(room_kinds: dict) -> discord.Embed:
    """패널 설명. 🚨 종류 목록을 **손으로 적지 않아요** — ROOM_KINDS에서 만들어요."""
    lines = [f"{cfg['emoji']} **{cfg['label']}** — {_short_desc(cfg)}"
             for cfg in room_kinds.values()]
    embed = discord.Embed(
        title="🔊 통화방 만들기",
        description=(
            "버튼을 누르면 **나만의 통화방**이 바로 열려요. 남이 들어오려면 "
            "**초대**를 받거나 **입장 신청**을 해야 해요.\n\n"
            + "\n".join(lines)
            + "\n\n　└ 정원을 정하거나 **입장시 마이크 막기**를 쓰려면 ⚙️ 를 누르세요"
            "\n　└ 방에 아무도 없으면 **자동으로 닫혀요**"
        ),
        color=0x5865F2,
    )
    embed.set_footer(text="누른 사람에게만 보이는 답이 떠요 · 명령어로도 돼요 (/방만들기)")
    return embed
