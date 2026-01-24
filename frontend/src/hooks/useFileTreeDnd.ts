"use client";

import { useState, useCallback } from "react";
import {
  DndContext,
  DragEndEvent,
  DragOverEvent,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
  DragOverlay,
} from "@dnd-kit/core";
import { apiClient } from "@/lib/api-client";

export interface FileTreeNode {
  name: string;
  path: string;
  isFolder: boolean;
  children: Map<string, FileTreeNode>;
  file?: {
    key: string;
    size: number;
    last_modified: string;
    content_type: string | null;
  };
}

interface MoveResponse {
  success: boolean;
  source_path: string;
  destination_path: string;
  is_folder: boolean;
  files_moved: number;
}

interface UseFileTreeDndOptions {
  /** Callback when a move operation completes successfully */
  onMoveComplete?: () => void;
  /** Callback when a move operation fails */
  onMoveError?: (error: string) => void;
}

interface UseFileTreeDndReturn {
  /** The DndContext sensors configuration */
  sensors: ReturnType<typeof useSensors>;
  /** Currently dragging item info */
  draggedItem: { id: string; name: string; isFolder: boolean } | null;
  /** ID of folder currently being hovered over */
  overFolderId: string | null;
  /** Whether a move operation is in progress */
  isMoving: boolean;
  /** Handler for drag start events */
  handleDragStart: (event: DragStartEvent) => void;
  /** Handler for drag over events */
  handleDragOver: (event: DragOverEvent) => void;
  /** Handler for drag end events */
  handleDragEnd: (event: DragEndEvent) => void;
  /** Handler for drag cancel events */
  handleDragCancel: () => void;
  /** Check if a drop target is valid for the current drag item */
  isValidDropTarget: (targetPath: string, targetIsFolder: boolean) => boolean;
  /** DragOverlay component for rendering the dragged item */
  DragOverlayComponent: typeof DragOverlay;
  /** DndContext component for wrapping the tree */
  DndContextComponent: typeof DndContext;
}

/**
 * Check if a path is nested under another path.
 * Used to prevent moving a folder into itself or its descendants.
 */
function isPathNested(parentPath: string, childPath: string): boolean {
  const normalizedParent = parentPath.replace(/\/$/, "");
  const normalizedChild = childPath.replace(/\/$/, "");

  return (
    normalizedChild.startsWith(normalizedParent + "/") ||
    normalizedChild === normalizedParent
  );
}

/**
 * Get the parent folder path from a file/folder path.
 */
function getParentPath(path: string): string {
  const parts = path.split("/");
  parts.pop();
  return parts.join("/");
}

/**
 * Hook for managing drag-and-drop file/folder moves in a file tree.
 *
 * Provides:
 * - Drag sensors configuration
 * - Drag state management (draggedItem, overFolderId)
 * - Move validation (prevents moving folder into itself)
 * - API call handling for move operations
 *
 * Usage:
 * ```tsx
 * const { sensors, handleDragStart, handleDragEnd, ... } = useFileTreeDnd({
 *   onMoveComplete: () => refreshFiles(),
 *   onMoveError: (error) => setError(error),
 * });
 *
 * return (
 *   <DndContext
 *     sensors={sensors}
 *     onDragStart={handleDragStart}
 *     onDragEnd={handleDragEnd}
 *     ...
 *   >
 *     <FileTree />
 *   </DndContext>
 * );
 * ```
 */
export function useFileTreeDnd({
  onMoveComplete,
  onMoveError,
}: UseFileTreeDndOptions = {}): UseFileTreeDndReturn {
  const [draggedItem, setDraggedItem] = useState<{
    id: string;
    name: string;
    isFolder: boolean;
  } | null>(null);
  const [overFolderId, setOverFolderId] = useState<string | null>(null);
  const [isMoving, setIsMoving] = useState(false);

  // Configure pointer sensor with activation constraint
  // to prevent accidental drags when clicking
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // Require 8px drag before activating
      },
    })
  );

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const { active } = event;
    const data = active.data.current as {
      name: string;
      isFolder: boolean;
    } | undefined;

    if (data) {
      setDraggedItem({
        id: String(active.id),
        name: data.name,
        isFolder: data.isFolder,
      });
    }
  }, []);

  const handleDragOver = useCallback((event: DragOverEvent) => {
    const { over } = event;

    if (over && over.data.current?.isFolder) {
      setOverFolderId(String(over.id));
    } else {
      setOverFolderId(null);
    }
  }, []);

  const handleDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const { active, over } = event;
      setDraggedItem(null);
      setOverFolderId(null);

      // No drop target
      if (!over) return;

      const sourcePath = String(active.id);
      const targetData = over.data.current as {
        isFolder: boolean;
        path: string;
      } | undefined;

      // Must drop on a folder
      if (!targetData?.isFolder) return;

      const targetFolderPath = String(over.id);

      // Can't drop on itself
      if (sourcePath === targetFolderPath) return;

      // Can't move folder into itself or its children
      if (isPathNested(sourcePath, targetFolderPath)) {
        onMoveError?.("Cannot move a folder into itself or its subdirectories");
        return;
      }

      // Can't move to the same parent (no-op)
      const sourceParent = getParentPath(sourcePath);
      if (sourceParent === targetFolderPath) return;

      // Calculate destination path
      const sourceName = sourcePath.split("/").pop() || sourcePath;
      const destinationPath = targetFolderPath
        ? `${targetFolderPath}/${sourceName}`
        : sourceName;

      // Perform the move
      setIsMoving(true);
      try {
        await apiClient.post<MoveResponse>("/files/move", {
          source_path: sourcePath,
          destination_path: destinationPath,
        });
        onMoveComplete?.();
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to move file";
        onMoveError?.(message);
      } finally {
        setIsMoving(false);
      }
    },
    [onMoveComplete, onMoveError]
  );

  const handleDragCancel = useCallback(() => {
    setDraggedItem(null);
    setOverFolderId(null);
  }, []);

  const isValidDropTarget = useCallback(
    (targetPath: string, targetIsFolder: boolean): boolean => {
      if (!draggedItem || !targetIsFolder) return false;

      // Can't drop on itself
      if (draggedItem.id === targetPath) return false;

      // Can't move folder into itself or its children
      if (draggedItem.isFolder && isPathNested(draggedItem.id, targetPath)) {
        return false;
      }

      // Can't drop on current parent (no-op)
      const sourceParent = getParentPath(draggedItem.id);
      if (sourceParent === targetPath) return false;

      return true;
    },
    [draggedItem]
  );

  return {
    sensors,
    draggedItem,
    overFolderId,
    isMoving,
    handleDragStart,
    handleDragOver,
    handleDragEnd,
    handleDragCancel,
    isValidDropTarget,
    DragOverlayComponent: DragOverlay,
    DndContextComponent: DndContext,
  };
}
