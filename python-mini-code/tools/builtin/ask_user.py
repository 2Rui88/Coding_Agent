"""ask_user — 向用户发起澄清提问，中断 Agent 回合等待回复。"""

from pydantic import BaseModel

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition


class AskUserInput(BaseModel):
    question: str


async def _run(input: AskUserInput, _context: ToolContext) -> ToolResult:
    return ToolResult(
        ok=True,
        output=input.question.strip(),
        await_user=True,
    )


ask_user_tool = ToolDefinition(
    name="ask_user",
    description="Ask the user a clarifying question. This ends the turn and waits for the user reply.",
    input_schema=AskUserInput.model_json_schema(),
    input_model=AskUserInput,
    run=_run,
)
