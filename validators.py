"""Deterministic checks on LLM outputs. Every function returns a list of human-readable errors."""
from gherkin.errors import CompositeParserException
from gherkin.parser import Parser

from schemas import Architecture, GapList, Memory, StoryList

REQUIRED_STEP_TYPES = {"Context": "Given", "Action": "When", "Outcome": "Then"}


def check_story_points(stories: StoryList, memory: Memory) -> list[str]:
    """Every story_points value must be on the estimation scale."""
    return [f"{s.id}: story_points {s.story_points} is not in the estimation scale {memory.estimation_scale}"
            for s in stories.stories if s.story_points not in memory.estimation_scale]


def _scenarios(feature: dict) -> list[dict]:
    """Scenarios of a parsed feature, including those nested in Rule blocks."""
    found = []
    for child in feature.get("children", []):
        if "scenario" in child:
            found.append(child["scenario"])
        elif "rule" in child:
            found += [c["scenario"] for c in child["rule"].get("children", []) if "scenario" in c]
    return found


def check_gherkin(stories: StoryList) -> list[str]:
    """Gherkin must parse and every scenario must contain Given, When and Then steps."""
    errors = []
    for s in stories.stories:
        try:
            doc = Parser().parse(s.gherkin)
        except CompositeParserException as exc:
            detail = " ".join(str(exc).split("\n")[1:]).strip() or str(exc)
            errors.append(f"{s.id}: Gherkin does not parse — {detail}")
            continue
        feature = doc.get("feature")
        scenarios = _scenarios(feature) if feature else []
        if not scenarios:
            errors.append(f"{s.id}: Gherkin has no Feature with Scenario blocks")
            continue
        for sc in scenarios:
            types = {step.get("keywordType") for step in sc.get("steps", [])}
            missing = [kw for t, kw in REQUIRED_STEP_TYPES.items() if t not in types]
            if missing:
                errors.append(f"{s.id}: scenario '{sc['name']}' is missing {'/'.join(missing)} step(s)")
    return errors


def check_architecture_stack(arch: Architecture, memory: Memory) -> list[str]:
    """Every non-External component must use a tech from the approved stack."""
    return [f"{c.id}: tech '{c.tech}' is not in the approved stack {memory.approved_stack} "
            f"(only tier 'External' may use other systems)"
            for c in arch.components if c.tier != "External" and c.tech not in memory.approved_stack]


def check_gap_coverage(gaps: GapList, stories: StoryList) -> list[str]:
    """Every High-severity gap must be linked by at least one story."""
    linked = {gap_id for s in stories.stories for gap_id in s.linked_gaps}
    return [f"{g.id}: High-severity gap '{g.title}' is not linked to any story"
            for g in gaps.gaps if g.severity == "High" and g.id not in linked]


def validate_stories(stories: StoryList, gaps: GapList, memory: Memory) -> list[str]:
    """All story-related checks (points, Gherkin, High-gap coverage)."""
    return check_story_points(stories, memory) + check_gherkin(stories) + check_gap_coverage(gaps, stories)


def validate(gaps: GapList, stories: StoryList, arch: Architecture, memory: Memory) -> list[str]:
    """Run every check and return all errors (empty list = valid)."""
    return validate_stories(stories, gaps, memory) + check_architecture_stack(arch, memory)
