"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/hooks";
import { apiClient, ApiError } from "@/lib/api-client";
import type {
  Plan,
  PlanSummary,
  PlanTask,
  PlanListResponse,
  CreatePlan,
  UpdatePlan,
  CreatePlanTask,
  UpdatePlanTask,
  PlanTaskStatus,
} from "@/types";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Button,
  Input,
  Label,
  Badge,
  Checkbox,
} from "@/components/ui";
import {
  Plus,
  X,
  Loader2,
  ChevronDown,
  ChevronRight,
  Trash2,
  Pencil,
  GripVertical,
  Check,
  Circle,
  Clock,
  CheckCircle2,
} from "lucide-react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { cn } from "@/lib/utils";

// =============================================================================
// Sortable Task Item Component
// =============================================================================

interface SortableTaskItemProps {
  task: PlanTask;
  onUpdate: (taskId: string, data: UpdatePlanTask) => Promise<void>;
  onDelete: (taskId: string) => Promise<void>;
  isUpdating: boolean;
}

function SortableTaskItem({
  task,
  onUpdate,
  onDelete,
  isUpdating,
}: SortableTaskItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editDescription, setEditDescription] = useState(task.description);
  const [editNotes, setEditNotes] = useState(task.notes || "");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const handleSave = async () => {
    await onUpdate(task.id, {
      description: editDescription,
      notes: editNotes || null,
    });
    setIsEditing(false);
  };

  const handleStatusChange = async (status: PlanTaskStatus) => {
    await onUpdate(task.id, {
      status,
      is_completed: status === "completed",
    });
  };

  const handleDelete = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    await onDelete(task.id);
  };

  const statusIcon = {
    pending: <Circle className="h-4 w-4 text-muted-foreground" />,
    in_progress: <Clock className="h-4 w-4 text-blue-500" />,
    completed: <CheckCircle2 className="h-4 w-4 text-green-500" />,
  };

  const statusBadge = {
    pending: "secondary",
    in_progress: "default",
    completed: "outline",
  } as const;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "flex items-start gap-2 p-3 bg-muted/30 rounded-lg border",
        isDragging && "opacity-50 shadow-lg",
        task.is_completed && "opacity-60"
      )}
    >
      <button
        {...attributes}
        {...listeners}
        className="cursor-grab touch-none p-1 hover:bg-muted rounded"
        disabled={isUpdating}
      >
        <GripVertical className="h-4 w-4 text-muted-foreground" />
      </button>

      <div className="flex-1 min-w-0">
        {isEditing ? (
          <div className="space-y-2">
            <Input
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              placeholder="Task description"
              disabled={isUpdating}
            />
            <Input
              value={editNotes}
              onChange={(e) => setEditNotes(e.target.value)}
              placeholder="Notes (optional)"
              disabled={isUpdating}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={handleSave} disabled={isUpdating}>
                {isUpdating ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  "Save"
                )}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setIsEditing(false);
                  setEditDescription(task.description);
                  setEditNotes(task.notes || "");
                }}
                disabled={isUpdating}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div>
            <p
              className={cn(
                "text-sm font-medium",
                task.is_completed && "line-through"
              )}
            >
              {task.description}
            </p>
            {task.notes && (
              <p className="text-xs text-muted-foreground mt-1">{task.notes}</p>
            )}
          </div>
        )}
      </div>

      {!isEditing && (
        <div className="flex items-center gap-2">
          <select
            value={task.status}
            onChange={(e) =>
              handleStatusChange(e.target.value as PlanTaskStatus)
            }
            disabled={isUpdating}
            className="h-8 text-xs rounded-md border border-input bg-background px-2"
          >
            <option value="pending">Pending</option>
            <option value="in_progress">In Progress</option>
            <option value="completed">Completed</option>
          </select>

          <Button
            size="sm"
            variant="ghost"
            onClick={() => setIsEditing(true)}
            disabled={isUpdating}
          >
            <Pencil className="h-3 w-3" />
          </Button>

          <Button
            size="sm"
            variant="ghost"
            onClick={handleDelete}
            disabled={isUpdating}
            className={cn(confirmDelete && "text-destructive")}
          >
            {isUpdating ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Trash2 className="h-3 w-3" />
            )}
          </Button>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Expandable Plan Card Component
// =============================================================================

interface PlanCardProps {
  plan: PlanSummary;
  onToggleComplete: (planId: string, isCompleted: boolean) => Promise<void>;
  onEdit: (plan: PlanSummary) => void;
  onDelete: (planId: string) => Promise<void>;
  isUpdating: boolean;
}

function PlanCard({
  plan,
  onToggleComplete,
  onEdit,
  onDelete,
  isUpdating,
}: PlanCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [fullPlan, setFullPlan] = useState<Plan | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [taskUpdating, setTaskUpdating] = useState<string | null>(null);
  const [showAddTask, setShowAddTask] = useState(false);
  const [newTaskDescription, setNewTaskDescription] = useState("");
  const [newTaskNotes, setNewTaskNotes] = useState("");
  const [addingTask, setAddingTask] = useState(false);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const fetchFullPlan = useCallback(async () => {
    if (fullPlan) return;
    setLoadingPlan(true);
    try {
      const data = await apiClient.get<Plan>(`/plans/${plan.id}`);
      setFullPlan(data);
    } catch (err) {
      console.error("Failed to fetch plan details:", err);
    } finally {
      setLoadingPlan(false);
    }
  }, [plan.id, fullPlan]);

  const handleExpand = async () => {
    if (!isExpanded) {
      await fetchFullPlan();
    }
    setIsExpanded(!isExpanded);
  };

  const handleDelete = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    await onDelete(plan.id);
    setConfirmDelete(false);
  };

  const handleTaskUpdate = async (taskId: string, data: UpdatePlanTask) => {
    setTaskUpdating(taskId);
    try {
      const updated = await apiClient.patch<PlanTask>(
        `/plans/tasks/${taskId}`,
        data
      );
      if (fullPlan) {
        setFullPlan({
          ...fullPlan,
          tasks: fullPlan.tasks.map((t) => (t.id === taskId ? updated : t)),
        });
      }
    } catch (err) {
      console.error("Failed to update task:", err);
    } finally {
      setTaskUpdating(null);
    }
  };

  const handleTaskDelete = async (taskId: string) => {
    setTaskUpdating(taskId);
    try {
      await apiClient.delete(`/plans/tasks/${taskId}`);
      if (fullPlan) {
        setFullPlan({
          ...fullPlan,
          tasks: fullPlan.tasks.filter((t) => t.id !== taskId),
        });
      }
    } catch (err) {
      console.error("Failed to delete task:", err);
    } finally {
      setTaskUpdating(null);
    }
  };

  const handleAddTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTaskDescription.trim()) return;

    setAddingTask(true);
    try {
      const newTask = await apiClient.post<PlanTask>(`/plans/${plan.id}/tasks`, {
        description: newTaskDescription,
        notes: newTaskNotes || null,
      });
      if (fullPlan) {
        setFullPlan({
          ...fullPlan,
          tasks: [...fullPlan.tasks, newTask],
        });
      }
      setNewTaskDescription("");
      setNewTaskNotes("");
      setShowAddTask(false);
    } catch (err) {
      console.error("Failed to add task:", err);
    } finally {
      setAddingTask(false);
    }
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || !fullPlan) return;

    const oldIndex = fullPlan.tasks.findIndex((t) => t.id === active.id);
    const newIndex = fullPlan.tasks.findIndex((t) => t.id === over.id);

    const newTasks = arrayMove(fullPlan.tasks, oldIndex, newIndex);
    setFullPlan({ ...fullPlan, tasks: newTasks });

    try {
      await apiClient.put(`/plans/${plan.id}/tasks/reorder`, {
        task_ids: newTasks.map((t: PlanTask) => t.id),
      });
    } catch (err) {
      console.error("Failed to reorder tasks:", err);
      // Revert on error
      setFullPlan({ ...fullPlan, tasks: fullPlan.tasks });
    }
  };

  const progress =
    plan.task_count > 0
      ? Math.round((plan.completed_task_count / plan.task_count) * 100)
      : 0;

  return (
    <Card className={cn(plan.is_completed && "opacity-70")}>
      <CardHeader className="pb-2">
        <div className="flex items-start gap-3">
          <Checkbox
            checked={plan.is_completed}
            onCheckedChange={(checked) =>
              onToggleComplete(plan.id, checked as boolean)
            }
            disabled={isUpdating}
            className="mt-1"
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <button
                onClick={handleExpand}
                className="flex items-center gap-1 hover:text-primary"
              >
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                <CardTitle
                  className={cn(
                    "text-lg",
                    plan.is_completed && "line-through"
                  )}
                >
                  {plan.name}
                </CardTitle>
              </button>
              {plan.is_completed && (
                <Badge variant="outline" className="text-green-600">
                  Completed
                </Badge>
              )}
            </div>
            {plan.description && (
              <p className="text-sm text-muted-foreground mt-1">
                {plan.description}
              </p>
            )}
            {plan.task_count > 0 && (
              <div className="flex items-center gap-2 mt-2">
                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden max-w-[200px]">
                  <div
                    className="h-full bg-primary transition-all"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <span className="text-xs text-muted-foreground">
                  {plan.completed_task_count}/{plan.task_count} tasks
                </span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onEdit(plan)}
              disabled={isUpdating}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleDelete}
              disabled={isUpdating}
              className={cn(confirmDelete && "text-destructive")}
            >
              {isUpdating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </CardHeader>

      {isExpanded && (
        <CardContent className="pt-0">
          {loadingPlan ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : fullPlan ? (
            <div className="space-y-3 mt-4">
              {fullPlan.notes && (
                <div className="p-3 bg-muted/50 rounded-lg">
                  <p className="text-sm text-muted-foreground">
                    <strong>Notes:</strong> {fullPlan.notes}
                  </p>
                </div>
              )}

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-medium">Tasks</h4>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowAddTask(!showAddTask)}
                  >
                    <Plus className="h-3 w-3 mr-1" />
                    Add Task
                  </Button>
                </div>

                {showAddTask && (
                  <form
                    onSubmit={handleAddTask}
                    className="p-3 bg-muted/30 rounded-lg border space-y-2"
                  >
                    <Input
                      value={newTaskDescription}
                      onChange={(e) => setNewTaskDescription(e.target.value)}
                      placeholder="Task description"
                      disabled={addingTask}
                    />
                    <Input
                      value={newTaskNotes}
                      onChange={(e) => setNewTaskNotes(e.target.value)}
                      placeholder="Notes (optional)"
                      disabled={addingTask}
                    />
                    <div className="flex gap-2">
                      <Button size="sm" type="submit" disabled={addingTask}>
                        {addingTask ? (
                          <Loader2 className="h-3 w-3 animate-spin mr-1" />
                        ) : (
                          <Plus className="h-3 w-3 mr-1" />
                        )}
                        Add
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        type="button"
                        onClick={() => {
                          setShowAddTask(false);
                          setNewTaskDescription("");
                          setNewTaskNotes("");
                        }}
                        disabled={addingTask}
                      >
                        Cancel
                      </Button>
                    </div>
                  </form>
                )}

                {fullPlan.tasks.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    No tasks yet. Add one to get started!
                  </p>
                ) : (
                  <DndContext
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    onDragEnd={handleDragEnd}
                  >
                    <SortableContext
                      items={fullPlan.tasks.map((t) => t.id)}
                      strategy={verticalListSortingStrategy}
                    >
                      <div className="space-y-2">
                        {fullPlan.tasks.map((task) => (
                          <SortableTaskItem
                            key={task.id}
                            task={task}
                            onUpdate={handleTaskUpdate}
                            onDelete={handleTaskDelete}
                            isUpdating={taskUpdating === task.id}
                          />
                        ))}
                      </div>
                    </SortableContext>
                  </DndContext>
                )}
              </div>
            </div>
          ) : null}
        </CardContent>
      )}
    </Card>
  );
}

