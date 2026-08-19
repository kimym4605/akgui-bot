"""기술 조회를 담당해요. 유저의 moves 배열(최대 4개)을 읽어요."""
from utils.pokemon_store import get_trainer
from utils.skill_data import get_learnset


def get_current_skills(user_id: int) -> list:
    """현재 보유 기술 목록을 반환해요."""
    trainer = get_trainer(user_id)
    if trainer is None:
        return []
    trainer.setdefault("moves", [])
    return trainer["moves"]


def get_learnable_skills(base_name: str, level: int) -> list:
    """해당 계열이 정확히 그 레벨에서 배울 수 있는 기술 목록을 반환해요."""
    learnset = get_learnset(base_name)
    return learnset.get(str(level), [])

