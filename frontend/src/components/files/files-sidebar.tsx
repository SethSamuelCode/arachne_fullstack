"use client";

import { useEffect, useCallback, useRef, useMemo, useState } from "react";
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from "react-resizable-panels";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import {
  useFilesStore,
  buildFileTree,
  formatFileSize,
  type FileTreeNode,
} from "@/stores/files-store";
import { apiClient } from "@/lib/api-client";
import { MarkdownContent } from "@/components/chat/markdown-content";
import {
  File,
  Folder,
  ChevronRight,
  ChevronDown,
  Trash2,
  Download,
  Eye,
  Plus,
  Upload,
  FolderUp,
  Loader2,
  AlertCircle,
  RefreshCw,
  Pencil,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Types for file preview
interface FilePreviewData {
  key: string;
  content_type: string | null;
  size: number;
  presigned_url?: string;
  content?: string;
  is_binary: boolean;
  is_truncated: boolean;
}

interface PresignedDownloadResponse {
  url: string;
  expires_in: number;
}

// File extension categories
const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"];
const TEXT_EXTENSIONS = [
  "txt", "md", "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml",
  "xml", "html", "css", "csv", "log", "sh", "bash", "env", "toml",
  "ini", "cfg", "rst", "sql", "r", "rb", "go", "java", "c", "cpp",
  "h", "hpp", "rs", "swift", "kt", "scala", "php", "pl", "lua",
];

export function FilesSidebar() {
  const {
    files,
    emptyFolders,
    selectedFile,
    expandedFolders,
    isLoading,
    isUploading,
    isRenaming,
    uploadProgress,
    renameProgress,
    error,
    fetchFiles,
    setSelectedFile,
    toggleFolder,
    uploadFiles,
    renameFile,
    renameFolder,
    deleteFile,
    deleteFolder,
    removeEmptyFolder,
    clearError,
  } = useFilesStore();

  const [previewData, setPreviewData] = useState<FilePreviewData | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  // Build file tree
  const fileTree = useMemo(
    () => buildFileTree(files, emptyFolders),
    [files, emptyFolders]
  );

  // Fetch files on mount
  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  // Load preview when selected file changes
  useEffect(() => {
    if (selectedFile) {
      loadFilePreview(selectedFile);
    } else {
      setPreviewData(null);
    }
  }, [selectedFile]);

  const loadFilePreview = async (fileKey: string) => {
    setIsLoadingPreview(true);
    try {
      const ext = fileKey.split(".").pop()?.toLowerCase() || "";
      const fileInfo = files.find((f) => f.key === fileKey);

      // Get presigned URL for direct S3 access
      const downloadResponse = await apiClient.get<PresignedDownloadResponse>(
        `/files/${fileKey}/download`
      );

      if (IMAGE_EXTENSIONS.includes(ext)) {
        // Images: use presigned URL directly
        const mimeMap: Record<string, string> = {
          png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg",
          gif: "image/gif", webp: "image/webp", svg: "image/svg+xml",
          bmp: "image/bmp", ico: "image/x-icon",
        };
        setPreviewData({
          key: fileKey,
          content_type: mimeMap[ext] || "image/png",
          size: fileInfo?.size || 0,
          presigned_url: downloadResponse.url,
          is_binary: true,
          is_truncated: false,
        });
      } else if (TEXT_EXTENSIONS.includes(ext)) {
        // Text files: fetch content
        const textResponse = await fetch(downloadResponse.url);
        if (!textResponse.ok) throw new Error("Failed to fetch file content");
        const textContent = await textResponse.text();
        const maxSize = 200 * 1024 * 1024; // 200MB
        const is_truncated = textContent.length > maxSize;

        setPreviewData({
          key: fileKey,
          content_type: "text/plain",
          size: fileInfo?.size || textContent.length,
          content: is_truncated ? textContent.slice(0, maxSize) : textContent,
          is_binary: false,
          is_truncated,
        });
      } else {
        // Binary files: show info only
        setPreviewData({
          key: fileKey,
          content_type: fileInfo?.content_type || "application/octet-stream",
          size: fileInfo?.size || 0,
          is_binary: true,
          is_truncated: false,
        });
      }
    } catch (err) {
      console.error("Failed to load preview:", err);
      setPreviewData(null);
    } finally {
      setIsLoadingPreview(false);
    }
  };

  // Handle file drop
  const handleDrop = useCallback(
    async (event: React.DragEvent) => {
      event.preventDefault();
      setDragOver(false);

      const items = event.dataTransfer.items;
      if (!items || items.length === 0) return;

      const filesToUpload: { file: File; path: string }[] = [];

      const traverseEntry = async (
        entry: FileSystemEntry,
        basePath: string
      ): Promise<void> => {
        const currentPath = basePath ? `${basePath}/${entry.name}` : entry.name;

        if (entry.isFile) {
          const fileEntry = entry as FileSystemFileEntry;
          const file = await new Promise<File>((resolve, reject) => {
            fileEntry.file(resolve, reject);
          });
          filesToUpload.push({ file, path: currentPath });
        } else if (entry.isDirectory) {
          const dirEntry = entry as FileSystemDirectoryEntry;
          const reader = dirEntry.createReader();
          const entries = await readAllEntries(reader);
          for (const childEntry of entries) {
            await traverseEntry(childEntry, currentPath);
          }
        }
      };

      const readAllEntries = async (
        reader: FileSystemDirectoryReader
      ): Promise<FileSystemEntry[]> => {
        const entries: FileSystemEntry[] = [];
        const readBatch = (): Promise<FileSystemEntry[]> =>
          new Promise((resolve, reject) => {
            reader.readEntries(resolve, reject);
          });

        let batch = await readBatch();
        while (batch.length > 0) {
          entries.push(...batch);
          batch = await readBatch();
        }
        return entries;
      };

      const traversePromises: Promise<void>[] = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === "file") {
          const entry = item.webkitGetAsEntry();
          if (entry) {
            traversePromises.push(traverseEntry(entry, ""));
          }
        }
      }

      await Promise.all(traversePromises);
      if (filesToUpload.length > 0) {
        await uploadFiles(filesToUpload);
      }
    },
    [uploadFiles]
  );

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.target.files;
    if (selectedFiles && selectedFiles.length > 0) {
      const filesToUpload = Array.from(selectedFiles).map((file) => ({
        file,
        path: file.name,
      }));
      uploadFiles(filesToUpload);
    }
    event.target.value = "";
  };

  const handleFolderSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.target.files;
    if (!selectedFiles || selectedFiles.length === 0) {
      event.target.value = "";
      return;
    }

    const filesToUpload = Array.from(selectedFiles).map((file) => ({
      file,
      path: file.webkitRelativePath || file.name,
    }));

    await uploadFiles(filesToUpload);
    event.target.value = "";
  };

  const handleDownload = async (key: string) => {
    try {
      const response = await apiClient.get<PresignedDownloadResponse>(
        `/files/${encodeURIComponent(key)}/download`
      );
      window.open(response.url, "_blank");
    } catch (err) {
      console.error("Download failed:", err);
    }
  };

  const handleDelete = async (key: string) => {
    if (!confirm(`Delete "${key}"?`)) return;
    await deleteFile(key);
  };

  const handleDeleteFolder = async (path: string) => {
    if (!confirm(`Delete folder "${path}" and all its contents?`)) return;
    await deleteFolder(path);
  };

  const emptyFolderPaths = useMemo(
    () => new Set(emptyFolders.map((f) => f.path)),
    [emptyFolders]
  );

  return (
    <div className="flex flex-col h-full">
      {/* Hidden file inputs */}
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

      {/* Error message */}
      {error && (
        <div className="mx-3 mb-2 p-2 bg-destructive/10 border border-destructive/20 rounded-lg flex items-start gap-2 text-xs text-destructive">
          <AlertCircle className="h-3 w-3 mt-0.5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={clearError} className="shrink-0">
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      {/* Upload progress overlay */}
      {isUploading && uploadProgress && (
        <div className="mx-3 mb-2 p-2 bg-primary/10 border border-primary/20 rounded-lg">
          <div className="flex items-center gap-2 text-xs mb-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>
              Uploading {uploadProgress.completed}/{uploadProgress.total}
            </span>
          </div>
          <Progress
            value={(uploadProgress.completed / uploadProgress.total) * 100}
            className="h-1"
          />
          <p className="text-xs text-muted-foreground truncate mt-1">
            {uploadProgress.currentFile}
          </p>
        </div>
      )}

      {/* Rename progress overlay */}
      {isRenaming && renameProgress && (
        <div className="mx-3 mb-2 p-2 bg-primary/10 border border-primary/20 rounded-lg">
          <div className="flex items-center gap-2 text-xs mb-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>
              Moving {renameProgress.completed}/{renameProgress.total}
            </span>
          </div>
          <Progress
            value={
              renameProgress.total > 0
                ? (renameProgress.completed / renameProgress.total) * 100
                : 0
            }
            className="h-1"
          />
          {renameProgress.currentFile && (
            <p className="text-xs text-muted-foreground truncate mt-1">
              {renameProgress.currentFile}
            </p>
          )}
        </div>
      )}

      {/* Resizable panels */}
      <PanelGroup
        orientation="horizontal"
        id="files-sidebar-panels"
        className="flex-1"
      >
        {/* File tree panel */}
        <Panel defaultSize={50} minSize={30}>
          <div
            className={cn(
              "h-full flex flex-col relative",
              dragOver && "bg-primary/5"
            )}
            onDrop={handleDrop}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2 border-b">
              <span className="text-xs font-medium">
                {files.length} file{files.length !== 1 ? "s" : ""}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => fetchFiles()}
                disabled={isLoading}
                title="Refresh"
              >
                <RefreshCw
                  className={cn("h-3 w-3", isLoading && "animate-spin")}
                />
              </Button>
            </div>

            {/* File tree */}
            <div className="flex-1 overflow-y-auto px-2 py-2">
              {isLoading && files.length === 0 ? (
                <div className="flex items-center justify-center py-8 text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : files.length === 0 && emptyFolders.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <File className="h-8 w-8 mx-auto mb-2 opacity-50" />
                  <p className="text-xs">No files yet</p>
                  <p className="text-xs mt-1">Drop files here</p>
                </div>
              ) : (
                <FileTreeView
                  node={fileTree}
                  depth={0}
                  expandedFolders={expandedFolders}
                  selectedFile={selectedFile}
                  onToggleFolder={toggleFolder}
                  onSelectFile={setSelectedFile}
                  onDownload={handleDownload}
                  onDelete={handleDelete}
                  onDeleteFolder={handleDeleteFolder}
                  onRenameFile={renameFile}
                  onRenameFolder={renameFolder}
                  onRemoveEmptyFolder={removeEmptyFolder}
                  emptyFolderPaths={emptyFolderPaths}
                  disabled={isRenaming}
                />
              )}
            </div>

            {/* Drag overlay */}
            {dragOver && (
              <div className="absolute inset-0 flex items-center justify-center bg-primary/10 border-2 border-dashed border-primary rounded-lg pointer-events-none">
                <div className="text-center">
                  <Upload className="h-8 w-8 mx-auto mb-2 text-primary" />
                  <p className="text-sm text-primary">Drop files here</p>
                </div>
              </div>
            )}

            {/* Floating action button */}
            <div className="absolute bottom-3 right-3 flex flex-col gap-2">
              <Button
                size="icon"
                className="h-10 w-10 rounded-full shadow-lg"
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                title="Upload files"
              >
                <Plus className="h-5 w-5" />
              </Button>
              <Button
                size="icon"
                variant="outline"
                className="h-8 w-8 rounded-full shadow-lg"
                onClick={() => folderInputRef.current?.click()}
                disabled={isUploading}
                title="Upload folder"
              >
                <FolderUp className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </Panel>

        {/* Resize handle */}
        <PanelResizeHandle className="w-1 bg-border hover:bg-primary/50 transition-colors" />

        {/* Preview panel */}
        <Panel defaultSize={50} minSize={20}>
          <div className="h-full flex flex-col">
            {/* Preview header */}
            <div className="flex items-center justify-between px-3 py-2 border-b min-h-[41px]">
              <span className="text-xs font-medium truncate">
                {selectedFile ? selectedFile.split("/").pop() : "Preview"}
              </span>
              {selectedFile && (
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => handleDownload(selectedFile)}
                    title="Download"
                  >
                    <Download className="h-3 w-3" />
                  </Button>
                </div>
              )}
            </div>

            {/* Preview content */}
            <div className="flex-1 overflow-auto p-3">
              <FilePreview
                data={previewData}
                isLoading={isLoadingPreview}
                selectedFile={selectedFile}
              />
            </div>
          </div>
        </Panel>
      </PanelGroup>
    </div>
  );
}

