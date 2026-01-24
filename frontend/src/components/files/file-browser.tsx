"use client";

import { useState, useCallback, useRef, useMemo } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogClose, DialogBody } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { apiClient } from "@/lib/api-client";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { useFileTreeDnd } from "@/hooks/useFileTreeDnd";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { 
  FolderOpen, 
  Upload, 
  Download, 
  Trash2, 
  RefreshCw, 
  File,
  Folder,
  AlertCircle,
  Loader2,
  FolderUp,
  ChevronRight,
  ChevronDown,
  Eye,
  FolderPlus,
  GripVertical,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface FileInfo {
  key: string;
  size: number;
  last_modified: string;
  content_type: string | null;
}

interface FileListResponse {
  files: FileInfo[];
  total: number;
}

interface PresignedUploadResponse {
  url: string;
  fields: Record<string, string>;
  key: string;
}

interface PresignedDownloadResponse {
  url: string;
  expires_in: number;
}

interface BatchFileItem {
  filename: string;
  content_type: string | null;
}

interface BatchPresignedUploadItem {
  filename: string;
  url: string;
  fields: Record<string, string>;
  key: string;
}

interface BatchPresignedUploadResponse {
  uploads: BatchPresignedUploadItem[];
  total: number;
}

interface FileContentResponse {
  key: string;
  content: string;
  content_type: string | null;
  size: number;
  is_binary: boolean;
  is_truncated: boolean;
}

interface FilePreviewData {
  key: string;
  content_type: string | null;
  size: number;
  // For images: presigned URL for direct loading
  presigned_url?: string;
  // For text files: actual content
  content?: string;
  is_binary: boolean;
  is_truncated: boolean;
}

interface UploadProgress {
  completed: number;
  total: number;
  currentFile: string;
}

interface EmptyFolder {
  path: string;
}

interface FileTreeNode {
  name: string;
  path: string;
  isFolder: boolean;
  children: Map<string, FileTreeNode>;
  file?: FileInfo;
}

interface FileBrowserProps {
  children?: React.ReactNode;
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Build a tree structure from flat file list
 */
function buildFileTree(files: FileInfo[], emptyFolders: EmptyFolder[]): FileTreeNode {
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

export function FileBrowser({ children }: FileBrowserProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [emptyFolders, setEmptyFolders] = useState<EmptyFolder[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const [previewFile, setPreviewFile] = useState<FilePreviewData | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [showNewFolderInput, setShowNewFolderInput] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  // Concurrency limit for uploads
  const UPLOAD_CONCURRENCY = 5;

  // Build file tree from flat list
  const fileTree = useMemo(
    () => buildFileTree(files, emptyFolders),
    [files, emptyFolders]
  );

  // Drag and drop file move functionality
  const {
    sensors,
    draggedItem,
    overFolderId,
    isMoving,
    handleDragStart,
    handleDragOver,
    handleDragEnd,
    handleDragCancel,
    isValidDropTarget,
    DragOverlayComponent,
    DndContextComponent,
  } = useFileTreeDnd({
    onMoveComplete: () => {
      fetchFiles();
    },
    onMoveError: (errorMsg) => {
      setError(errorMsg);
    },
  });

  const toggleFolder = useCallback((path: string) => {
    setCollapsedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const fetchFiles = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiClient.get<FileListResponse>("/files");
      setFiles(response.files);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load files");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleOpen = useCallback(() => {
    setIsOpen(true);
    fetchFiles();
  }, [fetchFiles]);

  /**
   * Create a new folder by uploading a placeholder file
   */
  const createFolder = async (folderName: string) => {
    if (!folderName.trim()) return;

    setIsCreatingFolder(true);
    setError(null);
    try {
      // Create folder by uploading a .gitkeep placeholder
      const folderPath = `${folderName.trim()}/.gitkeep`;
      const presigned = await apiClient.post<PresignedUploadResponse>("/files/presign", {
        filename: folderPath,
        content_type: "text/plain",
      });

      // Upload empty file
      const formData = new FormData();
      Object.entries(presigned.fields).forEach(([key, value]) => {
        formData.append(key, value);
      });
      formData.append("file", new Blob([""], { type: "text/plain" }), ".gitkeep");

      const uploadResponse = await fetch(presigned.url, {
        method: "POST",
        body: formData,
      });

      if (!uploadResponse.ok) {
        throw new Error("Failed to create folder");
      }

      await fetchFiles();
      setNewFolderName("");
      setShowNewFolderInput(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create folder");
    } finally {
      setIsCreatingFolder(false);
    }
  };

  /**
   * Upload a single file to S3 using presigned POST
   */
  const uploadSingleFile = async (
    file: File,
    presigned: BatchPresignedUploadItem
  ): Promise<void> => {
    const formData = new FormData();
    Object.entries(presigned.fields).forEach(([key, value]) => {
      formData.append(key, value);
    });
    formData.append("file", file);

    const uploadResponse = await fetch(presigned.url, {
      method: "POST",
      body: formData,
    });

    if (!uploadResponse.ok) {
      // Try to get more details from the response
      let errorDetail = uploadResponse.statusText;
      try {
        const errorText = await uploadResponse.text();
        if (errorText) {
          errorDetail = errorText;
        }
      } catch {
        // Ignore error reading response
      }
      throw new Error(`Upload failed for ${presigned.filename}: ${errorDetail}`);
    }
  };

  /**
   * Upload multiple files with concurrency limit and progress tracking
   */
  const uploadFilesWithProgress = async (
    filesToUpload: { file: File; path: string }[]
  ): Promise<void> => {
    if (filesToUpload.length === 0) return;

    setIsUploading(true);
    setUploadProgress({ completed: 0, total: filesToUpload.length, currentFile: "" });
    setError(null);

    try {
      // Get batch presigned URLs
      const batchRequest: BatchFileItem[] = filesToUpload.map(({ file, path }) => ({
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

          setUploadProgress((prev) =>
            prev ? { ...prev, currentFile: item.path } : null
          );

          await uploadSingleFile(item.file, presigned);

          completed++;
          setUploadProgress((prev) =>
            prev ? { ...prev, completed, currentFile: item.path } : null
          );
        }
      };

      // Run workers in parallel up to concurrency limit
      const workers = Array(Math.min(UPLOAD_CONCURRENCY, filesToUpload.length))
        .fill(null)
        .map(() => uploadWorker());

      await Promise.all(workers);

      // Refresh file list after all uploads complete
      await fetchFiles();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to upload files";
      setError(errorMessage);
      console.error("Batch upload error:", err);
    } finally {
      setIsUploading(false);
      setUploadProgress(null);
    }
  };

  const uploadFile = async (file: File) => {
    setIsUploading(true);
    setError(null);
    try {
      // Get presigned upload URL
      const presigned = await apiClient.post<PresignedUploadResponse>("/files/presign", {
        filename: file.name,
        content_type: file.type || undefined,
      });

      // Upload directly to S3
      const formData = new FormData();
      Object.entries(presigned.fields).forEach(([key, value]) => {
        formData.append(key, value);
      });
      formData.append("file", file);

      const uploadResponse = await fetch(presigned.url, {
        method: "POST",
        body: formData,
      });

      if (!uploadResponse.ok) {
        // Try to get more details from the response
        let errorDetail = uploadResponse.statusText;
        try {
          const errorText = await uploadResponse.text();
          if (errorText) {
            errorDetail = errorText;
          }
        } catch {
          // Ignore error reading response
        }
        throw new Error(`Upload failed: ${errorDetail}`);
      }

      // Refresh file list
      await fetchFiles();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to upload file";
      setError(errorMessage);
      console.error("Upload error:", err);
    } finally {
      setIsUploading(false);
    }
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.target.files;
    if (selectedFiles && selectedFiles.length > 0) {
      Array.from(selectedFiles).forEach(uploadFile);
    }
    // Reset input so same file can be selected again
    event.target.value = "";
  };

  /**
   * Handle folder selection via webkitdirectory input
   */
  const handleFolderSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.target.files;
    if (!selectedFiles || selectedFiles.length === 0) {
      event.target.value = "";
      return;
    }

    // Use webkitRelativePath to preserve folder structure
    const filesToUpload: { file: File; path: string }[] = [];
    const folderPaths = new Set<string>();

    Array.from(selectedFiles).forEach((file) => {
      // webkitRelativePath contains the folder path like "folder/subfolder/file.txt"
      const relativePath = file.webkitRelativePath || file.name;
      filesToUpload.push({ file, path: relativePath });

      // Track folder paths
      const pathParts = relativePath.split("/");
      for (let i = 1; i < pathParts.length; i++) {
        folderPaths.add(pathParts.slice(0, i).join("/"));
      }
    });

    // Note: webkitdirectory only returns files, empty folders are not included
    // We'll detect and display them by tracking all folder paths

    await uploadFilesWithProgress(filesToUpload);

    // Reset input so same folder can be selected again
    event.target.value = "";
  };

  /**
   * Read all entries from a directory reader (handles batching)
   */
  const readAllEntries = async (
    reader: FileSystemDirectoryReader
  ): Promise<FileSystemEntry[]> => {
    const entries: FileSystemEntry[] = [];
    
    const readBatch = (): Promise<FileSystemEntry[]> => {
      return new Promise((resolve, reject) => {
        reader.readEntries(
          (batch) => resolve(batch),
          (error) => reject(error)
        );
      });
    };

    // readEntries returns batches, keep reading until empty
    let batch = await readBatch();
    while (batch.length > 0) {
      entries.push(...batch);
      batch = await readBatch();
    }

    return entries;
  };

  /**
   * Recursively traverse a file system entry (file or directory)
   */
  const traverseEntry = async (
    entry: FileSystemEntry,
    basePath: string,
    files: { file: File; path: string }[],
    emptyFolderPaths: string[]
  ): Promise<void> => {
    const currentPath = basePath ? `${basePath}/${entry.name}` : entry.name;

    if (entry.isFile) {
      const fileEntry = entry as FileSystemFileEntry;
      const file = await new Promise<File>((resolve, reject) => {
        fileEntry.file(resolve, reject);
      });
      files.push({ file, path: currentPath });
    } else if (entry.isDirectory) {
      const dirEntry = entry as FileSystemDirectoryEntry;
      const reader = dirEntry.createReader();
      const entries = await readAllEntries(reader);

      if (entries.length === 0) {
        // Track empty folders
        emptyFolderPaths.push(currentPath);
      } else {
        for (const childEntry of entries) {
          await traverseEntry(childEntry, currentPath, files, emptyFolderPaths);
        }
      }
    }
  };

  const handleDrop = async (event: React.DragEvent) => {
    event.preventDefault();
    setDragOver(false);

    const items = event.dataTransfer.items;
    if (!items || items.length === 0) return;

    const filesToUpload: { file: File; path: string }[] = [];
    const emptyFolderPaths: string[] = [];
    const traversePromises: Promise<void>[] = [];

    // Use webkitGetAsEntry to handle both files and folders
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind === "file") {
        const entry = item.webkitGetAsEntry();
        if (entry) {
          traversePromises.push(
            traverseEntry(entry, "", filesToUpload, emptyFolderPaths)
          );
        }
      }
    }

    try {
      await Promise.all(traversePromises);

      // Store empty folders for display
      if (emptyFolderPaths.length > 0) {
        setEmptyFolders((prev) => [
          ...prev,
          ...emptyFolderPaths.map((path) => ({ path })),
        ]);
      }

      // Upload all collected files
      if (filesToUpload.length > 0) {
        await uploadFilesWithProgress(filesToUpload);
      } else if (emptyFolderPaths.length > 0) {
        // Only empty folders were dropped
        setError("Only empty folders were dropped. No files to upload.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process dropped items");
    }
  };

  const handleNativeDragOver = (event: React.DragEvent) => {
    event.preventDefault();
    setDragOver(true);
  };

  const handleNativeDragLeave = () => {
    setDragOver(false);
  };

  const downloadFile = async (fileKey: string) => {
    try {
      const response = await apiClient.get<PresignedDownloadResponse>(
        `/files/${encodeURIComponent(fileKey)}/download`
      );
      // Open download URL in new tab
      window.open(response.url, "_blank");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download file");
    }
  };

  const deleteFile = async (fileKey: string) => {
    if (!confirm(`Delete "${fileKey}"?`)) return;
    
    try {
      await apiClient.delete(`/files/${encodeURIComponent(fileKey)}`);
      await fetchFiles();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete file");
    }
  };

  const deleteFolder = async (folderPath: string) => {
    if (!confirm(`Delete folder "${folderPath}" and all its contents?`)) return;
    
    try {
      await apiClient.delete(`/files/folder/${encodeURIComponent(folderPath)}`);
      await fetchFiles();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete folder");
    }
  };

  const loadFilePreview = async (fileKey: string) => {
    setIsLoadingPreview(true);
    setError(null);
    try {
      const ext = fileKey.split(".").pop()?.toLowerCase() || "";
      const imageExtensions = ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"];
      const textExtensions = [
        "txt", "md", "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml",
        "xml", "html", "css", "csv", "log", "sh", "bash", "env", "toml",
        "ini", "cfg", "rst", "sql", "r", "rb", "go", "java", "c", "cpp",
        "h", "hpp", "rs", "swift", "kt", "scala", "php", "pl", "lua",
      ];
      
      // Get presigned URL for direct S3 access (fast!)
      const downloadResponse = await apiClient.get<PresignedDownloadResponse>(
        `/files/${fileKey}/download`
      );
      const fileInfo = files.find(f => f.key === fileKey);
      
      if (imageExtensions.includes(ext)) {
        // Images: use presigned URL directly in img src
        const mimeMap: Record<string, string> = {
          png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg",
          gif: "image/gif", webp: "image/webp", svg: "image/svg+xml",
          bmp: "image/bmp", ico: "image/x-icon",
        };
        setPreviewFile({
          key: fileKey,
          content_type: mimeMap[ext] || "image/png",
          size: fileInfo?.size || 0,
          presigned_url: downloadResponse.url,
          is_binary: true,
          is_truncated: false,
        });
      } else if (textExtensions.includes(ext)) {
        // Text files: fetch content from presigned URL and display in pre tag
        const textResponse = await fetch(downloadResponse.url);
        if (!textResponse.ok) {
          throw new Error("Failed to fetch file content");
        }
        const textContent = await textResponse.text();
        const maxSize = 200 * 1024 * 1024; // 200MB
        const is_truncated = textContent.length > maxSize;
        
        setPreviewFile({
          key: fileKey,
          content_type: "text/plain",
          size: fileInfo?.size || textContent.length,
          content: is_truncated ? textContent.slice(0, maxSize) : textContent,
          is_binary: false,
          is_truncated,
        });
      } else {
        // Binary files: show info only
        setPreviewFile({
          key: fileKey,
          content_type: fileInfo?.content_type || "application/octet-stream",
          size: fileInfo?.size || 0,
          is_binary: true,
          is_truncated: false,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load file preview");
    } finally {
      setIsLoadingPreview(false);
    }
  };

  const trigger = children || (
    <Button variant="ghost" size="icon" title="File Storage">
      <FolderOpen className="h-5 w-5" />
    </Button>
  );

  return (
    <>
      <div onClick={handleOpen} className="cursor-pointer">
        {trigger}
      </div>

      <Sheet open={isOpen} onOpenChange={setIsOpen}>
        <SheetContent side="right" className="w-96">
          <SheetHeader>
            <SheetTitle>File Storage</SheetTitle>
            <SheetClose onClick={() => setIsOpen(false)} />
          </SheetHeader>

          <div className="flex flex-col h-full overflow-hidden">
            {/* Upload Zone */}
            <div
              className={`m-4 p-4 border-2 border-dashed rounded-lg text-center transition-colors ${
                dragOver
                  ? "border-primary bg-primary/10"
                  : "border-muted-foreground/25 hover:border-muted-foreground/50"
              }`}
              onDrop={handleDrop}
              onDragOver={handleNativeDragOver}
              onDragLeave={handleNativeDragLeave}
            >
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileSelect}
                multiple
                className="hidden"
              />
              <input
                type="file"
                ref={folderInputRef}
                onChange={handleFolderSelect}
                // @ts-expect-error - webkitdirectory is a non-standard attribute
                webkitdirectory=""
                directory=""
                multiple
                className="hidden"
              />
              {isUploading && uploadProgress ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-center gap-2 text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span>
                      Uploading {uploadProgress.completed} of {uploadProgress.total} files...
                    </span>
                  </div>
                  <Progress 
                    value={(uploadProgress.completed / uploadProgress.total) * 100} 
                    className="h-2"
                  />
                  <p className="text-xs text-muted-foreground truncate max-w-full">
                    {uploadProgress.currentFile}
                  </p>
                </div>
              ) : isUploading ? (
                <div className="flex items-center justify-center gap-2 text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  <span>Uploading...</span>
                </div>
              ) : (
                <>
                  <Upload className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground mb-2">
                    Drag & drop files or folders here
                  </p>
                  <div className="flex gap-2 justify-center">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <File className="h-4 w-4 mr-1" />
                      Files
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => folderInputRef.current?.click()}
                    >
                      <FolderUp className="h-4 w-4 mr-1" />
                      Folder
                    </Button>
                  </div>
                </>
              )}
            </div>

            {/* Error Message */}
            {error && (
              <div className="mx-4 mb-4 p-3 bg-destructive/10 border border-destructive/20 rounded-lg flex items-start gap-2 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* File List Header */}
            <div className="flex items-center justify-between px-4 pb-2">
              <span className="text-sm font-medium">
                {files.length} file{files.length !== 1 ? "s" : ""}
                {emptyFolders.length > 0 && `, ${emptyFolders.length} empty folder${emptyFolders.length !== 1 ? "s" : ""}`}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setShowNewFolderInput(true)}
                  disabled={isCreatingFolder}
                  title="New Folder"
                >
                  <FolderPlus className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={fetchFiles}
                  disabled={isLoading}
                  title="Refresh"
                >
                  <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
                </Button>
              </div>
            </div>

            {/* New Folder Input */}
            {showNewFolderInput && (
              <div className="mx-4 mb-2 flex gap-2">
                <Input
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  placeholder="Folder name"
                  disabled={isCreatingFolder}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      createFolder(newFolderName);
                    } else if (e.key === "Escape") {
                      setShowNewFolderInput(false);
                      setNewFolderName("");
                    }
                  }}
                  autoFocus
                />
                <Button
                  size="sm"
                  onClick={() => createFolder(newFolderName)}
                  disabled={isCreatingFolder || !newFolderName.trim()}
                >
                  {isCreatingFolder ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    "Create"
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setShowNewFolderInput(false);
                    setNewFolderName("");
                  }}
                  disabled={isCreatingFolder}
                >
                  Cancel
                </Button>
              </div>
            )}

            {/* File List */}
            <div className="flex-1 overflow-y-auto px-4 pb-4">
              {isLoading && files.length === 0 ? (
                <div className="flex items-center justify-center py-8 text-muted-foreground">
                  <Loader2 className="h-6 w-6 animate-spin" />
                </div>
              ) : files.length === 0 && emptyFolders.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <File className="h-12 w-12 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">No files yet</p>
                  <p className="text-xs">Upload files to get started</p>
                </div>
              ) : (
                <DndContextComponent
                  sensors={sensors}
                  onDragStart={handleDragStart}
                  onDragOver={handleDragOver}
                  onDragEnd={handleDragEnd}
                  onDragCancel={handleDragCancel}
                >
                  <div className="space-y-1">
                    {/* Root folder drop target */}
                    <RootDropTarget 
                      isValidTarget={draggedItem ? isValidDropTarget("", true) : false}
                      isOver={overFolderId === ""}
                    />
                    <FileTreeView
                      node={fileTree}
                      depth={0}
                      collapsedFolders={collapsedFolders}
                      onToggleFolder={toggleFolder}
                      onDownload={downloadFile}
                      onDelete={deleteFile}
                      onDeleteFolder={deleteFolder}
                      onPreview={loadFilePreview}
                      onRemoveEmptyFolder={(path) =>
                        setEmptyFolders((prev) => prev.filter((f) => f.path !== path))
                      }
                      emptyFolderPaths={new Set(emptyFolders.map((f) => f.path))}
                      draggedItemId={draggedItem?.id}
                      overFolderId={overFolderId}
                      isValidDropTarget={isValidDropTarget}
                    />
                  </div>
                  <DragOverlayComponent>
                    {draggedItem && (
                      <div className="flex items-center gap-2 px-3 py-2 bg-background border rounded-md shadow-lg">
                        {draggedItem.isFolder ? (
                          <Folder className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <File className="h-4 w-4 text-muted-foreground" />
                        )}
                        <span className="text-sm">{draggedItem.name}</span>
                      </div>
                    )}
                  </DragOverlayComponent>
                </DndContextComponent>
              )}
              {isMoving && (
                <div className="absolute inset-0 bg-background/50 flex items-center justify-center">
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span>Moving...</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </SheetContent>
      </Sheet>

      {/* File Preview Dialog */}
      <Dialog open={previewFile !== null || isLoadingPreview} onOpenChange={(open) => !open && setPreviewFile(null)}>
        <DialogContent className="md:max-w-3xl lg:max-w-4xl">
          <DialogHeader>
            <DialogTitle>{previewFile?.key || "Loading..."}</DialogTitle>
            <DialogClose onClick={() => setPreviewFile(null)} />
          </DialogHeader>
          <DialogBody>
            {(() => {
              if (isLoadingPreview) {
                return (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                  </div>
                );
              }
              
              // Image with presigned URL - fast direct loading from S3
              if (previewFile?.presigned_url) {
                return (
                  <div className="flex flex-col items-center">
                    <img 
                      src={previewFile.presigned_url}
                      alt={previewFile.key}
                      className="max-w-full max-h-[60vh] object-contain rounded"
                    />
                    <p className="text-xs text-muted-foreground mt-2">Size: {formatFileSize(previewFile.size)}</p>
                  </div>
                );
              }
              
              // Text content
              if (previewFile && !previewFile.is_binary && previewFile.content) {
                const isMarkdown = previewFile.key.toLowerCase().endsWith(".md");
                return (
                  <>
                    {previewFile.is_truncated && (
                      <div className="mb-2 text-sm text-amber-500 bg-amber-500/10 p-2 rounded">
                        ⚠️ File truncated (showing first 200MB of {formatFileSize(previewFile.size)})
                      </div>
                    )}
                    {isMarkdown ? (
                      <div className="prose prose-sm dark:prose-invert max-w-none overflow-auto max-h-[60vh] p-4 bg-muted/30 rounded-md">
                        <MarkdownContent content={previewFile.content} />
                      </div>
                    ) : (
                      <pre className="text-sm whitespace-pre-wrap break-all font-mono bg-muted p-4 rounded-md overflow-auto max-h-[60vh]">
                        {previewFile.content}
                      </pre>
                    )}
                  </>
                );
              }
              
              // Binary file (non-image)
              if (previewFile?.is_binary) {
                return (
                  <div className="text-center text-muted-foreground py-8">
                    <File className="h-12 w-12 mx-auto mb-2 opacity-50" />
                    <p>Binary file - cannot display preview</p>
                    <p className="text-xs mt-1">Size: {formatFileSize(previewFile.size)}</p>
                  </div>
                );
              }
              
              return null;
            })()}
          </DialogBody>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface FileTreeViewProps {
  node: FileTreeNode;
  depth: number;
  collapsedFolders: Set<string>;
  onToggleFolder: (path: string) => void;
  onDownload: (key: string) => void;
  onDelete: (key: string) => void;
  onDeleteFolder: (path: string) => void;
  onPreview: (key: string) => void;
  onRemoveEmptyFolder: (path: string) => void;
  emptyFolderPaths: Set<string>;
  draggedItemId?: string | null;
  overFolderId?: string | null;
  isValidDropTarget?: (path: string, isFolder: boolean) => boolean;
}

/**
 * Root drop target for moving items to root level
 */
function RootDropTarget({ isValidTarget, isOver }: { isValidTarget: boolean; isOver: boolean }) {
  const { setNodeRef, isOver: localIsOver } = useDroppable({
    id: "",
    data: { isFolder: true, path: "" },
  });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "py-1.5 px-2 rounded-md border-2 border-dashed text-xs text-muted-foreground text-center transition-colors mb-1",
        (isOver || localIsOver) && isValidTarget
          ? "border-primary bg-primary/10"
          : "border-transparent"
      )}
    >
      {(isOver || localIsOver) && isValidTarget && "Drop here to move to root"}
    </div>
  );
}

/**
 * Draggable wrapper for file/folder items
 * Uses render prop pattern to pass drag handle props to children
 */
function DraggableItem({ 
  id, 
  name, 
  isFolder, 
  children 
}: { 
  id: string; 
  name: string; 
  isFolder: boolean; 
  children: (dragHandleProps: React.HTMLAttributes<HTMLElement>) => React.ReactNode;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id,
    data: { name, isFolder },
  });

  return (
    <div
      ref={setNodeRef}
      className={cn(isDragging && "opacity-50")}
    >
      {children({ ...attributes, ...listeners })}
    </div>
  );
}

