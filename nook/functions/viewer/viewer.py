# nook/functions/viewer/viewer.py
import datetime
import os
import re
import sys

from dotenv import load_dotenv

# プロジェクトルートをモジュール検索パスに追加
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from nook.functions.common.python.gemini_client import create_client

app = FastAPI()
# テンプレートディレクトリを絶対パスで指定
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

# NOOK_TYPEに基づいてアプリ名とタイトルを設定
NOOK_TYPE = os.environ.get("NOOK_TYPE", "default")

if NOOK_TYPE == "camera":
    app_names = [
        "reddit_explorer",
        "tech_feed",
    ]
else:
    app_names = [
        "github_trending",
        "hacker_news",
        "paper_summarizer",
        "reddit_explorer",
        "tech_feed",
    ]

# アプリタイトルを設定
app_title = "Nook Camera" if NOOK_TYPE == "camera" else "Nook"

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


def fetch_markdown(app_name: str, date_str: str) -> str:
    output_dir = os.environ.get("OUTPUT_DIR", "./output")
    key = f"{app_name}/{date_str}.md"
    file_path = os.path.join(output_dir, key)
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
            print(f"Fetched markdown for {key}:")
            print(content[:500])
            return content
    except Exception as e:
        return f"Error fetching {key}: {e}"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, date: str | None = None):
    if date is None:
        date = datetime.date.today().strftime("%Y-%m-%d")
    contents = {name: fetch_markdown(name, date) for name in app_names}
    weather_data = get_weather_data()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "contents": contents,
            "date": date,
            "app_names": app_names,
            "weather_data": weather_data,
            "app_title": app_title,
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
