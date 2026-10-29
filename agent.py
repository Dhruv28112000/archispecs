"""ArchiSpec orchestrator: ingest → plan → memory → skills → validate → tools → bundle.

Tool calls are driven by code (MCP stdio client), not chosen by the LLM.
CLI: python agent.py samples/checkout_brd.pdf   (auto-approves the plan)
"""
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pymupdf
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import validators
from llm import generate_json
from memory import store
from mcp_server.drawio import DRAFT_LABEL
from schemas import Architecture, GapList, Memory, Plan, StoryList, UserStory

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "prompts"
SERVER = ROOT / "mcp_server" / "server.py"

STORY_BATCHES = 3
BATCH_SIZE = 4
MAX_MEMORY_QUERIES = 8
GENERIC_HEADINGS = {"purpose", "background", "scope", "stakeholders", "introduction", "assumptions",
                    "constraints", "assumptions and constraints", "success metrics", "glossary"}

OnEvent = Callable[[str, str, str], None]
log = logging.getLogger("archispecs.agent")


def _noop(step: str, status: str, detail: str) -> None:
    pass


class _LLMEventHandler(logging.Handler):
    """Forward llm.py log lines (provider, retries, fallback) to the step log."""

    def __init__(self, on_event: OnEvent):
        super().__init__(level=logging.INFO)
        self.on_event = on_event

    def emit(self, record: logging.LogRecord) -> None:
        status = "warning" if record.levelno >= logging.WARNING else "info"
        self.on_event("llm", status, record.getMessage())


# ---------- ingest & memory context ----------

def ingest(pdf_path: str | Path) -> str:
    """Extract text from the BRD PDF (ligatures expanded)."""
    flags = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES
    with pymupdf.open(pdf_path) as doc:
        return "\n".join(page.get_text(flags=flags) for page in doc)


def memory_queries(brd_text: str) -> list[str]:
    """Build semantic-search queries from the BRD's numbered sub-section headings (goals, features)."""
    queries = []
    for match in re.finditer(r"^\s*\d+\.\d+\s+(.+?)\s*$", brd_text, re.M):
        heading = match.group(1)
        if heading.lower() not in GENERIC_HEADINGS and heading not in queries:
            queries.append(heading)
    return queries[:MAX_MEMORY_QUERIES] or [brd_text[:500]]


def memory_context(memory: dict[str, Any]) -> str:
    """Render the query_enterprise_memory result as the MEMORY CONTEXT block for prompts."""
    c = memory["constraints"]
    lines = ["MEMORY CONTEXT",
             f"APPROVED STACK: {', '.join(c['approved_stack'])}",
             f"ESTIMATION SCALE: {c['estimation_scale']}",
             "RULES:"]
    lines += [f"- [{r['key']}] ({r['type']}) {r['text']}" for r in memory["relevant"] if r["type"] != "feedback"]
    if c["feedback"]:
        lines += ["FEEDBACK (follow these):"] + [f"- {f}" for f in c["feedback"]]
    if memory.get("similar_past"):
        lines += ["SIMILAR PAST ITEMS (reuse wording where it fits):"]
        lines += [f"- ({r['kind']}) {r['text']}" for r in memory["similar_past"]]
    return "\n".join(lines)


def _local_memory(brd_text: str) -> dict[str, Any]:
    """Same shape as the MCP tool result, read directly (used only to brief the planner)."""
    queries = memory_queries(brd_text)
    return {"constraints": store.get_constraints().model_dump(), "relevant": store.search(queries, n=3),
            "similar_past": []}


# ---------- skills ----------

def make_plan(brd_text: str, memory: dict[str, Any]) -> Plan:
    """Planner skill: 4-stage plan adapted to the BRD."""
    user = f"BRD:\n{brd_text}\n\n{memory_context(memory)}"
    return generate_json((PROMPTS / "planner.md").read_text(encoding="utf-8"), user, Plan)


def _with_errors(user: str, previous: str, errors: list[str]) -> str:
    return (f"{user}\n\nYOUR PREVIOUS ANSWER:\n{previous}\n\n"
            "VALIDATION ERRORS in your previous answer — return a corrected answer that fixes them:\n"
            + "\n".join(f"- {e}" for e in errors))