/**
 * Droppable wrapper for folder items
 */
function DroppableFolder({
  id,
  isValidTarget,
  isOver,
  children,
}: {
  id: string;
  isValidTarget: boolean;
  isOver: boolean;
  children: React.ReactNode;
}) {
  const { setNodeRef, isOver: localIsOver } = useDroppable({
    id,
    data: { isFolder: true, path: id },
  });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "rounded-md transition-colors",
        (isOver || localIsOver) && isValidTarget && "ring-2 ring-primary ring-offset-1 bg-primary/5"
      )}
    >
      {children}
    </div>
  );
}

function FileTreeView({
  node,
  depth,
  collapsedFolders,
  onToggleFolder,
  onDownload,
  onDelete,
  onDeleteFolder,
  onPreview,
  onRemoveEmptyFolder,
  emptyFolderPaths,
  draggedItemId,
  overFolderId,
  isValidDropTarget,
}: FileTreeViewProps) {
  // Sort children: folders first, then files, alphabetically
  const sortedChildren = Array.from(node.children.values()).sort((a, b) => {
    if (a.isFolder && !b.isFolder) return -1;
    if (!a.isFolder && b.isFolder) return 1;
    return a.name.localeCompare(b.name);
  });

  // For root node, just render children
  if (depth === 0) {
    return (
      <>
        {sortedChildren.map((child) => (
          <FileTreeView
            key={child.path}
            node={child}
            depth={1}
            collapsedFolders={collapsedFolders}
            onToggleFolder={onToggleFolder}
            onDownload={onDownload}
            onDelete={onDelete}
            onDeleteFolder={onDeleteFolder}
            onPreview={onPreview}
            onRemoveEmptyFolder={onRemoveEmptyFolder}
            emptyFolderPaths={emptyFolderPaths}
            draggedItemId={draggedItemId}
            overFolderId={overFolderId}
            isValidDropTarget={isValidDropTarget}
          />
        ))}
      </>
    );
  }

  const isCollapsed = collapsedFolders.has(node.path);
  const isEmptyFolder = emptyFolderPaths.has(node.path);
  const hasChildren = node.children.size > 0;
  const paddingLeft = (depth - 1) * 16;
  const isDragging = draggedItemId === node.path;
  const isOverThis = overFolderId === node.path;
  const isValidTarget = isValidDropTarget?.(node.path, node.isFolder) ?? false;

  if (node.isFolder) {
    return (
      <DroppableFolder id={node.path} isValidTarget={isValidTarget} isOver={isOverThis}>
        <DraggableItem id={node.path} name={node.name} isFolder={true}>
          {(dragHandleProps) => (
            <div
              className={cn(
                "flex items-center gap-1 py-1.5 px-2 rounded-md hover:bg-accent/50 cursor-pointer transition-colors group",
                isEmptyFolder && "border border-dashed border-muted-foreground/30",
                isDragging && "opacity-50"
              )}
              style={{ paddingLeft }}
              onClick={() => hasChildren && onToggleFolder(node.path)}
            >
              <span {...dragHandleProps} onClick={(e) => e.stopPropagation()}>
                <GripVertical className="h-4 w-4 shrink-0 text-muted-foreground/50 cursor-grab" />
              </span>
              {hasChildren ? (
                isCollapsed ? (
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                )
              ) : (
                <span className="w-4" />
              )}
              <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="text-sm truncate flex-1" title={node.path}>
                {node.name}
              </span>
              {isEmptyFolder ? (
                <>
                  <span className="text-xs text-muted-foreground">(empty)</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-destructive hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemoveEmptyFolder(node.path);
                    }}
                    title="Remove from list"
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </>
              ) : (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-destructive hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteFolder(node.path);
                  }}
                  title="Delete folder"
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              )}
            </div>
          )}
        </DraggableItem>
        {!isCollapsed && hasChildren && (
          <div>
            {sortedChildren.map((child) => (
              <FileTreeView
                key={child.path}
                node={child}
                depth={depth + 1}
                collapsedFolders={collapsedFolders}
                onToggleFolder={onToggleFolder}
                onDownload={onDownload}
                onDelete={onDelete}
                onDeleteFolder={onDeleteFolder}
                onPreview={onPreview}
                onRemoveEmptyFolder={onRemoveEmptyFolder}
                emptyFolderPaths={emptyFolderPaths}
                draggedItemId={draggedItemId}
                overFolderId={overFolderId}
                isValidDropTarget={isValidDropTarget}
              />
            ))}
          </div>
        )}
      </DroppableFolder>
    );
  }

  // File node
  return (
    <DraggableItem id={node.path} name={node.name} isFolder={false}>
      {(dragHandleProps) => (
        <div
          className={cn(
            "flex items-center gap-1 py-1.5 px-2 rounded-md hover:bg-accent/50 transition-colors group",
            isDragging && "opacity-50"
          )}
          style={{ paddingLeft: paddingLeft + 20 }}
        >
          <span {...dragHandleProps}>
            <GripVertical className="h-4 w-4 shrink-0 text-muted-foreground/50 cursor-grab" />
          </span>
          <File className="h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="flex-1 min-w-0">
            <span className="text-sm truncate block" title={node.path}>
              {node.name}
            </span>
            {node.file && (
              <span className="text-xs text-muted-foreground">
                {formatFileSize(node.file.size)}
              </span>
            )}
          </div>
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => onPreview(node.path)}
              title="Preview"
            >
              <Eye className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => onDownload(node.path)}
              title="Download"
            >
              <Download className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-destructive hover:text-destructive"
              onClick={() => onDelete(node.path)}
              title="Delete"
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        </div>
      )}
    </DraggableItem>
  );
}
