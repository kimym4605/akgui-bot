FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libopus0 \
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