def _story_batch(base: str, gaps: GapList, ids: list[str], written: list[UserStory],
                 memory: Memory, on_event: OnEvent, focus_gaps: list[str] | None = None) -> list[UserStory]:
    """Generate one batch of stories; validate points + Gherkin; one repair call on errors."""
    system = (PROMPTS / "gaps_stories.md").read_text(encoding="utf-8")
    covered = {g for s in written for g in s.linked_gaps}
    uncovered = focus_gaps or [g.id for g in gaps.gaps if g.severity == "High" and g.id not in covered]
    parts = [f"TASK: stories\nSTORY IDS: {', '.join(ids)}"]
    if written:
        parts.append("ALREADY WRITTEN (do not duplicate):\n" + "\n".join(f"- {s.id} {s.title}" for s in written))
    if uncovered:
        parts.append(f"PRIORITY GAPS (High gaps not yet linked to a story): {', '.join(uncovered)}")
    if focus_gaps:
        parts.append("Write exactly one story per PRIORITY GAP and link it.")
    user = "\n".join(parts) + f"\n\n{base}\n\nGAPS:\n{gaps.model_dump_json()}"

    batch = generate_json(system, user, StoryList)
    errors = validators.check_story_points(batch, memory) + validators.check_gherkin(batch)
    if errors:
        on_event("validate", "warning", f"{len(errors)} issue(s) in {ids[0]}–{ids[-1]}, sending one repair: "
                 + "; ".join(errors))
        batch = generate_json(system, _with_errors(user, batch.model_dump_json(), errors), StoryList)
    return batch.stories


def gaps_and_stories(brd_text: str, memory: dict[str, Any], on_event: OnEvent = _noop) -> tuple[GapList, StoryList]:
    """Gap detection, then stories in batches of BATCH_SIZE, then one coverage batch for unlinked High gaps."""
    base = f"BRD:\n{brd_text}\n\n{memory_context(memory)}"
    mem = Memory(**memory["constraints"])
    system = (PROMPTS / "gaps_stories.md").read_text(encoding="utf-8")

    gaps = generate_json(system, f"TASK: gaps\n\n{base}", GapList)
    high = sum(g.severity == "High" for g in gaps.gaps)
    on_event("gaps", "done", f"{len(gaps.gaps)} gaps ({high} High): " + ", ".join(g.id for g in gaps.gaps))

    stories: list[UserStory] = []
    for b in range(STORY_BATCHES):
        ids = [f"US-{n:02d}" for n in range(len(stories) + 1, len(stories) + BATCH_SIZE + 1)]
        on_event("stories", "start", f"batch {b + 1}/{STORY_BATCHES}: {ids[0]}–{ids[-1]}")
        stories += _story_batch(base, gaps, ids, stories, mem, on_event)

    missing = [e.split(":")[0] for e in validators.check_gap_coverage(gaps, StoryList(stories=stories))]
    if missing:
        ids = [f"US-{n:02d}" for n in range(len(stories) + 1, len(stories) + len(missing[:5]) + 1)]
        on_event("stories", "start", f"coverage batch for unlinked High gaps {missing[:5]}")
        stories += _story_batch(base, gaps, ids, stories, mem, on_event, focus_gaps=missing[:5])

    on_event("stories", "done", f"{len(stories)} stories, {sum(s.story_points for s in stories)} points")
    return gaps, StoryList(stories=stories)


def architect(brd_text: str, memory: dict[str, Any], gaps: GapList, on_event: OnEvent = _noop) -> Architecture:
    """Architect skill (approved stack only); one repair call if the stack check fails."""
    system = (PROMPTS / "architect.md").read_text(encoding="utf-8")
    user = f"BRD:\n{brd_text}\n\n{memory_context(memory)}\n\nGAPS:\n{gaps.model_dump_json()}"
    arch = generate_json(system, user, Architecture)
    errors = validators.check_architecture_stack(arch, Memory(**memory["constraints"]))
    if errors:
        on_event("validate", "warning", "architecture repair: " + "; ".join(errors))
        arch = generate_json(system, _with_errors(user, arch.model_dump_json(), errors), Architecture)
    return arch


# ---------- MCP ----------

def _server_params() -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], cwd=str(ROOT))


