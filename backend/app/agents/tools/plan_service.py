from datetime import datetime
from uuid import uuid4
from app.core.config import settings
from app.schemas.planning import Plan
from zoneinfo import ZoneInfo
tz = ZoneInfo(settings.TZ)


class PlanStore:
    def __init__(self):
        self.plans: dict[str, Plan] = {}

    def update_plan(self, plan_id: str, plan_data: Plan):
        if plan_id not in self.plans:
            return f"plan {plan_id} not found"
        
        for in_task in plan_data.steps:
            for existing_task in self.plans[plan_id].steps:
                if in_task.id == existing_task.id:
                    existing_task.task_description = in_task.task_description
                    existing_task.task_notes = in_task.task_notes
                    existing_task.task_completed = in_task.task_completed
                    existing_task.task_status = in_task.task_status
                    existing_task.task_position = in_task.task_position
                else:
                    self.plans[plan_id].steps.append(in_task)
                    
        self.plans[plan_id].updated_at = datetime.now(tz=tz)
        
        return f"plan {plan_id} updated"        

        
    def create_plan(self, plan_data: Plan) -> str:
        plan_id = plan_data.id
        self.plans[plan_id] = plan_data
        return plan_id

    def get_plan(self, plan_id: str) -> Plan | str:
        if plan_id in self.plans:
            return self.plans[plan_id]
        else:
            return f"plan {plan_id} not found"
        
    def delete_plan(self, plan_id: str) -> str:
        if plan_id in self.plans:
            del self.plans[plan_id]
            return f"plan {plan_id} deleted"
        return f"plan {plan_id} not found"

    def get_all_plans(self) -> list:
        export_list = []
        for plan in self.plans.values():
            export_list.append((plan.id, plan.name, plan.plan_description))
        return export_list

plan_service = PlanStore()

def get_plan_service():
    return plan_service