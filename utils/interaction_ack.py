"""🚨 상호작용을 **3초 안에** 받아두는 한 줄.

## 왜 있나

디스코드 상호작용 토큰은 **첫 응답까지 3초**다. 넘기면 `404 Unknown interaction`
(error code `10062`)으로 터지고, 유저에게는 "앱이 응답하지 않았습니다"만 남는다.

🚨 **진짜 피해는 404가 아니라 그 순서다.** 코인을 먼저 빼고 응답을 나중에 하면,
응답이 실패했을 때 **유저는 화면도 못 보고 코인만 잃는다.** 2026-10-17에 🎣 낚시
다시던지기가 정확히 이걸로 터졌다(내구도는 깎이고 화면은 안 뜸).

⭐ `defer()`로 한 번 받아두면 그 뒤로는 **15분짜리 웹훅 토큰**이 되어, Atlas가
얼마나 느리든(지금 봇은 메모리가 포화라 자주 느리다) 안전하게 고쳐 쓸 수 있다.

## 쓰는 법 - 핸들러의 **첫 줄**에서

```python
async def buy(self, interaction, button):
    if not await ack(interaction, ephemeral=True, thinking=True):
        return                      # 🚨 받지 못했으면 코인을 건드리기 전에 빠져나와요
    if not await coin_wallet.spend(...):
        ...
    await interaction.followup.send("샀어요", ephemeral=True)
```

| 상황 | 인자 | 그 뒤에 쓸 것 |
|---|---|---|
| 버튼/선택 - **화면을 그대로 두고** 받기 | `ack(it)` | `edit_original_response` |
| 버튼/선택 - **새 비공개 메시지**를 띄울 때 | `ack(it, ephemeral=True, thinking=True)` | `followup.send(ephemeral=True)` |
| 슬래시 명령 | `ack(it, ephemeral=True)` | `followup.send` 또는 `edit_original_response` |

⚠️ **슬래시 명령에 인자 없는 `ack(it)`를 쓰면 안 된다.** 컴포넌트 전용인
`deferred_message_update`를 쓸 수 없어서 "생각 중"이 **채널에 공개로** 남는다.

⚠️ 받아둔 뒤에는 `interaction.response.*`를 다시 쓸 수 없다(이미 응답한 상태다).
`followup.send` 또는 `edit_original_response`를 쓴다. 컴포넌트에서도
`edit_original_response`는 **버튼이 달려 있던 메시지**를 가리킨다.

-> [[reference_discord_interaction_3s_token]]
"""
import logging

import discord

log = logging.getLogger("akgui")


async def ack(interaction: discord.Interaction, *,
              ephemeral: bool = False, thinking: bool = False) -> bool:
    """상호작용을 먼저 받아둬요. 받았으면 `True`, 토큰이 죽었으면 `False`.

    🚨 `False`면 **자원(코인·내구도·재고)을 건드리기 전에 그냥 빠져나오세요.**
    화면을 띄울 수 없는 상황에서 코인만 빼는 게 제일 나쁜 결과예요.

    인자는 `discord.InteractionResponse.defer`와 같아요(위 표 참고)."""
    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=thinking)
        return True
    except discord.HTTPException:
        # ⚠️ 여기선 followup도 못 써요(토큰 자체가 죽었어요). 로그만 남겨요.
        log.warning("상호작용을 받지 못했어요 (user=%s type=%s)",
                    getattr(interaction.user, "id", "?"), interaction.type)
        return False
