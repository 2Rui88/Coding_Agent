"""web_fetch — 获取网页内容并转为文本。"""

import httpx
from pydantic import BaseModel

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition


class WebFetchInput(BaseModel):
    url: str


async def _run(input: WebFetchInput, _context: ToolContext) -> ToolResult:
    url = input.url.strip()
    if not url.startswith(("http://", "https://")):
        return ToolResult(ok=False, output=f"Invalid URL: {url}")

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "mini-code/0.1"},
            )
            resp.raise_for_status()
            text = resp.text[:50_000]
            return ToolResult(ok=True, output=text)
    except httpx.HTTPStatusError as e:
        return ToolResult(ok=False, output=f"HTTP {e.response.status_code}: {url}")
    except httpx.TimeoutException:
        return ToolResult(ok=False, output=f"Request timed out: {url}")
    except Exception as e:
        return ToolResult(ok=False, output=str(e))


web_fetch_tool = ToolDefinition(
    name="web_fetch",
    description="Fetch content from a URL and return as text.",
    input_schema=WebFetchInput.model_json_schema(),
    input_model=WebFetchInput,
    run=_run,
)
