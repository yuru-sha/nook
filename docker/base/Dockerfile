# ベースイメージ
FROM python:3.11-slim

# 必要なシステムパッケージのインストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        cron \
        tzdata \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# UVのインストール
RUN pip install --no-cache-dir uv

# 作業ディレクトリの作成
WORKDIR /app

# 環境変数の設定
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    PYTHONDONTWRITEBYTECODE=1

# タイムゾーンの設定
RUN ln -fs /usr/share/zoneinfo/Asia/Tokyo /etc/localtime
