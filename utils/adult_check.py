"""🔞 성인 역할 판정 한 곳.

## 왜 모듈로 뺐나 (2026-10-23)

🎰 **도박 미션**(`play_gamble`)을 넣으면서 `mission_store`도 "이 사람이 성인인가"를
알아야 했어요. 그런데 판정 함수는 `cogs/casino.py`에 있었고, 거기서 가져오면
`mission -> casino -> mission` 순환 import가 돼요(도박 쪽에서도 미션 훅을 불러야
하니까요). 그래서 **판정만** 여기로 옮기고 양쪽이 이걸 같이 봐요.

🚨 **네 번째 상수를 만들지 마세요.** `ADULT_ROLE_ID`를 읽는 곳은 여기와
`cogs/adult_verify.py`(역할을 **부여**하는 쪽) 둘뿐이어야 해요. 세 벌이 되면 한쪽만
고쳐서 "도박은 막히는데 미션은 배정되는" 식으로 어긋나요.
"""
import os

import discord

# cogs/adult_verify.py와 **같은** 환경변수예요. 여기서 새 이름을 만들면 둘이 어긋나요.
ADULT_ROLE_ID = os.getenv("ADULT_ROLE_ID")


def is_adult(user: discord.abc.User | discord.Member | None) -> bool:
    """성인 역할이 있는지. 🚨 **모르면 False**예요 (막는 쪽으로).

    ⚠️ 판정 기준을 바꾸면 도박 잠금과 도박 미션 배정이 **같이** 바뀌어요. 그게 의도예요 —
    "미션은 받았는데 명령어가 막힌다"가 제일 나쁜 조합이거든요.
    """
    if not isinstance(user, discord.Member):
        return False          # DM이면 서버 역할을 못 봐요
    if user.guild_permissions.administrator:
        return True           # 운영진은 통과 (역할 설정이 꼬여도 잠기지 않게)
    if not ADULT_ROLE_ID:
        return False          # ⚠️ 설정이 없으면 막는 쪽으로. 열어주면 미성년자가 통과해요.
    return any(str(role.id) == ADULT_ROLE_ID for role in user.roles)