async def _call_tool(session: ClientSession, name: str, args: dict[str, Any], on_event: OnEvent,
                     summary: str) -> dict[str, Any]:
    """Call an MCP tool, emitting start/done events; raise on tool errors."""
    on_event(f"mcp:{name}", "start", summary)
    result = await session.call_tool(name, args)
    if result.isError or result.structuredContent is None:
        text = " ".join(getattr(c, "text", "") for c in result.content)
        on_event(f"mcp:{name}", "error", text)
        raise RuntimeError(f"MCP tool {name} failed: {text}")
    return result.structuredContent


async def _save_feedback(text: str) -> dict[str, Any]:
    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await _call_tool(session, "save_feedback", {"text": text}, _noop, "")


def save_feedback(text: str) -> dict[str, Any]:
    """Store user feedback in memory via the MCP save_feedback tool. Returns {key}."""
    return asyncio.run(_save_feedback(text))


# ---------- summary ----------

def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def applied_keys(gaps: GapList, stories: StoryList, arch: Architecture) -> list[str]:
    """Memory keys cited by gaps, stories and components."""
    keys = set(re.findall(r"applied:\s*([\w-]+)", " ".join(g.suggested_requirement for g in gaps.gaps)))
    keys |= {t for s in stories.stories for t in s.compliance_tags}
    keys |= {m for c in arch.components for r in c.requirements for m in re.findall(r"applied:\s*([\w-]+)", r)}
    return sorted(keys)


