"use client";

import { create } from "zustand";
import { apiClient } from "@/lib/api-client";
import { consumeSSE, type FolderRenameProgress } from "@/lib/sse";

// Types matching backend schemas
export interface FileInfo {
  key: string;
  size: number;
  last_modified: string;
  content_type: string | null;
}

export interface FileListResponse {
  files: FileInfo[];
  total: number;
}

export interface PresignedUploadResponse {
  url: string;
  fields: Record<string, string>;
  key: string;
}

export interface BatchPresignedUploadItem {
  filename: string;
  url: string;
  fields: Record<string, string>;
  key: string;
}

export interface BatchPresignedUploadResponse {
  uploads: BatchPresignedUploadItem[];
  total: number;
}

export interface PresignedDownloadResponse {
  url: string;
  expires_in: number;
}

export interface RenameResponse {
  success: boolean;
  old_path: string;
  new_path: string;
}

export interface UploadProgress {
  completed: number;
  total: number;
  currentFile: string;
}

export interface RenameProgress {
  total: number;
  completed: number;
  currentFile: string | null;
}

export interface FileTreeNode {
  name: string;
  path: string;
  isFolder: boolean;
  children: Map<string, FileTreeNode>;
  file?: FileInfo;
}

export interface EmptyFolder {
  path: string;
}

interface FilesState {
  // Data
  files: FileInfo[];
  emptyFolders: EmptyFolder[];
  selectedFile: string | null;
  expandedFolders: Set<string>;

  // Loading states
  isLoading: boolean;
  isUploading: boolean;
  isRenaming: boolean;

  // Progress tracking
  uploadProgress: UploadProgress | null;
  renameProgress: RenameProgress | null;

  // Error state
  error: string | null;

  // Actions
  fetchFiles: () => Promise<void>;
  setSelectedFile: (key: string | null) => void;
  toggleFolder: (path: string) => void;
  expandFolder: (path: string) => void;
  collapseFolder: (path: string) => void;
  setError: (error: string | null) => void;
  clearError: () => void;

  // File operations
  uploadFiles: (files: { file: File; path: string }[]) => Promise<void>;
  renameFile: (oldPath: string, newPath: string) => Promise<boolean>;
  renameFolder: (oldPath: string, newPath: string) => Promise<boolean>;
  deleteFile: (key: string) => Promise<boolean>;
  deleteFolder: (path: string) => Promise<boolean>;
  getDownloadUrl: (key: string) => Promise<string | null>;

  // Empty folders (client-side only)
  addEmptyFolder: (path: string) => void;
  removeEmptyFolder: (path: string) => void;
}

// Concurrency limit for uploads
const UPLOAD_CONCURRENCY = 5;

