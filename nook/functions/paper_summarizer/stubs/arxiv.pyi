from datetime import datetime

class Result:
    entry_id: str
    updated: datetime
    published: datetime
    title: str
    authors: list[str]
    summary: str
    comment: str | None
    journal_ref: str | None
    doi: str | None
    primary_category: str
    categories: list[str]
    links: list[dict[str, str]]
    pdf_url: str

def Search(
    query: str | None = None,
    id_list: list[str] | None = None,
    max_results: int | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> SearchResult: ...

class SearchResult:
    def __init__(
        self,
        query: str | None = None,
        id_list: list[str] | None = None,
        max_results: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> None: ...
    def results(self) -> list[Result]: ...
