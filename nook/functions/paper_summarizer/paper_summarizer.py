import concurrent.futures
import inspect
import os
import pprint
import re
import traceback
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import arxiv
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from ..common.python.gemini_client import create_client


class Config:
    hugging_face_api_url_format = "https://huggingface.co/papers?date={date}"
    arxiv_id_regex = r"\d{4}\.\d{5}"
    arxiv_ids_s3_key_format = "paper_summarizer/arxiv_ids-{date}.txt"
    summary_index_s3_key_format = "paper_summarizer/{date}.md"


def remove_tex_backticks(text: str) -> str:
    r"""
    文字列が TeX 形式、つまり
      `$\ldots$`
    の場合、外側のバッククォート (`) だけを削除して
      $\ldots$
    に変換します。
    それ以外の場合は、文字列を変更しません。
    """
    # 正規表現パターン:
    # ^`       : 文字列の先頭にバッククォート
    # (\$.*?\$): 内部は $ で始まり $ で終わる部分をキャプチャ（非貪欲）
    # `$       : 文字列の末尾にバッククォート
    pattern = r"^`(\$.*?\$)`$"
    return re.sub(pattern, r"\1", text)


def remove_outer_markdown_markers(text: str) -> str:
    """
    文章中の "```markdown" で始まるブロックについて、
    最も遠くにある "```" を閉じマーカーとして認識し、
    開始の "```markdown" とその閉じマーカー "```" のみを削除します。
    ブロック内に存在する他の "```" はそのまま残ります。

    例:
        入力:
            "通常のテキスト\n```markdown\n内部の```は残す\nその他のテキスト\n```\n続きのテキスト"
        出力:
            "通常のテキスト\n\n内部の```は残す\nその他のテキスト\n続きのテキスト"
    """
    pattern = r"```markdown(.*)```"
    return re.sub(pattern, lambda m: m.group(1), text, flags=re.DOTALL)


def remove_outer_singlequotes(text: str) -> str:
    """
    文章中の "'''" で始まるブロックについて、
    最も遠くにある "'''" を閉じマーカーとして認識し、
    開始の "'''" とその閉じマーカー "'''" のみを削除します。
    ブロック内に存在する他の "'''" はそのまま残ります。

    例:
        入力:
            "通常のテキスト\n'''\n内部の'''は残す\nその他のテキスト\n'''\n続きのテキスト"
        出力:
            "通常のテキスト\n\n内部の'''は残す\nその他のテキスト\n続きのテキスト"
    """
    pattern = r"'''(.*)'''"
    return re.sub(pattern, lambda m: m.group(1), text, flags=re.DOTALL)


@dataclass
class PaperInfo:
    title: str
    abstract: str
    url: str
    contents: str
    summary: str = field(init=False)


