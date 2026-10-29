"""ArchiSpec MCP server (FastMCP, stdio).

Tools: query_enterprise_memory, generate_drawio_diagram, export_sprint_backlog,
save_feedback, save_run. Run standalone: python mcp_server/server.py
Note: stdout is the MCP channel — never print(); use logging (stderr).
"""
import csv
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from mcp_server.drawio import DRAFT_LABEL, write_drawio  # noqa: E402
from memory import store  # noqa: E402
from schemas import Architecture, GapList, StoryList, UserStory  # noqa: E402

mcp = FastMCP("archispec")

BACKLOG_COLUMNS = ["Summary", "Issue Type", "Description", "Story Points", "Labels"]


def _output_path(filename: str, suffix: str) -> Path:
    """Resolve a safe file path inside OUTPUT_DIR (basename only, forced suffix)."""
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).stem) or "output"
    out_dir = ROOT / os.getenv("OUTPUT_DIR", "outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{stem}{suffix}"


def _parse_list(raw: str, model: type[GapList] | type[StoryList], field: str):
    """Accept either {"<field>": [...]} or a bare JSON list."""
    raw = raw.strip()
    if raw.startswith("["):
        raw = f'{{"{field}": {raw}}}'
    return model.model_validate_json(raw)


def _story_description(story: UserStory) -> str:
    gaps = ", ".join(story.linked_gaps) or "none"
    return (f"{DRAFT_LABEL}\n\n"
            f"As a {story.as_a}, I want {story.i_want}, so that {story.so_that}.\n\n"
            f"Acceptance criteria:\n{story.gherkin}\n\n"
            f"Linked gaps: {gaps}")


def _labels(story: UserStory) -> str:
    # Jira labels cannot contain spaces.
    tags = ["archispec", "draft", *story.compliance_tags]
    return " ".join(re.sub(r"\s+", "-", t.strip()) for t in tags if t.strip())


@mcp.tool()
def query_enterprise_memory(queries: list[str]) -> dict[str, Any]:
    """Return hard constraints (deterministic), relevant memory records (semantic) and similar past items."""
    return {
        "constraints": store.get_constraints().model_dump(),
        "relevant": store.search(queries),
        "similar_past": store.search_past(queries),
    }


@mcp.tool()
def generate_drawio_diagram(architecture_json: str, filename: str) -> dict[str, Any]:
    """Render an Architecture JSON to an editable .drawio file in the output folder."""
    arch = Architecture.model_validate_json(architecture_json)
    return write_drawio(arch, _output_path(filename, ".drawio"))


@mcp.tool()
def export_sprint_backlog(stories_json: str, filename: str) -> dict[str, Any]:
    """Write user stories to a Jira-importable CSV. Returns {path, rows}."""
    stories = _parse_list(stories_json, StoryList, "stories").stories
    path = _output_path(filename, ".csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(BACKLOG_COLUMNS)
        for s in stories:
            writer.writerow([f"{s.id} {s.title}", "Story", _story_description(s),
                             s.story_points, _labels(s)])
    return {"path": str(path), "rows": len(stories)}


@mcp.tool()
def save_feedback(text: str) -> dict[str, Any]:
    """Store user feedback in enterprise memory so the next run can retrieve it."""
    return {"key": store.add_feedback(text)}


@mcp.tool()
def save_run(run_id: str, gaps_json: str, stories_json: str) -> dict[str, Any]:
    """Store approved gaps and stories from a run in past_runs."""
    gaps = _parse_list(gaps_json, GapList, "gaps").gaps
    stories = _parse_list(stories_json, StoryList, "stories").stories
    return {"run_id": run_id, "stored": store.add_run(run_id, gaps, stories)}


if __name__ == "__main__":
    mcp.run()  # stdio transport
