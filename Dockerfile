FROM python:3.12-slim

WORKDIR /app

# システム依存パッケージ
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python依存パッケージ
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリコード
COPY . .

# ポート公開
EXPOSE 8000

# 起動
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
