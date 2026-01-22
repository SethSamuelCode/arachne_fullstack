from datetime import datetime
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.core.config import settings

tz = ZoneInfo(settings.TZ)

class SingleTask(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    task_description: str = Field(default="", description="Description of the task and what needs to be done.", examples=["Write unit tests for the new feature", "Design the database schema for user profiles"])
    task_notes: str | None = Field(default=None, description="Additional notes or context for the task.", examples=["Remember to follow the coding standards.", "Consider scalability for future growth."])
    task_completed: bool = Field(default=False, description="Indicates whether the task has been completed.")
    task_status: Literal["pending", "in_progress", "completed"] = Field(default="pending", description="Current status of the task.", examples=["pending", "in_progress", "completed"])
    task_position: int = Field(default=0, description="Position of the task in the list.")

class Plan(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str = Field(default="", description="Name of the plan.", examples=["Project Launch Plan", "Marketing Strategy Plan"])
    plan_description: str = Field(default="", description="Detailed description of the plan and its objectives.", examples=["This plan outlines the steps to successfully launch the new product.", "This plan details the marketing strategies for the upcoming quarter."])
    steps: list[SingleTask] = Field(default=[], description="List of tasks that make up the plan.")
    plan_notes: str | None = Field(default=None, description="Additional notes or context for the plan.", examples=["Include budget considerations.", "Outline key milestones."])
    plan_completed: bool = Field(default=False, description="Indicates whether the plan has been completed.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=tz), description="Timestamp when the plan was created.")
    updated_at: datetime | None = Field(default=None, description="Timestamp when the plan was last updated.")


class SingleTaskUpdate(BaseModel):
    """Schema for partial task updates - only id is required, all other fields are optional."""

    id: str = Field(..., description="The unique identifier of the task to update.")
    task_description: str | None = Field(default=None, description="Description of the task and what needs to be done.")
    task_notes: str | None = Field(default=None, description="Additional notes or context for the task.")
    task_completed: bool | None = Field(default=None, description="Indicates whether the task has been completed.")
    task_status: Literal["pending", "in_progress", "completed"] | None = Field(default=None, description="Current status of the task.")
    task_position: int | None = Field(default=None, description="Position of the task in the list.")


class PlanUpdate(BaseModel):
    """Schema for partial plan updates - all fields are optional.

    Only fields explicitly provided will be updated. Missing fields retain their existing values.
    To update tasks, provide their IDs in the steps list - only provided task fields will be updated.
    """

    name: str | None = Field(default=None, description="Name of the plan.")
    plan_description: str | None = Field(default=None, description="Detailed description of the plan and its objectives.")
    steps: list[SingleTaskUpdate] | None = Field(default=None, description="List of task updates. Only provided fields per task will be updated.")
    plan_notes: str | None = Field(default=None, description="Additional notes or context for the plan.")
    plan_completed: bool | None = Field(default=None, description="Indicates whether the plan has been completed.")
