"""레벨업으로 새 기술을 배울 수 있을 때, 버튼으로 '배운다/배우지 않는다'를 묻고
슬롯이 꽉 찼으면 교체할 기술을 선택하게 해주는 UI예요."""
import discord

from utils.skill_data import MOVES
from utils.skill_store import collect_new_moves, get_current_skills, learn_skill, replace_skill


class LearnMoveView(discord.ui.View):
    def __init__(self, user_id: int, move_name: str, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.move_name = move_name
        self.decided = None  # "learn" / "skip" / None(타임아웃)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("본인만 선택할 수 있어요.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="배운다", style=discord.ButtonStyle.success)
    async def learn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.decided = "learn"
        self.stop()
        await interaction.response.edit_message(content=f"✅ **{self.move_name}**을(를) 배우기로 했어요!", view=None)

    @discord.ui.button(label="배우지 않는다", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.decided = "skip"
        self.stop()
        await interaction.response.edit_message(content=f"➡️ **{self.move_name}**을(를) 배우지 않았어요.", view=None)


class ReplaceMoveView(discord.ui.View):
    def __init__(self, user_id: int, new_move: str, current_moves: list, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.new_move = new_move
        self.chosen_old_move = None

        options = [discord.SelectOption(label=m, value=m) for m in current_moves]
        options.append(discord.SelectOption(label="배우지 않기", value="__skip__"))
        select = discord.ui.Select(placeholder="삭제할 기술을 선택하세요", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("본인만 선택할 수 있어요.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        self.chosen_old_move = None if value == "__skip__" else value
        self.stop()
        if self.chosen_old_move:
            await interaction.response.edit_message(
                content=f"🔄 **{self.chosen_old_move}** → **{self.new_move}**(으)로 교체했어요!", view=None
            )
        else:
            await interaction.response.edit_message(content=f"➡️ **{self.new_move}**을(를) 배우지 않았어요.", view=None)


def _move_summary(move_name: str) -> str:
    info = MOVES.get(move_name)
    if info is None:
        return move_name
    return f"{move_name} ({info['type']} · 위력 {info['power']} · 명중 {info['accuracy']} · {info['category']} · PP {info['pp']})"


async def prompt_new_moves(send, user_id: int, base_name: str, before_level: int, after_level: int):
    """레벨업 구간에서 새로 배울 수 있는 기술들을 순서대로 물어봐요.
    send는 (content=.., view=..) 를 받는 비동기 콜백이에요.
    (interaction.followup.send 또는 member.send를 그대로 넘기면 돼요)"""
    known_moves = get_current_skills(user_id)
    new_moves = collect_new_moves(base_name, before_level, after_level, known_moves)

    for move_name in new_moves:
        known_moves = get_current_skills(user_id)
        if move_name in known_moves:
            continue

        view = LearnMoveView(user_id, move_name)
        await send(
            content=f"🎉 새로운 기술을 배울 수 있어요!\n**{_move_summary(move_name)}**\n배우시겠어요?",
            view=view,
        )
        await view.wait()

        if view.decided != "learn":
            continue

        if learn_skill(user_id, move_name):
            continue

        current_moves = get_current_skills(user_id)
        replace_view = ReplaceMoveView(user_id, move_name, current_moves)
        await send(
            content=(
                f"기술은 최대 4개까지만 가질 수 있어요.\n"
                f"현재 기술: {', '.join(current_moves)}\n"
                f"새로운 기술 **{move_name}**을(를) 배우려면 기존 기술 하나를 삭제해야 해요."
            ),
            view=replace_view,
        )
        await replace_view.wait()

        if replace_view.chosen_old_move:
            replace_skill(user_id, replace_view.chosen_old_move, move_name)