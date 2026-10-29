"""Stdio round-trip test for mcp_server/server.py (no LLM calls; needs seeded memory).

Run: python tests/test_mcp_server.py
Only read-only and file-writing tools are called, so memory is not modified.
"""
import asyncio
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from mcp_server.drawio import SAMPLE  # noqa: E402

STORY = {
    "id": "US-01", "title": "Pay with wallet", "as_a": "signed-in customer",
    "i_want": "to pay from my wallet balance", "so_that": "checkout is fast",
    "gherkin": "Feature: Wallet payment\n  Scenario: Enough balance\n    Given a wallet balance of 50\n"
               "    When I buy an item costing 20\n    Then my balance is 30",
    "story_points": 3, "linked_gaps": ["GAP-01"], "compliance_tags": ["PCI DSS"],
}


async def run() -> None:
    """Start the server over stdio, list tools and call the non-mutating ones."""
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server" / "server.py")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(t.name for t in (await session.list_tools()).tools)
            print("tools:", tools)
            assert {"query_enterprise_memory", "generate_drawio_diagram", "export_sprint_backlog",
                    "save_feedback", "save_run"} <= set(tools)

            mem = (await session.call_tool("query_enterprise_memory",
                                           {"queries": ["prevent duplicate wallet payments"]})).structuredContent
            print("approved_stack:", mem["constraints"]["approved_stack"])
            print("relevant keys:", [r["key"] for r in mem["relevant"]][:3])
            assert mem["constraints"]["estimation_scale"] == [1, 2, 3, 5, 8, 13]

            diagram = (await session.call_tool("generate_drawio_diagram", {
                "architecture_json": SAMPLE.model_dump_json(), "filename": "mcp_test"})).structuredContent
            print("drawio:", diagram)

            backlog = (await session.call_tool("export_sprint_backlog", {
                "stories_json": json.dumps([STORY]), "filename": "../escape_attempt"})).structuredContent
            print("backlog:", backlog)
            path = Path(backlog["path"])
            assert path.parent == ROOT / "outputs", "filename must stay inside outputs/"
            rows = list(csv.DictReader(path.open(encoding="utf-8")))
            assert rows[0]["Story Points"] == "3" and "Given" in rows[0]["Description"]
            print("labels:", rows[0]["Labels"])
    print("OK")


if __name__ == "__main__":
    asyncio.run(run())
