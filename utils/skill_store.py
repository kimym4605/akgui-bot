"""기술 습득/조회/교체를 담당해요. 유저의 moves 배열(최대 4개)을 관리해요."""
from utils.pokemon_store import get_trainer, save_trainer
from utils.skill_data import get_learnset

MAX_MOVES = 4


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


def collect_new_moves(base_name: str, from_level: int, to_level: int, known_moves: list) -> list:
    """from_level 초과 ~ to_level 이하 구간에서 새로 배울 수 있는 기술들을
    레벨 오름차순으로 모아요. 이미 알고 있는 기술은 제외해요."""
    learnset = get_learnset(base_name)
    new_moves = []
    for lvl in range(from_level + 1, to_level + 1):
        for move in learnset.get(str(lvl), []):
            if move not in known_moves and move not in new_moves:
                new_moves.append(move)
    return new_moves


def learn_skill(user_id: int, skill_name: str) -> bool:
    """포켓몬에게 기술을 추가해요. 슬롯이 이미 4개 꽉 찼으면 실패(False)해요."""
    trainer = get_trainer(user_id)
    if trainer is None:
        return False
    trainer.setdefault("moves", [])
    if len(trainer["moves"]) >= MAX_MOVES or skill_name in trainer["moves"]:
        return False
    trainer["moves"].append(skill_name)
    save_trainer(user_id, trainer)
    return True


def replace_skill(user_id: int, old_skill: str, new_skill: str) -> bool:
    """기존 기술 하나를 삭제하고 새 기술로 교체해요."""
    trainer = get_trainer(user_id)
    if trainer is None:
        return False
    trainer.setdefault("moves", [])
    if old_skill not in trainer["moves"]:
        return False
    idx = trainer["moves"].index(old_skill)
    trainer["moves"][idx] = new_skill
    save_trainer(user_id, trainer)
    return True