from datetime import datetime
from pydantic import BaseModel, Field
from app.core.config import settings
from typing import Literal
from uuid import uuid4

from zoneinfo import ZoneInfo
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
    steps: list[SingleTask] = Field(default=[], description="List of tasks that make up the plan.")
    plan_notes: str | None = Field(default=None, description="Additional notes or context for the plan.", examples=["Include budget considerations.", "Outline key milestones."])
    plan_completed: bool = Field(default=False, description="Indicates whether the plan has been completed.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=tz), description="Timestamp when the plan was created.")
    updated_at: datetime | None = Field(default=None, description="Timestamp when the plan was last updated.")