// =============================================================================
// Main Plans Page
// =============================================================================

export default function PlansPage() {
  const { isAuthenticated } = useAuth();

  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const limit = 20;

  // Filters
  const [hideCompleted, setHideCompleted] = useState(false);

  // Action states
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Create/Edit modal
  const [showModal, setShowModal] = useState(false);
  const [editingPlan, setEditingPlan] = useState<PlanSummary | null>(null);
  const [formData, setFormData] = useState<CreatePlan>({
    name: "",
    description: "",
    notes: null,
    is_completed: false,
  });
  const [formLoading, setFormLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchPlans = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params: Record<string, string> = {
        skip: String(skip),
        limit: String(limit),
        include_completed: String(!hideCompleted),
      };

      const data = await apiClient.get<PlanListResponse>("/plans", { params });
      setPlans(data.items);
      setTotal(data.total);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to fetch plans");
      }
    } finally {
      setLoading(false);
    }
  }, [skip, hideCompleted]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchPlans();
    }
  }, [isAuthenticated, fetchPlans]);

  const handleToggleComplete = async (planId: string, isCompleted: boolean) => {
    setActionLoading(planId);
    try {
      await apiClient.patch(`/plans/${planId}`, { is_completed: isCompleted });
      await fetchPlans();
    } catch (err) {
      console.error("Failed to update plan:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (planId: string) => {
    setActionLoading(planId);
    try {
      await apiClient.delete(`/plans/${planId}`);
      await fetchPlans();
    } catch (err) {
      console.error("Failed to delete plan:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const handleEdit = (plan: PlanSummary) => {
    setEditingPlan(plan);
    setFormData({
      name: plan.name,
      description: plan.description,
      notes: null, // Would need to fetch full plan for notes
      is_completed: plan.is_completed,
    });
    setFormError(null);
    setShowModal(true);
  };

  const handleCreate = () => {
    setEditingPlan(null);
    setFormData({
      name: "",
      description: "",
      notes: null,
      is_completed: false,
    });
    setFormError(null);
    setShowModal(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormLoading(true);
    setFormError(null);

    try {
      if (editingPlan) {
        await apiClient.patch<Plan>(`/plans/${editingPlan.id}`, {
          name: formData.name,
          description: formData.description,
          notes: formData.notes,
          is_completed: formData.is_completed,
        } as UpdatePlan);
      } else {
        await apiClient.post<Plan>("/plans", formData);
      }
      setShowModal(false);
      await fetchPlans();
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(err.message);
      } else {
        setFormError(editingPlan ? "Failed to update plan" : "Failed to create plan");
      }
    } finally {
      setFormLoading(false);
    }
  };

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(skip / limit) + 1;

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Card className="p-6 text-center">
          <p className="text-muted-foreground">
            Please log in to view your plans.
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold">Plans</h1>
          <p className="text-sm sm:text-base text-muted-foreground">
            Manage your plans and tasks
          </p>
        </div>
        <Button onClick={handleCreate}>
          <Plus className="h-4 w-4 mr-2" />
          New Plan
        </Button>
      </div>

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <Card className="w-full max-w-md mx-4">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>
                {editingPlan ? "Edit Plan" : "Create New Plan"}
              </CardTitle>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowModal(false);
                  setFormError(null);
                }}
              >
                <X className="h-4 w-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Name</Label>
                  <Input
                    id="name"
                    value={formData.name}
                    onChange={(e) =>
                      setFormData({ ...formData, name: e.target.value })
                    }
                    placeholder="Plan name"
                    required
                    disabled={formLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="description">Description</Label>
                  <Input
                    id="description"
                    value={formData.description}
                    onChange={(e) =>
                      setFormData({ ...formData, description: e.target.value })
                    }
                    placeholder="What is this plan about?"
                    disabled={formLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="notes">Notes (optional)</Label>
                  <textarea
                    id="notes"
                    value={formData.notes || ""}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        notes: e.target.value || null,
                      })
                    }
                    placeholder="Additional notes..."
                    disabled={formLoading}
                    className="w-full min-h-[80px] rounded-md border border-input bg-background px-3 py-2 text-sm"
                  />
                </div>
                {editingPlan && (
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="is_completed"
                      checked={formData.is_completed}
                      onCheckedChange={(checked) =>
                        setFormData({
                          ...formData,
                          is_completed: checked as boolean,
                        })
                      }
                      disabled={formLoading}
                    />
                    <Label htmlFor="is_completed">Mark as completed</Label>
                  </div>
                )}
                {formError && (
                  <p className="text-sm text-destructive">{formError}</p>
                )}
                <div className="flex gap-2 justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setShowModal(false);
                      setFormError(null);
                    }}
                    disabled={formLoading}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" disabled={formLoading}>
                    {formLoading ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        {editingPlan ? "Saving..." : "Creating..."}
                      </>
                    ) : editingPlan ? (
                      "Save Changes"
                    ) : (
                      "Create Plan"
                    )}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filters */}
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={hideCompleted}
              onCheckedChange={(checked) => {
                setHideCompleted(checked as boolean);
                setSkip(0);
              }}
            />
            Hide completed plans
          </label>
          <span className="text-sm text-muted-foreground">
            Showing {plans.length} of {total} plans
          </span>
        </div>
      </Card>

      {/* Error State */}
      {error && (
        <Card className="p-4 border-destructive">
          <p className="text-destructive">{error}</p>
        </Card>
      )}

      {/* Plans List */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : plans.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-muted-foreground mb-4">
            {hideCompleted
              ? "No active plans. Create one or show completed plans."
              : "No plans yet. Create your first plan to get started!"}
          </p>
          <Button onClick={handleCreate}>
            <Plus className="h-4 w-4 mr-2" />
            Create Plan
          </Button>
        </Card>
      ) : (
        <div className="space-y-4">
          {plans.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              onToggleComplete={handleToggleComplete}
              onEdit={handleEdit}
              onDelete={handleDelete}
              isUpdating={actionLoading === plan.id}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSkip(Math.max(0, skip - limit))}
            disabled={skip === 0}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {currentPage} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSkip(skip + limit)}
            disabled={currentPage >= totalPages}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
