"""채널 제한(`/채널설정`) 해석 규칙 회귀 테스트.

    python scripts/test_channel_check.py

특히 **그룹을 새로 쪼갰을 때**(`/내전전적`을 profile → scrim_record로) 설정 전에
"아무 채널에서나 됨"으로 풀리지 않는지 봐요.
⚠️ 실제 `data/settings.json`을 건드리지 않게 임시 디렉터리로 바꿔치기해서 돌려요.
"""
import os
import sys
import tempfile
from pathlib import Path

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from utils import settings_store  # noqa: E402

_tmp = tempfile.TemporaryDirectory()
settings_store.DATA_DIR = _tmp.name
settings_store.FILE_PATH = os.path.join(_tmp.name, "settings.json")

from utils.channel_check import channel_key, get_allowed_channel_id  # noqa: E402

passed = failed = 0
PROFILE_CH = 1554515180191228067   # #프로필
SCRIM_CH = 1555974445670211635     # #내전전적


def check(label, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}\n     기대: {want}\n     실제: {got}")


print("아무것도 설정 안 했을 때")
check("제한 없음(None)", get_allowed_channel_id("scrim_record"), None)
check("폴백 그룹도 비었으면 None",
      get_allowed_channel_id("scrim_record", fallback_group="profile"), None)

print("\n그룹을 쪼갠 직후 (profile만 설정돼 있음)")
settings_store.set_setting(channel_key("profile"), PROFILE_CH)
check("scrim_record 단독으로는 여전히 None",
      get_allowed_channel_id("scrim_record"), None)
check("🚨 폴백을 주면 프로필 채널을 물려받음 (아무 채널에서나 되지 않아요)",
      get_allowed_channel_id("scrim_record", fallback_group="profile"), PROFILE_CH)
check("profile 자신은 그대로", get_allowed_channel_id("profile"), PROFILE_CH)

print("\n/채널설정으로 내전전적 채널을 지정한 뒤")
settings_store.set_setting(channel_key("scrim_record"), SCRIM_CH)
check("자기 설정이 폴백보다 우선",
      get_allowed_channel_id("scrim_record", fallback_group="profile"), SCRIM_CH)
check("프로필은 영향 없음", get_allowed_channel_id("profile"), PROFILE_CH)
check("둘이 서로 다른 채널", SCRIM_CH != PROFILE_CH, True)

print("\n.env 기본값 (설정이 없을 때만 써요)")
os.environ["TEST_CH_ENV"] = "12345"
check("설정이 없으면 .env를 씀",
      get_allowed_channel_id("nothing_set", "TEST_CH_ENV"), 12345)
check("설정이 있으면 .env보다 설정이 우선",
      get_allowed_channel_id("scrim_record", "TEST_CH_ENV"), SCRIM_CH)
check(".env가 폴백보다 먼저",
      get_allowed_channel_id("nothing_set", "TEST_CH_ENV", "profile"), 12345)
os.environ["TEST_CH_ENV"] = "숫자아님"
check("숫자가 아니면 무시",
      get_allowed_channel_id("nothing_set", "TEST_CH_ENV"), None)
del os.environ["TEST_CH_ENV"]
check("없는 환경변수면 None", get_allowed_channel_id("nothing_set", "NOPE_ENV"), None)

print("\n문자열로 저장돼 있어도 숫자로 돌려줘요 (손으로 고친 파일 대비)")
settings_store.set_setting(channel_key("as_text"), "999888777")
check("int로 변환", get_allowed_channel_id("as_text"), 999888777)

_tmp.cleanup()
print(f"\n{passed}개 통과, {failed}개 실패")
sys.exit(1 if failed else 0)
