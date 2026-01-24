/**
 * Plan types for AI assistant planning functionality.
 */

export type PlanTaskStatus = "pending" | "in_progress" | "completed";

export interface PlanTask {
  id: string;
  plan_id: string;
  description: string;
  notes: string | null;
  status: PlanTaskStatus;
  is_completed: boolean;
  position: number;
  created_at: string;
  updated_at: string | null;
}

export interface Plan {
  id: string;
  user_id: string;
  name: string;
  description: string;
  notes: string | null;
  is_completed: boolean;
  tasks: PlanTask[];
  created_at: string;
  updated_at: string | null;
}

export interface PlanSummary {
  id: string;
  name: string;
  description: string;
  is_completed: boolean;
  task_count: number;
  completed_task_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface PlanListResponse {
  items: PlanSummary[];
  total: number;
  skip: number;
  limit: number;
}

export interface CreatePlan {
  name: string;
  description?: string;
  notes?: string | null;
  is_completed?: boolean;
  tasks?: CreatePlanTask[];
}

export interface UpdatePlan {
  name?: string;
  description?: string;
  notes?: string | null;
  is_completed?: boolean;
}

export interface CreatePlanTask {
  description: string;
  notes?: string | null;
  status?: PlanTaskStatus;
  is_completed?: boolean;
  position?: number;
}

export interface UpdatePlanTask {
  description?: string;
  notes?: string | null;
  status?: PlanTaskStatus;
  is_completed?: boolean;
  position?: number;
}

export interface TaskReorderRequest {
  task_ids: string[];
}
