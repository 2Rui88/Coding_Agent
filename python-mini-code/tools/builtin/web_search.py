"""web_search — 网页搜索（使用 DuckDuckGo HTML 搜索，无需 API key）。"""

import httpx
from pydantic import BaseModel

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition


class WebSearchInput(BaseModel):
    query: str


async def _run(input: WebSearchInput, _context: ToolContext) -> ToolResult:
    query = input.query.strip()
    if not query:
        return ToolResult(ok=False, output="Empty search query")

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "mini-code/0.1"},
            )
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        return ToolResult(ok=False, output=f"Search request failed: {e}")

    # 简单 HTML 提取（提取链接和摘要）
    import re
    results = []
    # 匹配 DuckDuckGo 结果片段
    blocks = re.split(r'<a rel="nofollow" class="result__a"', html)
    for block in blocks[1:6]:
        href_match = re.search(r'href="([^"]+)"', block)
        title_match = re.search(r'class="result__a"[^>]*>([^<]+)', block)
        snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)

        title = re.sub(r"<[^>]+>", "", title_match.group(1) if title_match else "no title")
        url = href_match.group(1) if href_match else ""
        snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1) if snippet_match else "")

        results.append(f"{title}\n{url}\n{snippet}")

    if not results:
        return ToolResult(ok=True, output=f"No results found for: {query}")

    return ToolResult(ok=True, output="\n\n".join(results))


web_search_tool = ToolDefinition(
    name="web_search",
    description="Search the web using DuckDuckGo and return formatted results.",
    input_schema=WebSearchInput.model_json_schema(),
    input_model=WebSearchInput,
    run=_run,
)
