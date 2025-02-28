import inspect
import os
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import boto3
import feedparser
import requests
import tomllib
from botocore.exceptions import ClientError
from bs4 import BeautifulSoup
from gemini_client import create_client

_MARKDOWN_FORMAT = """
# {title}

[View on {feed_name}]({url})

{summary}
"""


class Config:
    tech_feed_max_entries_per_day = 10
    summary_index_s3_key_format = "tech_feed/{date}.md"
    threshold_days = 1

    @classmethod
    def load_feeds(cls) -> dict[str, str]:
        """Load feed URLs from feed.toml file."""
        feed_toml_path = os.path.join(os.path.dirname(__file__), "feed.toml")
        with open(feed_toml_path, "rb") as f:
            feed_data = tomllib.load(f)

        # Create a dictionary mapping feed names to URLs
        feeds = {}
        for feed in feed_data.get("feeds", []):
            feeds[feed["name"]] = feed["url"]

        return feeds


@dataclass
class Article:
    feed_name: str
    title: str
    url: str
    text: str
    soup: BeautifulSoup
    category: str | None = field(default=None)
    summary: list[str] = field(init=False)


class TechFeed:
    def __init__(self) -> None:
        self._client = create_client()
        self._s3 = boto3.client("s3")
        self._bucket_name = os.environ["BUCKET_NAME"]
        self._tech_feed_urls = Config.load_feeds()
        self._threshold = datetime.now() - timedelta(days=Config.threshold_days)

    def __call__(self) -> None:
        markdowns = []
        for feed_name, feed_url in self._tech_feed_urls.items():
            feed_parser: feedparser.FeedParserDict = feedparser.parse(feed_url)
            entries = self._filter_entries(feed_parser)
            if len(entries) > Config.tech_feed_max_entries_per_day:
                entries = entries[: Config.tech_feed_max_entries_per_day]

            for entry in entries:
                article = self._retrieve_article(entry, feed_name=feed_name)
                article.summary = self._summarize_article(article)
                markdowns.append(self._stylize_article(article))
                time.sleep(2)
        self._store_summaries(markdowns)

    def _filter_entries(
        self, feed_parser: feedparser.FeedParserDict
    ) -> list[dict[str, Any]]:
        filtered_entries = []
        for entry in feed_parser["entries"]:
            date_ = entry.get("date_parsed")
            if not date_:
                continue
            published_dt = datetime.fromtimestamp(time.mktime(date_))
            if published_dt > self._threshold:
                filtered_entries.append(entry)
        return filtered_entries

    def _retrieve_article(self, entry: dict[str, Any], feed_name: str) -> Article:
        try:
            response = requests.get(entry.link)
            soup = BeautifulSoup(response.text, "html.parser")
            text = "\n".join(
                [
                    p.get_text()
                    for p in soup.find_all(
                        ["p", "code", "ul", "h1", "h2", "h3", "h4", "h5", "h6"]
                    )
                ]
            )
            return Article(
                feed_name=feed_name,
                title=entry.title,
                url=entry.link,
                text=text,
                soup=soup,
            )
        except Exception as e:
            raise Exception(f"Error raised while retrieving article: {e}") from e

    def _store_summaries(self, summaries: list[str]) -> None:
        date_str = date.today().strftime("%Y-%m-%d")
        key = Config.summary_index_s3_key_format.format(date=date_str)
        content = "\n---\n".join(summaries)
        try:
            self._s3.put_object(
                Bucket=self._bucket_name,
                Key=key,
                Body=content,
            )
        except ClientError as e:
            print(f"Error putting object {key} into bucket {self._bucket_name}.")
            print(e)

    def _stylize_article(self, article: Article) -> str:
        return _MARKDOWN_FORMAT.format(
            title=article.title,
            feed_name=article.feed_name,
            url=article.url,
            summary=article.summary,
        )

    def _summarize_article(self, article: Article) -> str:
        return self._client.generate_content(
            contents=self._contents_format.format(
                title=article.title, text=article.text
            ),
            system_instruction=self._system_instruction,
        )

    @property
    def _system_instruction(self) -> str:
        return inspect.cleandoc(
            """
            ユーザーから記事のタイトルと文章が与えられるので、内容をよく読み、日本語で詳細な要約を作成してください。
            与えられる文章はHTMLから抽出された文章なので、一部情報が欠落していたり、数式、コード、不必要な文章などが含まれている場合があります。
            要約以外の出力は不要です。
            """
        )

    @property
    def _contents_format(self) -> str:
        return inspect.cleandoc(
            """
            {title}

            本文:
            {text}
            """
        )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    print(event)

    try:
        if event.get("source") == "aws.events":
            tech_feed_ = TechFeed()
            tech_feed_()

        return {"statusCode": 200}
    except Exception as e:
        print(traceback.format_exc())
        print(e)
        return {"statusCode": 500}
