"""Phase 4 check: run each prompt through llm.py on the sample BRD and print the results.

Run: python tests/run_prompts.py [path/to/brd.pdf]   (live Gemini calls; results are cached)
"""
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

from llm import generate_json  # noqa: E402
from memory import store  # noqa: E402
from schemas import Architecture, GapList, Plan, StoryList  # noqa: E402

PROMPTS = ROOT / "prompts"


def extract_text(pdf: Path) -> str:
    """Extract PDF text without ligatures (see CLAUDE.md)."""
    flags = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES
    with pymupdf.open(pdf) as doc:
        return "\n".join(page.get_text(flags=flags) for page in doc)


def memory_context(queries: list[str]) -> str:
    """Render constraints + semantic matches as the MEMORY CONTEXT block."""
    mem = store.get_constraints()
    lines = ["MEMORY CONTEXT",
             f"APPROVED STACK: {', '.join(mem.approved_stack)}",
             f"ESTIMATION SCALE: {mem.estimation_scale}",
             "RULES:"]
    lines += [f"- [{r['key']}] ({r['type']}) {r['text']}" for r in store.search(queries)]
    return "\n".join(lines)


def main() -> None:
    """Run planner, gaps, one story batch and architect; print short summaries."""
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "checkout_brd.pdf"
    brd = extract_text(pdf)
    ctx = memory_context(["one-click checkout saved card storage", "wallet payment balance top-up",
                          "personal data customer profile", "prevent duplicate payments"])
    base = f"BRD:\n{brd}\n\n{ctx}"

    plan = generate_json((PROMPTS / "planner.md").read_text(), base, Plan)
    print("\n== PLAN ==")
    for s in plan.steps:
        print(f"{s.id}. {s.title} [{s.executor}] — {s.purpose}")

    gs_system = (PROMPTS / "gaps_stories.md").read_text()
    gaps = generate_json(gs_system, f"TASK: gaps\n\n{base}", GapList)
    print("\n== GAPS ==")
    for g in gaps.gaps:
        print(f"{g.id} [{g.severity}/{g.category}] {g.title} (§{g.source_section})")

    ids = ["US-01", "US-02", "US-03", "US-04", "US-05"]
    stories = generate_json(gs_system, f"TASK: stories\nSTORY IDS: {', '.join(ids)}\n\n{base}\n\n"
                                       f"GAPS:\n{gaps.model_dump_json()}", StoryList)
    print("\n== STORIES (batch 1) ==")
    for s in stories.stories:
        print(f"{s.id} {s.title} — {s.story_points} pts, gaps={s.linked_gaps}, tags={s.compliance_tags}")
    print("\nFirst Gherkin:\n" + stories.stories[0].gherkin)

    arch = generate_json((PROMPTS / "architect.md").read_text(),
                         f"{base}\n\nGAPS:\n{gaps.model_dump_json()}", Architecture)
    print("\n== ARCHITECTURE ==")
    for c in arch.components:
        print(f"{c.id}: {c.name} [{c.tech} / {c.tier}] {c.requirements}")
    print(f"connections: {len(arch.connections)}")

    mem = store.get_constraints()
    off_stack = [c.tech for c in arch.components if c.tier != "External" and c.tech not in mem.approved_stack]
    bad_points = [s.id for s in stories.stories if s.story_points not in mem.estimation_scale]
    print("\nQuick checks:", json.dumps({"off_stack": off_stack, "bad_points": bad_points}))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    main()
