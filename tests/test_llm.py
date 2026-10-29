"""Tiny live test for llm.py (calls Gemini; needs .env).

Run: python tests/test_llm.py   (or python -m pytest -q once pytest is installed)
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm import generate_json  # noqa: E402
from schemas import Plan  # noqa: E402

SYSTEM = "You are a delivery planner. Return a short plan as JSON."
USER = "Plan 3 steps to turn a requirements PDF into user stories. Executors: ingest, gaps_and_stories, validate."


def test_plan_and_cache() -> None:
    """First call returns a valid Plan; the identical second call is served from cache."""
    first = generate_json(SYSTEM, USER, Plan)
    assert first.steps, "plan has no steps"
    start = time.perf_counter()
    second = generate_json(SYSTEM, USER, Plan)
    assert second == first
    assert time.perf_counter() - start < 0.5, "second call was not served from cache"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    test_plan_and_cache()
    plan = generate_json(SYSTEM, USER, Plan)
    for step in plan.steps:
        print(f"{step.id}. {step.title} [{step.executor}]")
    print("OK")