def write_summary(path: Path, title: str, source: str, run_id: str, plan: Plan, gaps: GapList,
                  stories: StoryList, arch: Architecture, flags: list[str], files: dict[str, str]) -> None:
    """Write the executive summary, critical gaps table and links (deterministic, no LLM)."""
    sev = {s: [g for g in gaps.gaps if g.severity == s] for s in ("High", "Medium", "Low")}
    lines = [
        f"# ArchiSpec summary — {title}", "", f"> **{DRAFT_LABEL}**", "",
        f"Source: `{source}` · Run: `{run_id}`", "",
        "## Executive summary",
        f"- **{len(gaps.gaps)} gaps** found: {len(sev['High'])} High, {len(sev['Medium'])} Medium, {len(sev['Low'])} Low",
        f"- **{len(stories.stories)} user stories**, {sum(s.story_points for s in stories.stories)} story points in total",
        f"- **Architecture:** {len(arch.components)} components, {len(arch.connections)} connections",
        f"- **Memory applied:** {', '.join(applied_keys(gaps, stories, arch)) or 'none'}",
        f"- **Validation:** {'all checks passed' if not flags else f'{len(flags)} open issue(s) — see below'}",
        "", "## ⚠ Critical gaps (High)",
        "| ID | Gap | Category | BRD section | Suggested requirement |", "|---|---|---|---|---|",
    ]
    lines += [f"| {g.id} | {_cell(g.title)} | {g.category} | {g.source_section} | {_cell(g.suggested_requirement)} |"
              for g in sev["High"]] or ["| – | No High-severity gaps | | | |"]
    lines += ["", "## Other gaps", "| ID | Severity | Gap | BRD section |", "|---|---|---|---|"]
    lines += [f"| {g.id} | {g.severity} | {_cell(g.title)} | {g.source_section} |" for g in sev["Medium"] + sev["Low"]]
    lines += ["", "## Validation flags"] + ([f"- {f}" for f in flags] or ["- none"])
    lines += ["", "## Plan"] + [f"{s.id}. **{s.title}** (`{s.executor}`) — {s.purpose}" for s in plan.steps]
    lines += ["", "## Files"] + [f"- [{label}]({Path(p).name})" for label, p in files.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- public API ----------

def plan_run(pdf_path: str | Path, on_event: OnEvent = _noop) -> Plan:
    """Ingest the BRD and return the plan for human approval."""
    handler = _LLMEventHandler(on_event)
    logging.getLogger("archispecs.llm").addHandler(handler)
    try:
        on_event("ingest", "start", str(pdf_path))
        brd = ingest(pdf_path)
        on_event("ingest", "done", f"{len(brd)} characters extracted")
        on_event("plan", "start", "planner skill")
        plan = make_plan(brd, _local_memory(brd))
        on_event("plan", "done", f"{len(plan.steps)} steps")
        return plan
    finally:
        logging.getLogger("archispecs.llm").removeHandler(handler)


async def _execute(pdf_path: Path, plan: Plan, on_event: OnEvent) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")
    brd = ingest(pdf_path)
    title_match = re.search(r"Project:\s*(.+)", brd)
    title = title_match.group(1).strip() if title_match else pdf_path.stem
    out_dir = ROOT / os.getenv("OUTPUT_DIR", "outputs")

    on_event("mcp", "start", "starting MCP server (stdio)")
    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = [t.name for t in (await session.list_tools()).tools]
        on_event("mcp", "done", f"connected — tools: {', '.join(tools)}")

        queries = memory_queries(brd)
        memory = await _call_tool(session, "query_enterprise_memory", {"queries": queries}, on_event,
                                  f"queries: {queries}")
        on_event("mcp:query_enterprise_memory", "done",
                 f"stack={memory['constraints']['approved_stack']}; retrieved: "
                 + ", ".join(f"{r['key']} ({1 - r['distance']:.2f})" for r in memory["relevant"])
                 + f"; similar past: {len(memory['similar_past'])}")

        on_event("gaps", "start", "gaps_and_stories skill")
        gaps, stories = gaps_and_stories(brd, memory, on_event)

        on_event("architect", "start", "architect skill")
        arch = architect(brd, memory, gaps, on_event)
        on_event("architect", "done", f"{len(arch.components)} components, {len(arch.connections)} connections")

        on_event("validate", "start", "final validation")
        flags = validators.validate(gaps, stories, arch, Memory(**memory["constraints"]))
        on_event("validate", "warning" if flags else "done",
                 f"{len(flags)} flag(s): " + "; ".join(flags) if flags else "all checks passed")

        diagram = await _call_tool(session, "generate_drawio_diagram",
                                   {"architecture_json": arch.model_dump_json(), "filename": "architecture"},
                                   on_event, f"{len(arch.components)} components")
        flags += diagram["warnings"]
        on_event("mcp:generate_drawio_diagram", "done", diagram["path"])

        backlog = await _call_tool(session, "export_sprint_backlog",
                                   {"stories_json": stories.model_dump_json(), "filename": "backlog"},
                                   on_event, f"{len(stories.stories)} stories")
        on_event("mcp:export_sprint_backlog", "done", f"{backlog['rows']} rows → {backlog['path']}")

        summary_path = out_dir / "summary.md"
        files = {"Architecture diagram (.drawio)": diagram["path"], "Jira backlog (.csv)": backlog["path"]}
        write_summary(summary_path, title, pdf_path.name, run_id, plan, gaps, stories, arch, flags, files)
        on_event("summary", "done", str(summary_path))

        saved = await _call_tool(session, "save_run", {"run_id": run_id, "gaps_json": gaps.model_dump_json(),
                                                       "stories_json": stories.model_dump_json()},
                                 on_event, run_id)
        on_event("mcp:save_run", "done", f"{saved['stored']} items stored for reuse in future runs")

    return {"run_id": run_id, "title": title, "plan": plan, "memory": memory, "gaps": gaps,
            "stories": stories, "architecture": arch, "flags": flags,
            "paths": {"summary": str(summary_path), "drawio": diagram["path"], "backlog": backlog["path"]}}


def _root_cause(exc: BaseException) -> BaseException:
    """Unwrap single-exception groups raised by anyio task groups (MCP client)."""
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


def execute_run(pdf_path: str | Path, plan: Plan, on_event: OnEvent = _noop) -> dict[str, Any]:
    """Run the approved plan end to end. Returns results and output paths."""
    handler = _LLMEventHandler(on_event)
    logging.getLogger("archispecs.llm").addHandler(handler)
    try:
        return asyncio.run(_execute(Path(pdf_path), plan, on_event))
    except Exception as exc:
        cause = _root_cause(exc)
        on_event("run", "error", f"{type(cause).__name__}: {cause}")
        raise cause from None
    finally:
        logging.getLogger("archispecs.llm").removeHandler(handler)


def _print_event(step: str, status: str, detail: str) -> None:
    print(f"[{status.upper():7}] {step:32} {detail}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python agent.py path/to/brd.pdf")
    logging.getLogger("archispecs.llm").setLevel(logging.INFO)
    pdf = Path(sys.argv[1])
    approved_plan = plan_run(pdf, _print_event)
    for s in approved_plan.steps:
        print(f"  PLAN {s.id}. {s.title} [{s.executor}] — {s.purpose}")
    print("  (CLI auto-approves the plan)")
    result = execute_run(pdf, approved_plan, _print_event)
    print(json.dumps(result["paths"], indent=2))
