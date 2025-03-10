# ビルドステージ
FROM nook-base:latest AS builder

# 作業ディレクトリの設定
WORKDIR /app

# 依存関係ファイルのコピー
COPY requirements.txt ./

# UVのインストールと依存関係のインストール
RUN uv pip install --no-cache --system -r requirements.txt && \
    find /usr/local -type d -name __pycache__ -exec rm -r {} + && \
    find /usr/local -type f -name "*.pyc" -delete

# 実行用のステージ
FROM nook-base:latest

# 作業ディレクトリの設定
WORKDIR /app

# Pythonパッケージとコマンドをビルダーステージからコピー
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# アプリケーションのコピー
COPY . .

# 環境変数の設定
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    PYTHONDONTWRITEBYTECODE=1

# タイムゾーンの設定
RUN ln -fs /usr/share/zoneinfo/Asia/Tokyo /etc/localtime

# アプリケーションの実行
CMD ["python", "nook/functions/viewer/viewer.py"]
