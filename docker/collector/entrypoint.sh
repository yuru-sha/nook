#!/bin/bash

# 環境変数をcronに渡すための設定
env | grep -v "PATH\|HOSTNAME\|HOME\|PWD" > /etc/environment

# cronサービスを起動
service cron start

# 初回実行（オプション）
echo "初回データ収集を実行します..."
cd /app && python main.py

# ログを表示し続ける
tail -f /var/log/cron.log