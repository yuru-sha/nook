# nook/functions/tech_feed/test_tech_feed.py
import os
import sys

from dotenv import load_dotenv  # 環境変数を読み込むために追加

# プロジェクトルートをモジュール検索パスに追加
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from nook.functions.tech_feed.tech_feed import TechFeed

if __name__ == "__main__":
    # .envファイルを読み込む
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

    tech_feed = TechFeed()
    tech_feed()