// File tree component
interface FileTreeViewProps {
  node: FileTreeNode;
  depth: number;
  expandedFolders: Set<string>;
  selectedFile: string | null;
  onToggleFolder: (path: string) => void;
  onSelectFile: (key: string | null) => void;
  onDownload: (key: string) => void;
  onDelete: (key: string) => void;
  onDeleteFolder: (path: string) => void;
  onRenameFile: (oldPath: string, newPath: string) => Promise<boolean>;
  onRenameFolder: (oldPath: string, newPath: string) => Promise<boolean>;
  onRemoveEmptyFolder: (path: string) => void;
  emptyFolderPaths: Set<string>;
  disabled?: boolean;
}

function FileTreeView({
  node,
  depth,
  expandedFolders,
  selectedFile,
  onToggleFolder,
  onSelectFile,
  onDownload,
  onDelete,
  onDeleteFolder,
  onRenameFile,
  onRenameFolder,
  onRemoveEmptyFolder,
  emptyFolderPaths,
  disabled,
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
            expandedFolders={expandedFolders}
            selectedFile={selectedFile}
            onToggleFolder={onToggleFolder}
            onSelectFile={onSelectFile}
            onDownload={onDownload}
            onDelete={onDelete}
            onDeleteFolder={onDeleteFolder}
            onRenameFile={onRenameFile}
            onRenameFolder={onRenameFolder}
            onRemoveEmptyFolder={onRemoveEmptyFolder}
            emptyFolderPaths={emptyFolderPaths}
            disabled={disabled}
          />
        ))}
      </>
    );
  }

  const isExpanded = expandedFolders.has(node.path);
  const isEmptyFolder = emptyFolderPaths.has(node.path);
  const hasChildren = node.children.size > 0;
  const paddingLeft = (depth - 1) * 12;

  if (node.isFolder) {
    return (
      <FolderItem
        node={node}
        depth={depth}
        isExpanded={isExpanded}
        isEmptyFolder={isEmptyFolder}
        hasChildren={hasChildren}
        paddingLeft={paddingLeft}
        onToggle={() => hasChildren && onToggleFolder(node.path)}
        onDelete={() => onDeleteFolder(node.path)}
        onRemoveEmpty={() => onRemoveEmptyFolder(node.path)}
        onRename={(newName) => {
          const pathParts = node.path.split("/");
          pathParts[pathParts.length - 1] = newName;
          const newPath = pathParts.join("/");
          return onRenameFolder(node.path, newPath);
        }}
        disabled={disabled}
      >
        {isExpanded &&
          hasChildren &&
          sortedChildren.map((child) => (
            <FileTreeView
              key={child.path}
              node={child}
              depth={depth + 1}
              expandedFolders={expandedFolders}
              selectedFile={selectedFile}
              onToggleFolder={onToggleFolder}
              onSelectFile={onSelectFile}
              onDownload={onDownload}
              onDelete={onDelete}
              onDeleteFolder={onDeleteFolder}
              onRenameFile={onRenameFile}
              onRenameFolder={onRenameFolder}
              onRemoveEmptyFolder={onRemoveEmptyFolder}
              emptyFolderPaths={emptyFolderPaths}
              disabled={disabled}
            />
          ))}
      </FolderItem>
    );
  }

  // File node
  return (
    <FileItem
      node={node}
      paddingLeft={paddingLeft}
      isSelected={selectedFile === node.path}
      onSelect={() => onSelectFile(node.path)}
      onDownload={() => onDownload(node.path)}
      onDelete={() => onDelete(node.path)}
      onRename={(newName) => {
        const pathParts = node.path.split("/");
        pathParts[pathParts.length - 1] = newName;
        const newPath = pathParts.join("/");
        return onRenameFile(node.path, newPath);
      }}
      disabled={disabled}
    />
  );
}

