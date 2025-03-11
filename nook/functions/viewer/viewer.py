# nook/functions/viewer/viewer.py
import os
import re
from datetime import datetime
from enum import Enum

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from nook.functions.common.python.gemini_client import create_client

app = FastAPI()
# テンプレートディレクトリを絶対パスで指定
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

# NOOK_TYPEに基づいてアプリ名とタイトルを設定
NOOK_TYPE = os.environ.get("NOOK_TYPE", "default")


class NookType(str, Enum):
    """Nookのタイプを定義するEnum"""

    DEFAULT = "default"
    CAMERA = "camera"


def get_app_names(nook_type: NookType) -> list[str]:
    """
    指定されたNookタイプに応じたアプリ名のリストを返す。

    Parameters
    ----------
    nook_type : NookType
        Nookのタイプ

    Returns
    -------
    list[str]
        アプリ名のリスト
    """
    if nook_type == NookType.CAMERA:
        return [
            "reddit_explorer",
            "tech_feed",
        ]
    else:
        return [
            "github_trending",
            "hacker_news",
            "paper_summarizer",
            "reddit_explorer",
            "tech_feed",
        ]


def get_app_title(nook_type: NookType) -> str:
    """
    指定されたNookタイプに応じたアプリタイトルを返す。

    Parameters
    ----------
    nook_type : NookType
        Nookのタイプ

    Returns
    -------
    str
        アプリタイトル
    """
    return "Nook Camera" if nook_type == NookType.CAMERA else "Nook"


WEATHER_ICONS = {
    "100": "☀️",
    "101": "🌤️",
    "200": "☁️",
    "201": "⛅",
    "202": "🌧️",
    "300": "🌧️",
    "301": "🌦️",
    "400": "🌨️",
}


def get_weather_data():
    try:
        response = requests.get(
            "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json", timeout=5
        )
        response.raise_for_status()
        data = response.json()
        tokyo = next(
            (
                area
                for area in data[0]["timeSeries"][2]["areas"]
                if area["area"]["name"] == "東京"
            ),
            None,
        )
        tokyo_weather = next(
            (
                area
                for area in data[0]["timeSeries"][0]["areas"]
                if area["area"]["code"] == "130010"
            ),
            None,
        )
        if tokyo and tokyo_weather:
            temps = tokyo["temps"]
            weather_code = tokyo_weather["weatherCodes"][0]
            weather_icon = WEATHER_ICONS.get(weather_code, "")
            return {
                "temp": temps[0],
                "weather_code": weather_code,
                "weather_icon": weather_icon,
            }
    except Exception as e:
        print(f"Error fetching weather data: {e}")
    return {
        "temp": "--",
        "weather_code": "100",
        "weather_icon": WEATHER_ICONS.get("100", "☀️"),
    }


def extract_links(text: str) -> list[str]:
    markdown_links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text)
    markdown_links = [
        (text, url)
        for text, url in markdown_links
        if not text.startswith("[Image]") and not text.startswith("[Video]")
    ]
    urls = re.findall(r"(?<![\(\[])(https?://[^\s\)]+)", text)
    return [url for _, url in markdown_links] + urls


def fetch_url_content(url: str) -> str | None:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["script", "style", "nav", "header", "footer"]):
            element.decompose()
        main_content = soup.find("article") or soup.find("main") or soup.find("body")
        if main_content:
            text = " ".join(main_content.get_text(separator=" ").split())
            return text[:1000] + "..." if len(text) > 1000 else text
        return None
    except Exception as e:
        print(f"Error fetching URL {url}: {e}")
        return None


