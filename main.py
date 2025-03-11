# main.py
import os

from dotenv import load_dotenv

from nook.functions.github_trending.github_trending import GithubTrending
from nook.functions.hacker_news.hacker_news import HackerNewsRetriever
from nook.functions.paper_summarizer.paper_summarizer import PaperSummarizer
from nook.functions.reddit_explorer.reddit_explorer import RedditExplorer
from nook.functions.tech_feed.tech_feed import TechFeed


def run_all():
    # 環境変数の読み込み
    load_dotenv()

    # 出力ディレクトリを設定（環境変数がなければデフォルト）
    OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./output")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.environ["OUTPUT_DIR"] = OUTPUT_DIR

    # NOOK_TYPEに基づいて処理を分岐
    NOOK_TYPE = os.environ.get("NOOK_TYPE", "default")

    if NOOK_TYPE == "camera":
        print("Running Nook Camera collectors...")
        handlers = [
            RedditExplorer(),
            TechFeed(),
        ]
    else:
        print("Running Nook collectors...")
        handlers = [
            PaperSummarizer(),
            HackerNewsRetriever(),
            RedditExplorer(),
            GithubTrending(),
            TechFeed(),
        ]

    for handler in handlers:
        print(f"Running {handler.__class__.__name__}...")
        handler()
        print(f"Completed {handler.__class__.__name__}")


if __name__ == "__main__":
    run_all()
