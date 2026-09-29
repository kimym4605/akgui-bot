FROM python:3.12-slim

# fonts-nanum은 악귀 프로필 카드(utils/profile_card.py)가 쓰는 한글 폰트예요.
# ⚠️ 이 이미지(python:3.12-slim)에는 폰트가 하나도 없어서, 빼면 카드의 한글이
#    전부 두부(□)로 나와요. Pillow만 깔고 끝내면 안 돼요.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libopus0 fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 버전이 == 로 고정돼 있어서, 이 레이어는 requirements.txt가 바뀔 때만 다시 돌아요(빠름).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ★ yt-dlp만 일부러 `COPY . .` **뒤에** 둬요.
#
# 유튜브가 추출 방식을 자주 바꿔서 yt-dlp는 낡으면 노래방이 깨지는데,
# requirements.txt에 같이 적어두면 도커 캐시에 얼어붙어 오히려 업데이트가 안 됐어요.
# 여기 두면 코드가 한 줄이라도 바뀔 때마다 이 레이어가 무효화돼서,
# 배포할 때마다 자동으로 최신 yt-dlp가 들어가요. (플래그 챙길 필요 없음)
RUN pip install --no-cache-dir --upgrade yt-dlp \
    && python -c "import yt_dlp; print('설치된 yt-dlp:', yt_dlp.version.__version__)"

CMD ["python", "-u", "bot.py"]