def fetch_markdown(
    app_name: str, date_str: str, nook_type: NookType = NookType.DEFAULT
) -> str:
    """
    指定されたアプリ名と日付のマークダウンファイルを取得する。

    Parameters
    ----------
    app_name : str
        アプリ名
    date_str : str
        日付文字列（YYYY-MM-DD形式）
    nook_type : NookType
        Nookのタイプ（デフォルトはDEFAULT）

    Returns
    -------
    str
        マークダウンの内容
    """
    output_dir = os.environ.get("OUTPUT_DIR", "./output")
    key = f"{nook_type.value}/{app_name}/{date_str}.md"
    file_path = os.path.join(output_dir, key)
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
            print(f"Fetched markdown for {key}:")
            print(content[:500])
            return content
    except Exception as e:
        return f"Error fetching {key}: {e}"


@app.get("/")
async def root():
    """ルートパスへのアクセスをデフォルトタイプにリダイレクト"""
    return RedirectResponse(url="/default")


@app.get("/{nook_type}", response_class=HTMLResponse)
async def index(request: Request, nook_type: str):
    """
    指定されたタイプのNookのインデックスページを表示。

    Parameters
    ----------
    request : Request
        リクエストオブジェクト
    nook_type : str
        Nookのタイプ（"default" または "camera"）

    Returns
    -------
    HTMLResponse
        インデックスページのHTML
    """
    try:
        nook_type_enum = NookType(nook_type.lower())
    except ValueError:
        return RedirectResponse(url="/default")

    app_names = get_app_names(nook_type_enum)
    app_title = get_app_title(nook_type_enum)
    weather_data = get_weather_data()

    # クエリパラメータから日付を取得、なければ今日の日付を使用
    date_str = request.query_params.get("date", datetime.now().strftime("%Y-%m-%d"))

    # 各アプリのマークダウンコンテンツを取得
    contents = {}
    for app_name in app_names:
        contents[app_name] = fetch_markdown(app_name, date_str, nook_type_enum)

    # タブ名を設定
    tab_names = {
        "github_trending": "GitHub Trending",
        "hacker_news": "Hacker News",
        "paper_summarizer": "Paper Summarizer",
        "reddit_explorer": "Reddit Explorer",
        "tech_feed": "Tech Feed",
    }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_names": app_names,
            "app_title": app_title,
            "nook_type": nook_type_enum.value,
            "weather_data": weather_data,
            "contents": contents,
            "tab_names": tab_names,
            "date": date_str,  # テンプレートに日付を渡す
        },
    )


@app.get("/api/weather", response_class=JSONResponse)
async def get_weather():
    return get_weather_data()


_MESSAGE = """
以下の記事に関連して、検索エンジンをを用いて事実を確認しながら、ユーザーからの質問に対してできるだけ詳細に答えてください。
なお、回答はMarkdown形式で記述してください。

[記事]

{markdown}

{additional_context}

[チャット履歴]

'''
{chat_history}
'''

[ユーザーからの新しい質問]

'''
{message}
'''

それでは、回答をお願いします。
"""


@app.post("/chat/{topic_id}")
async def chat(topic_id: str, request: Request):
    """
    チャットエンドポイント。

    Parameters
    ----------
    topic_id : str
        トピックID
    request : Request
        リクエストオブジェクト

    Returns
    -------
    dict
        レスポンス
    """
    data = await request.json()
    message = data.get("message")
    markdown = data.get("markdown")
    chat_history = data.get("chat_history", "なし")
    links = extract_links(markdown) + extract_links(message)
    additional_context_list = []
    for url in links:
        if content := fetch_url_content(url):
            additional_context_list.append(
                f"- Content from {url}:\n\n'''{content}'''\n\n"
            )
    additional_context = (
        (
            "\n\n[記事またはユーザーからの質問に含まれるリンクの内容](うまく取得できていない可能性があります)\n\n"
            + "\n\n".join(additional_context_list)
        )
        if additional_context_list
        else ""
    )
    formatted_message = _MESSAGE.format(
        markdown=markdown,
        additional_context=additional_context,
        chat_history=chat_history,
        message=message,
    )
    gemini_client = create_client(use_search=True)
    response_text = gemini_client.chat_with_search(formatted_message)
    return {"response": response_text}


if __name__ == "__main__":
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