export const useFilesStore = create<FilesState>((set, get) => ({
  // Initial state
  files: [],
  emptyFolders: [],
  selectedFile: null,
  expandedFolders: new Set(),
  isLoading: false,
  isUploading: false,
  isRenaming: false,
  uploadProgress: null,
  renameProgress: null,
  error: null,

  // Fetch files from backend
  fetchFiles: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await apiClient.get<FileListResponse>("/files");
      set({ files: response.files, isLoading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load files";
      set({ error: message, isLoading: false });
    }
  },

  // Selection
  setSelectedFile: (key) => set({ selectedFile: key }),

  // Folder expansion
  toggleFolder: (path) => {
    set((state) => {
      const newExpanded = new Set(state.expandedFolders);
      if (newExpanded.has(path)) {
        newExpanded.delete(path);
      } else {
        newExpanded.add(path);
      }
      return { expandedFolders: newExpanded };
    });
  },

  expandFolder: (path) => {
    set((state) => {
      const newExpanded = new Set(state.expandedFolders);
      newExpanded.add(path);
      return { expandedFolders: newExpanded };
    });
  },

  collapseFolder: (path) => {
    set((state) => {
      const newExpanded = new Set(state.expandedFolders);
      newExpanded.delete(path);
      return { expandedFolders: newExpanded };
    });
  },

  // Error handling
  setError: (error) => set({ error }),
  clearError: () => set({ error: null }),

  // Upload files with progress tracking
  uploadFiles: async (filesToUpload) => {
    if (filesToUpload.length === 0) return;

    set({
      isUploading: true,
      uploadProgress: { completed: 0, total: filesToUpload.length, currentFile: "" },
      error: null,
    });

    try {
      // Get batch presigned URLs
      const batchRequest = filesToUpload.map(({ file, path }) => ({
        filename: path,
        content_type: file.type || null,
      }));

      const batchResponse = await apiClient.post<BatchPresignedUploadResponse>(
        "/files/presign/batch",
        { files: batchRequest }
      );

      // Create upload queue with concurrency limit
      let completed = 0;
      const uploadQueue = [...filesToUpload];
      const presignedMap = new Map(
        batchResponse.uploads.map((p) => [p.filename, p])
      );

      const uploadWorker = async (): Promise<void> => {
        while (uploadQueue.length > 0) {
          const item = uploadQueue.shift();
          if (!item) break;

          const presigned = presignedMap.get(item.path);
          if (!presigned) {
            throw new Error(`No presigned URL for ${item.path}`);
          }

          set((state) => ({
            uploadProgress: state.uploadProgress
              ? { ...state.uploadProgress, currentFile: item.path }
              : null,
          }));

          // Upload to S3
          const formData = new FormData();
          Object.entries(presigned.fields).forEach(([key, value]) => {
            formData.append(key, value);
          });
          formData.append("file", item.file);

          const uploadResponse = await fetch(presigned.url, {
            method: "POST",
            body: formData,
          });

          if (!uploadResponse.ok) {
            let errorDetail = uploadResponse.statusText;
            try {
              const errorText = await uploadResponse.text();
              if (errorText) errorDetail = errorText;
            } catch {
              // Ignore
            }
            throw new Error(`Upload failed for ${presigned.filename}: ${errorDetail}`);
          }

          completed++;
          set((state) => ({
            uploadProgress: state.uploadProgress
              ? { ...state.uploadProgress, completed, currentFile: item.path }
              : null,
          }));
        }
      };

      // Run workers in parallel
      const workers = Array(Math.min(UPLOAD_CONCURRENCY, filesToUpload.length))
        .fill(null)
        .map(() => uploadWorker());

      await Promise.all(workers);

      // Refresh file list
      await get().fetchFiles();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to upload files";
      set({ error: message });
    } finally {
      set({ isUploading: false, uploadProgress: null });
    }
  },

  // Rename a single file
  renameFile: async (oldPath, newPath) => {
    set({ isRenaming: true, error: null });
    try {
      await apiClient.post<RenameResponse>("/files/rename", {
        old_path: oldPath,
        new_path: newPath,
      });

      // Update selected file if it was the renamed one
      const { selectedFile } = get();
      if (selectedFile === oldPath) {
        set({ selectedFile: newPath });
      }

      await get().fetchFiles();
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to rename file";
      set({ error: message });
      return false;
    } finally {
      set({ isRenaming: false });
    }
  },

  // Rename a folder with SSE progress
  renameFolder: async (oldPath, newPath) => {
    set({
      isRenaming: true,
      renameProgress: { total: 0, completed: 0, currentFile: null },
      error: null,
    });

    return new Promise<boolean>((resolve) => {
      consumeSSE(
        "/files/rename/folder",
        { old_path: oldPath, new_path: newPath },
        {
          onEvent: (event) => {
            const data = event.data as FolderRenameProgress;

            if (data.event === "progress") {
              set({
                renameProgress: {
                  total: data.total,
                  completed: data.completed,
                  currentFile: data.current_file,
                },
              });
            } else if (data.event === "complete") {
              set({ renameProgress: null, isRenaming: false });

              // Update selected file if it was under the renamed folder
              const { selectedFile } = get();
              if (selectedFile?.startsWith(oldPath + "/")) {
                const newSelectedPath = selectedFile.replace(oldPath, newPath);
                set({ selectedFile: newSelectedPath });
              }

              get().fetchFiles();
              resolve(true);
            } else if (data.event === "error") {
              set({
                error: data.error || "Failed to rename folder",
                renameProgress: null,
                isRenaming: false,
              });
              resolve(false);
            }
          },
          onError: (err) => {
            set({
              error: err.message,
              renameProgress: null,
              isRenaming: false,
            });
            resolve(false);
          },
        }
      ).catch(() => {
        // Error already handled in onError
        resolve(false);
      });
    });
  },

  // Delete a file
  deleteFile: async (key) => {
    set({ error: null });
    try {
      await apiClient.delete(`/files/${encodeURIComponent(key)}`);

      // Clear selection if deleted file was selected
      const { selectedFile } = get();
      if (selectedFile === key) {
        set({ selectedFile: null });
      }

      await get().fetchFiles();
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to delete file";
      set({ error: message });
      return false;
    }
  },

  // Delete a folder
  deleteFolder: async (path) => {
    set({ error: null });
    try {
      await apiClient.delete(`/files/folder/${encodeURIComponent(path)}`);

      // Clear selection if deleted folder contained selected file
      const { selectedFile } = get();
      if (selectedFile?.startsWith(path + "/")) {
        set({ selectedFile: null });
      }

      await get().fetchFiles();
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to delete folder";
      set({ error: message });
      return false;
    }
  },

  // Get presigned download URL
  getDownloadUrl: async (key) => {
    try {
      const response = await apiClient.get<PresignedDownloadResponse>(
        `/files/${encodeURIComponent(key)}/download`
      );
      return response.url;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to get download URL";
      set({ error: message });
      return null;
    }
  },

  // Empty folders (client-side tracking)
  addEmptyFolder: (path) => {
    set((state) => ({
      emptyFolders: [...state.emptyFolders, { path }],
    }));
  },

  removeEmptyFolder: (path) => {
    set((state) => ({
      emptyFolders: state.emptyFolders.filter((f) => f.path !== path),
    }));
  },
}));

/**
 * Build a tree structure from flat file list.
 */
export function buildFileTree(
  files: FileInfo[],
  emptyFolders: EmptyFolder[]
): FileTreeNode {
  const root: FileTreeNode = {
    name: "",
    path: "",
    isFolder: true,
    children: new Map(),
  };

  // Add files to tree
  for (const file of files) {
    const parts = file.key.split("/");
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      const currentPath = parts.slice(0, i + 1).join("/");

      if (!current.children.has(part)) {
        current.children.set(part, {
          name: part,
          path: currentPath,
          isFolder: !isLast,
          children: new Map(),
          file: isLast ? file : undefined,
        });
      }

      current = current.children.get(part)!;
    }
  }

  // Add empty folders to tree
  for (const folder of emptyFolders) {
    const parts = folder.path.split("/");
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const currentPath = parts.slice(0, i + 1).join("/");

      if (!current.children.has(part)) {
        current.children.set(part, {
          name: part,
          path: currentPath,
          isFolder: true,
          children: new Map(),
        });
      }

      current = current.children.get(part)!;
    }
  }

  return root;
}

/**
 * Format file size for display.
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

/**
 * Format date for display.
 */
export function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
