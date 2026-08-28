"""
라이엇 로그인 세션 쿠키를 암호화해서 저장하기 위한 대칭키 암복호화 유틸이에요.
비밀번호는 절대 저장하지 않고, 이미 로그인된 세션을 이어가기 위한 쿠키 값만
암호화해서 보관해요. .env의 RIOT_SESSION_KEY로 암복호화해요.

⚠️ RIOT_SESSION_KEY를 바꾸면 기존에 저장해둔 세션을 전부 복호화하지 못하게 돼요.
"""
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

_key = os.environ.get("RIOT_SESSION_KEY")
_fernet = Fernet(_key.encode()) if _key else None


def encrypt(value: str) -> str:
    if not _fernet:
        raise RuntimeError("RIOT_SESSION_KEY가 설정되지 않았어요(.env 확인).")
    return _fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> Optional[str]:
    if not _fernet:
        return None
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        return None