class PaperIdRetriever:
    def retrieve_from_hugging_face(self) -> list[str]:
        arxiv_ids = []
        try:
            response = requests.get(
                url=Config.hugging_face_api_url_format.format(
                    date=(date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
                )
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            for article in soup.find_all("article"):
                for a in article.find_all("a"):
                    href = a.get("href")
                    if re.match(rf"^/papers/{Config.arxiv_id_regex}$", href):
                        arxiv_ids.append(href.split("/")[-1])
        except requests.exceptions.RequestException as e:
            print(f"Error when retrieving papers from Hugging Face: {e}")
        return list(set(arxiv_ids))


class PaperSummarizer:
    def __init__(self):
        self._client = create_client()
        self._arxiv = arxiv.Client()
        self._paper_id_retriever = PaperIdRetriever()
        self._old_arxiv_ids = self._load_old_arxiv_ids()

    def __call__(self) -> None:
        new_arxiv_ids = self._paper_id_retriever.retrieve_from_hugging_face()
        new_arxiv_ids = self._remove_duplicates(new_arxiv_ids)
        print(f"The number of new arXiv IDs: {len(new_arxiv_ids)}")
        markdowns = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            markdowns = list(
                tqdm(
                    executor.map(self._process_paper, new_arxiv_ids),
                    total=len(new_arxiv_ids),
                    desc="Summarizing papers",
                )
            )
        self._save_arxiv_ids(new_arxiv_ids)
        self._store_summaries(markdowns)

    def _process_paper(self, arxiv_id: str) -> str:
        paper_info = self._retrieve_paper_info(arxiv_id)
        paper_info.summary = self._summarize_paper_info(paper_info)
        return self._stylize_paper_info(paper_info)

    def _retrieve_paper_info(self, id_or_url: str) -> PaperInfo:
        if id_or_url.startswith("https://arxiv.org/"):
            arxiv_id = id_or_url.split("/")[-1]
        else:
            arxiv_id = id_or_url
        search = arxiv.Search(id_list=[arxiv_id])
        info = next(self._arxiv.results(search))
        contents = self._extract_body_text(arxiv_id)
        return PaperInfo(
            title=info.title,
            abstract=info.summary,
            url=info.entry_id,
            contents=contents,
        )

    def _summarize_paper_info(self, paper_info: PaperInfo) -> str:
        system_instruction = self._system_instruction_format.format(
            title=paper_info.title,
            url=paper_info.url,
            abstract=paper_info.abstract,
            contents=paper_info.contents,
        )
        return self._client.generate_content(
            contents=self._contents,
            system_instruction=system_instruction,
        )

    def _stylize_paper_info(self, paper_info: PaperInfo) -> str:
        summary = paper_info.summary
        summary = remove_tex_backticks(summary)
        summary = remove_outer_markdown_markers(summary)
        summary = remove_outer_singlequotes(summary)
        return summary

    def _remove_duplicates(self, new_arxiv_ids: list[str]) -> list[str]:
        return list(set(new_arxiv_ids) - set(self._old_arxiv_ids))

    def _store_summaries(self, summaries: list[str]) -> None:
        date_str = date.today().strftime("%Y-%m-%d")
        key = Config.summary_index_s3_key_format.format(date=date_str)
        content = "\n\n---\n\n".join(summaries)
        output_dir = os.environ.get("OUTPUT_DIR", "./output")
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, key)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Saved summaries to {file_path}")

    def _load_old_arxiv_ids(self) -> list[str]:
        arxiv_ids = []
        output_dir = os.environ.get("OUTPUT_DIR", "./output")
        for i in range(1, 8):
            last_n_arxiv_ids_path = os.path.join(
                output_dir,
                Config.arxiv_ids_s3_key_format.format(
                    date=(date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
                ),
            )
            try:
                with open(last_n_arxiv_ids_path, encoding="utf-8") as f:
                    arxiv_ids.extend(f.read().splitlines())
            except FileNotFoundError:
                print(f"No previous IDs found at {last_n_arxiv_ids_path}")
                continue
        return arxiv_ids

    def _save_arxiv_ids(self, new_arxiv_ids: list[str]) -> None:
        date_str = date.today().strftime("%Y-%m-%d")
        key = Config.arxiv_ids_s3_key_format.format(date=date_str)
        output_dir = os.environ.get("OUTPUT_DIR", "./output")
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, key)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_arxiv_ids))
        print(f"Saved arXiv IDs to {file_path}")

    def _is_valid_body_line(self, line: str, min_length: int = 80):
        """本文として妥当な行かを判断するための簡易ヒューリスティック。
        ・行の長さが十分（例: 80文字以上）
        ・メールアドレス（@）が含まれない
        ・「Corresponding Author」や「University」「Lab」などのキーワードを含まない
        ・かつ、文として終わる（ピリオドが含まれている）場合を優先
        """
        if "@" in line:
            return False
        for kw in [
            "university",
            "lab",
            "department",
            "institute",
            "corresponding author",
        ]:
            if kw in line.lower():
                return False
        if len(line) < min_length:
            return False
        return False if "." not in line else True

    def _extract_body_text(self, arxiv_id: str, min_line_length: int = 40):
        response = requests.get(f"https://arxiv.org/html/{arxiv_id}")
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")

        body = soup.body
        if body:
            for tag in body.find_all(["header", "nav", "footer", "script", "style"]):
                tag.decompose()
            full_text = body.get_text(separator="\n", strip=True)
        else:
            full_text = ""

        lines = full_text.splitlines()

        # ヒューリスティックにより、実際の論文本文の開始行を探す
        start_index = 0
        for i, line in enumerate(lines):
            clean_line = line.strip()
            # 先頭部分の空行や短すぎる行はスキップ
            if len(clean_line) < min_line_length:
                continue
            if self._is_valid_body_line(clean_line, min_length=100):
                start_index = i
                break

        # 開始行以降を本文として抽出
        body_lines = lines[start_index:]
        # ノイズ除去: 短すぎる行は除外
        filtered_lines = []
        for line in body_lines:
            if len(line.strip()) >= min_line_length:
                line = line.strip()
                line = line.replace("Â", " ")
                filtered_lines.append(line.strip())
        return "\n".join(filtered_lines)

    @property
    def _system_instruction_format(self) -> str:
        return inspect.cleandoc(
            """
            以下のテキストは、ある論文のタイトルとURL、abstract、および本文のコンテンツです。
            本文はhtmlから抽出されたもので、ノイズや不要な部分が含まれている可能性があります。
            よく読んで、ユーザーの質問に答えてください。

            title
            '''
            {title}
            '''

            url
            '''
            {url}
            '''

            abstract
            '''
            {abstract}
            '''

            contents
            '''
            {contents}
            '''
            """
        )

    @property
    def _contents(self) -> str:
        return inspect.cleandoc(
            """
            以下の8つの質問について、順を追って非常に詳細に、分かりやすく答えてください。

            1. 既存研究では何ができなかったのか
            2. どのようなアプローチでそれを解決しようとしたか
            3. 結果、何が達成できたのか
            4. Limitationや問題点は何か。本文で言及されているものの他、あなたが考えるものも含めて
            5. 技術的な詳細について。技術者が読むことを想定したトーンで
            6. コストや物理的な詳細について。例えばトレーニングに使用したGPUの数や時間、データセット、モデルのサイズなど
            7. 参考文献のうち、特に参照すべきもの
            8. この論文を140字以内のツイートで要約すると？

            フォーマットは以下の通りで、markdown形式で回答してください。このフォーマットに沿った文言以外の出力は不要です。
            なお、数式は表示が崩れがちで面倒なので、説明に数式を使うときは、代わりにPython風の疑似コードを書いてください。

            '''
            # タイトル

            [View Paper](url)

            ## 1. 既存研究では何ができなかったのか

            ...

            ## 2. どのようなアプローチでそれを解決しようとしたか

            ...
            '''

            それでは、よろしくお願いします。
            """
        )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    pprint(event)

    try:
        if event.get("source") == "aws.events":
            paper_summarizer_ = PaperSummarizer()
            paper_summarizer_()
        return {"statusCode": 200}
    except Exception as e:
        pprint(traceback.format_exc())
        pprint(e)
        return {"statusCode": 500}
