"""Pydantic data contracts for ArchiSpec — single source of truth.

Keep models FLAT: Gemini structured output supports only a JSON Schema subset.
"""
from typing import Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    id: int
    title: str
    purpose: str
    executor: str = Field(description="Skill or tool name that runs this step")


class Plan(BaseModel):
    steps: list[PlanStep]


class Gap(BaseModel):
    id: str = Field(description='Format "GAP-01"')
    title: str
    category: Literal["NFR", "Security", "EdgeCase", "Compliance"]
    severity: Literal["High", "Medium", "Low"]
    reason: str
    suggested_requirement: str
    source_section: str = Field(description='BRD section number, or "not stated" if absent')


class GapList(BaseModel):
    gaps: list[Gap]


class UserStory(BaseModel):
    id: str = Field(description='Format "US-01"')
    title: str
    as_a: str
    i_want: str
    so_that: str
    gherkin: str = Field(description="Full Gherkin text: Feature + Scenario(s)")
    story_points: int
    linked_gaps: list[str]
    compliance_tags: list[str]


class StoryList(BaseModel):
    stories: list[UserStory]


class Component(BaseModel):
    id: str
    name: str
    tech: str
    tier: Literal["Client", "Edge", "Service", "Data", "Messaging", "External"]
    requirements: list[str]


class Connection(BaseModel):
    source: str
    target: str
    label: str


class Architecture(BaseModel):
    components: list[Component]
    connections: list[Connection]


class Memory(BaseModel):
    """Hard constraints + guidance assembled from Chroma by memory/store.py."""

    approved_stack: list[str] = []
    compliance_rules: list[str] = []
    estimation_scale: list[int] = []
    feedback: list[str] = []