// Folder item with inline rename
interface FolderItemProps {
  node: FileTreeNode;
  depth: number;
  isExpanded: boolean;
  isEmptyFolder: boolean;
  hasChildren: boolean;
  paddingLeft: number;
  onToggle: () => void;
  onDelete: () => void;
  onRemoveEmpty: () => void;
  onRename: (newName: string) => Promise<boolean>;
  disabled?: boolean;
  children?: React.ReactNode;
}

function FolderItem({
  node,
  isExpanded,
  isEmptyFolder,
  hasChildren,
  paddingLeft,
  onToggle,
  onDelete,
  onRemoveEmpty,
  onRename,
  disabled,
  children,
}: FolderItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState(node.name);

  const handleRename = async () => {
    if (editName.trim() && editName !== node.name) {
      const success = await onRename(editName.trim());
      if (success) {
        setIsEditing(false);
      }
    } else {
      setIsEditing(false);
      setEditName(node.name);
    }
  };

  return (
    <div>
      <div
        className={cn(
          "flex items-center gap-1 py-1 px-1 rounded-md hover:bg-accent/50 cursor-pointer transition-colors group",
          isEmptyFolder && "border border-dashed border-muted-foreground/30",
          disabled && "opacity-50 pointer-events-none"
        )}
        style={{ paddingLeft }}
        onClick={onToggle}
      >
        {hasChildren ? (
          isExpanded ? (
            <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
          )
        ) : (
          <span className="w-3" />
        )}
        <Folder className="h-3 w-3 shrink-0 text-muted-foreground" />

        {isEditing ? (
          <Input
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            onBlur={handleRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleRename();
              if (e.key === "Escape") {
                setIsEditing(false);
                setEditName(node.name);
              }
            }}
            className="h-5 px-1 py-0 text-xs flex-1"
            autoFocus
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span className="text-xs truncate flex-1" title={node.path}>
            {node.name}
          </span>
        )}

        {isEmptyFolder ? (
          <>
            <span className="text-xs text-muted-foreground">(empty)</span>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 text-destructive hover:text-destructive opacity-0 group-hover:opacity-100"
              onClick={(e) => {
                e.stopPropagation();
                onRemoveEmpty();
              }}
              title="Remove from list"
            >
              <X className="h-3 w-3" />
            </Button>
          </>
        ) : (
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={(e) => {
                e.stopPropagation();
                setIsEditing(true);
              }}
              title="Rename"
            >
              <Pencil className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 text-destructive hover:text-destructive"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              title="Delete folder"
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

// File item with inline rename
interface FileItemProps {
  node: FileTreeNode;
  paddingLeft: number;
  isSelected: boolean;
  onSelect: () => void;
  onDownload: () => void;
  onDelete: () => void;
  onRename: (newName: string) => Promise<boolean>;
  disabled?: boolean;
}

function FileItem({
  node,
  paddingLeft,
  isSelected,
  onSelect,
  onDownload,
  onDelete,
  onRename,
  disabled,
}: FileItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState(node.name);

  const handleRename = async () => {
    if (editName.trim() && editName !== node.name) {
      const success = await onRename(editName.trim());
      if (success) {
        setIsEditing(false);
      }
    } else {
      setIsEditing(false);
      setEditName(node.name);
    }
  };

  return (
    <div
      className={cn(
        "flex items-center gap-1 py-1 px-1 rounded-md hover:bg-accent/50 transition-colors group cursor-pointer",
        isSelected && "bg-accent",
        disabled && "opacity-50 pointer-events-none"
      )}
      style={{ paddingLeft: paddingLeft + 15 }}
      onClick={onSelect}
    >
      <File className="h-3 w-3 shrink-0 text-muted-foreground" />

      {isEditing ? (
        <Input
          value={editName}
          onChange={(e) => setEditName(e.target.value)}
          onBlur={handleRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleRename();
            if (e.key === "Escape") {
              setIsEditing(false);
              setEditName(node.name);
            }
          }}
          className="h-5 px-1 py-0 text-xs flex-1"
          autoFocus
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <div className="flex-1 min-w-0">
          <span className="text-xs truncate block" title={node.path}>
            {node.name}
          </span>
          {node.file && (
            <span className="text-xs text-muted-foreground">
              {formatFileSize(node.file.size)}
            </span>
          )}
        </div>
      )}

      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5"
          onClick={(e) => {
            e.stopPropagation();
            setIsEditing(true);
          }}
          title="Rename"
        >
          <Pencil className="h-3 w-3" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5"
          onClick={(e) => {
            e.stopPropagation();
            onDownload();
          }}
          title="Download"
        >
          <Download className="h-3 w-3" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5 text-destructive hover:text-destructive"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          title="Delete"
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

// File preview component
interface FilePreviewProps {
  data: FilePreviewData | null;
  isLoading: boolean;
  selectedFile: string | null;
}

function FilePreview({ data, isLoading, selectedFile }: FilePreviewProps) {
  if (!selectedFile) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <div className="text-center">
          <Eye className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p className="text-xs">Select a file to preview</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <p className="text-xs">Failed to load preview</p>
      </div>
    );
  }

  // Image preview
  if (data.presigned_url) {
    return (
      <div className="flex flex-col items-center">
        <img
          src={data.presigned_url}
          alt={data.key}
          className="max-w-full max-h-[50vh] object-contain rounded"
        />
        <p className="text-xs text-muted-foreground mt-2">
          {formatFileSize(data.size)}
        </p>
      </div>
    );
  }

  // Text content
  if (!data.is_binary && data.content) {
    const isMarkdown = data.key.toLowerCase().endsWith(".md");
    return (
      <>
        {data.is_truncated && (
          <div className="mb-2 text-xs text-amber-500 bg-amber-500/10 p-2 rounded">
            ⚠️ File truncated (showing first 200MB)
          </div>
        )}
        {isMarkdown ? (
          <div className="prose prose-sm dark:prose-invert max-w-none overflow-auto text-xs">
            <MarkdownContent content={data.content} />
          </div>
        ) : (
          <pre className="text-xs whitespace-pre-wrap break-all font-mono bg-muted p-2 rounded-md overflow-auto">
            {data.content}
          </pre>
        )}
      </>
    );
  }

  // Binary file (non-image)
  return (
    <div className="h-full flex items-center justify-center text-muted-foreground">
      <div className="text-center">
        <File className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p className="text-xs">Binary file - cannot preview</p>
        <p className="text-xs mt-1">{formatFileSize(data.size)}</p>
      </div>
    </div>
  );
}
