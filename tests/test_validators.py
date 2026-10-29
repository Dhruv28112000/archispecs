"""Validator tests: one valid and one invalid example per rule. Run: python -m pytest -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas import Architecture, Component, Gap, GapList, Memory, StoryList, UserStory  # noqa: E402
from validators import (  # noqa: E402
    check_architecture_stack,
    check_gap_coverage,
    check_gherkin,
    check_story_points,
    validate,
)

MEMORY = Memory(approved_stack=["Next.js", "FastAPI", "PostgreSQL", "Redis", "Kafka"],
                estimation_scale=[1, 2, 3, 5, 8, 13])

GOOD_GHERKIN = """Feature: Wallet payment
  Scenario: Enough balance
    Given my wallet balance is 50
    When I pay 20 from my wallet
    Then my balance is 30
  Scenario: Not enough balance
    Given my wallet balance is 10
    And I am on the checkout page
    When I pay 20 from my wallet
    Then the payment is declined
    But my balance stays 10"""


def story(id_: str = "US-01", points: int = 3, gherkin: str = GOOD_GHERKIN,
          linked: list[str] | None = None) -> UserStory:
    return UserStory(id=id_, title="Pay with wallet", as_a="customer", i_want="to pay from my wallet",
                     so_that="checkout is fast", gherkin=gherkin, story_points=points,
                     linked_gaps=linked or [], compliance_tags=[])


def gap(id_: str = "GAP-01", severity: str = "High") -> Gap:
    return Gap(id=id_, title="Concurrent wallet debits", category="EdgeCase", severity=severity,
               reason="r", suggested_requirement="s", source_section="3.3")


def component(tech: str, tier: str = "Service") -> Component:
    return Component(id="c1", name="Svc", tech=tech, tier=tier, requirements=[])


# story_points ∈ estimation_scale
def test_story_points_valid():
    assert check_story_points(StoryList(stories=[story(points=5)]), MEMORY) == []


def test_story_points_invalid():
    errors = check_story_points(StoryList(stories=[story(points=4)]), MEMORY)
    assert len(errors) == 1 and "US-01" in errors[0] and "4" in errors[0]


# gherkin parses and has Given/When/Then
def test_gherkin_valid():
    assert check_gherkin(StoryList(stories=[story()])) == []


def test_gherkin_does_not_parse():
    errors = check_gherkin(StoryList(stories=[story(gherkin="just some text\nGiven nothing")]))
    assert len(errors) == 1 and "does not parse" in errors[0]


def test_gherkin_without_scenarios():
    errors = check_gherkin(StoryList(stories=[story(gherkin="Feature: F\n  Given x")]))
    assert errors == ["US-01: Gherkin has no Feature with Scenario blocks"]


def test_gherkin_missing_then():
    text = "Feature: F\n  Scenario: No outcome\n    Given a balance\n    When I pay"
    errors = check_gherkin(StoryList(stories=[story(gherkin=text)]))
    assert errors == ["US-01: scenario 'No outcome' is missing Then step(s)"]


# Component.tech ∈ approved_stack (External exempt)
def test_architecture_valid_including_external():
    arch = Architecture(components=[component("FastAPI"), component("PayBridge", tier="External")], connections=[])
    assert check_architecture_stack(arch, MEMORY) == []


def test_architecture_unapproved_tech():
    arch = Architecture(components=[component("MongoDB", tier="Data")], connections=[])
    errors = check_architecture_stack(arch, MEMORY)
    assert len(errors) == 1 and "MongoDB" in errors[0]


# every High gap linked by ≥1 story
def test_gap_coverage_valid():
    gaps = GapList(gaps=[gap("GAP-01"), gap("GAP-02", severity="Low")])
    assert check_gap_coverage(gaps, StoryList(stories=[story(linked=["GAP-01"])])) == []


def test_gap_coverage_missing_high_gap():
    gaps = GapList(gaps=[gap("GAP-01"), gap("GAP-02")])
    errors = check_gap_coverage(gaps, StoryList(stories=[story(linked=["GAP-01"])]))
    assert len(errors) == 1 and errors[0].startswith("GAP-02")


def test_validate_collects_all_errors():
    arch = Architecture(components=[component("MongoDB")], connections=[])
    errors = validate(GapList(gaps=[gap()]), StoryList(stories=[story(points=4)]), arch, MEMORY)
    assert len(errors) == 3
