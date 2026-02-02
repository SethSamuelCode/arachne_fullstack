"use client";

import { useEffect, useCallback, useRef, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogBody } from "@/components/ui/dialog";
import {
  useFilesStore,
  buildFileTree,
  formatFileSize,
  type FileTreeNode,
} from "@/stores/files-store";
import { usePinFiles } from "@/hooks/use-pin-files";
import { apiClient } from "@/lib/api-client";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { PinnedContentSummary } from "./pinned-content-summary";
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
  Loader2,
  AlertCircle,
  RefreshCw,
  Pencil,
  X,
  FolderUp,
  FolderPlus,
  Pin,
} from "lucide-react";
import { cn } from "@/lib/utils";

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"];
const TEXT_EXTENSIONS = [
  "txt", "md", "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml",
  "xml", "html", "css", "csv", "log", "sh", "bash", "env", "toml",
  "ini", "cfg", "rst", "sql", "r", "rb", "go", "java", "c", "cpp",
  "h", "hpp", "rs", "swift", "kt", "scala", "php", "pl", "lua",
];

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

interface PresignedUploadResponse {
  url: string;
  fields: Record<string, string>;
  key: string;
}

interface ChatFilesSidebarProps {
  conversationId: string | null;
  onConversationNeeded?: () => Promise<string | null>;
}

export function ChatFilesSidebar({ conversationId, onConversationNeeded }: ChatFilesSidebarProps) {
  const {
    files,
    emptyFolders,
    expandedFolders,
    isLoading,
    isUploading,
    uploadProgress,
    error,
    fetchFiles,
    toggleFolder,
    uploadFiles,
    deleteFile,
    deleteFolder,
    renameFile,
    renameFolder,
    clearError,
  } = useFilesStore();

  const {
    pinnedInfo,
    isPinning,
    pinFiles,
  } = usePinFiles({
    conversationId: conversationId || "",
    autoFetch: !!conversationId,
    autoCheckStaleness: false,
  });

  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [previewData, setPreviewData] = useState<FilePreviewData | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [showNewFolderInput, setShowNewFolderInput] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const pinnedFilePaths = useMemo(
    () => new Set(pinnedInfo?.file_paths ?? []),
    [pinnedInfo]
  );

  const fileTree = useMemo(
    () => buildFileTree(files, emptyFolders),
    [files, emptyFolders]
  );

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  const toggleSelection = useCallback((path: string) => {
    setSelectedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedFiles(new Set(files.map((f) => f.key)));
  }, [files]);

  const clearSelection = useCallback(() => {
    setSelectedFiles(new Set());
  }, []);

  const handlePinSelected = useCallback(async () => {
    const paths = Array.from(selectedFiles);
    if (paths.length === 0) return;

    let targetConversationId = conversationId;
    if (!targetConversationId && onConversationNeeded) {
      targetConversationId = await onConversationNeeded();
    }
    if (!targetConversationId) return;

    try {
      await pinFiles(paths);
      clearSelection();
    } catch (err) {
      console.error("Pin failed:", err);
    }
  }, [selectedFiles, conversationId, onConversationNeeded, pinFiles, clearSelection]);

  const loadFilePreview = useCallback(async (fileKey: string) => {
    setIsLoadingPreview(true);
    try {
      const ext = fileKey.split(".").pop()?.toLowerCase() || "";
      const fileInfo = files.find((f) => f.key === fileKey);
      const downloadResponse = await apiClient.get<PresignedDownloadResponse>(
        `/files/${fileKey}/download`
      );

      if (IMAGE_EXTENSIONS.includes(ext)) {
        const mimeMap: Record<string, string> = {
          png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg",
          gif: "image/gif", webp: "image/webp", svg: "image/svg+xml",
          bmp: "image/bmp", ico: "image/x-icon",
        };
        setPreviewData({
          key: fileKey, content_type: mimeMap[ext] || "image/png",
          size: fileInfo?.size || 0, presigned_url: downloadResponse.url,
          is_binary: true, is_truncated: false,
        });
      } else if (TEXT_EXTENSIONS.includes(ext)) {
        const textResponse = await fetch(downloadResponse.url);
        if (!textResponse.ok) throw new Error("Failed to fetch file content");
        const textContent = await textResponse.text();
        const maxSize = 200 * 1024;
        setPreviewData({
          key: fileKey, content_type: "text/plain",
          size: fileInfo?.size || textContent.length,
          content: textContent.length > maxSize ? textContent.slice(0, maxSize) : textContent,
          is_binary: false, is_truncated: textContent.length > maxSize,
        });
      } else {
        setPreviewData({
          key: fileKey, content_type: fileInfo?.content_type || "application/octet-stream",
          size: fileInfo?.size || 0, is_binary: true, is_truncated: false,
        });
      }
    } catch (err) {
      console.error("Failed to load preview:", err);
      setPreviewData(null);
    } finally {
      setIsLoadingPreview(false);
    }
  }, [files]);

  const handleDownload = useCallback(async (key: string) => {
    try {
      const response = await apiClient.get<PresignedDownloadResponse>(
        `/files/${encodeURIComponent(key)}/download`
      );
      window.open(response.url, "_blank");
    } catch (err) {
      console.error("Download failed:", err);
    }
  }, []);

  const handleDelete = useCallback(async (key: string) => {
    if (!confirm(`Delete "${key}"?`)) return;
    await deleteFile(key);
  }, [deleteFile]);

  const handleDeleteFolder = useCallback(async (path: string) => {
    if (!confirm(`Delete folder "${path}" and all its contents?`)) return;
    await deleteFolder(path);
  }, [deleteFolder]);

  const handleDrop = useCallback(async (event: React.DragEvent) => {
    event.preventDefault();
    setDragOver(false);

    const items = event.dataTransfer.items;
    if (!items || items.length === 0) return;

    const filesToUpload: { file: File; path: string }[] = [];

    const traverseEntry = async (entry: FileSystemEntry, basePath: string): Promise<void> => {
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
        const readBatch = (): Promise<FileSystemEntry[]> =>
          new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        let batch = await readBatch();
        while (batch.length > 0) {
          for (const child of batch) await traverseEntry(child, currentPath);
          batch = await readBatch();
        }
      }
    };

    const promises: Promise<void>[] = [];
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry();
      if (entry) promises.push(traverseEntry(entry, ""));
    }
    await Promise.all(promises);
    if (filesToUpload.length > 0) await uploadFiles(filesToUpload);
  }, [uploadFiles]);

  const handleFileSelect = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files;
    if (selected && selected.length > 0) {
      uploadFiles(Array.from(selected).map((file) => ({ file, path: file.name })));
    }
    event.target.value = "";
  }, [uploadFiles]);

  const handleFolderSelect = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files;
    if (!selected || selected.length === 0) { event.target.value = ""; return; }
    await uploadFiles(
      Array.from(selected).map((file) => ({ file, path: file.webkitRelativePath || file.name }))
    );
    event.target.value = "";
  }, [uploadFiles]);

  const handleCreateFolder = useCallback(async () => {
    if (!newFolderName.trim()) return;
    setIsCreatingFolder(true);
    try {
      const presigned = await apiClient.post<PresignedUploadResponse>("/files/presign", {
        filename: `${newFolderName.trim()}/.gitkeep`, content_type: "text/plain",
      });
      const formData = new FormData();
      Object.entries(presigned.fields).forEach(([k, v]) => formData.append(k, v));
      formData.append("file", new Blob([""], { type: "text/plain" }), ".gitkeep");
      const resp = await fetch(presigned.url, { method: "POST", body: formData });
      if (!resp.ok) throw new Error("Failed to create folder");
      await fetchFiles();
      setNewFolderName("");
      setShowNewFolderInput(false);
    } catch (err) {
      console.error("Failed to create folder:", err);
    } finally {
      setIsCreatingFolder(false);
    }
  }, [newFolderName, fetchFiles]);

  const emptyFolderPaths = useMemo(
    () => new Set(emptyFolders.map((f) => f.path)),
    [emptyFolders]
  );

  const selectedCount = selectedFiles.size;

  return (
    <div className="flex flex-col h-full">
      <input type="file" ref={fileInputRef} onChange={handleFileSelect} multiple className="hidden" />
      <input
        type="file" ref={folderInputRef} onChange={handleFolderSelect}
        // @ts-expect-error - webkitdirectory is non-standard
        webkitdirectory="" directory="" multiple className="hidden"
      />

      <PinnedContentSummary conversationId={conversationId} />

      {error && (
        <div className="mx-2 my-1 p-2 bg-destructive/10 border border-destructive/20 rounded flex items-start gap-2 text-xs text-destructive">
          <AlertCircle className="h-3 w-3 mt-0.5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={clearError}><X className="h-3 w-3" /></button>
        </div>
      )}

      {isUploading && uploadProgress && (
        <div className="mx-2 my-1 p-2 bg-primary/10 border border-primary/20 rounded">
          <div className="flex items-center gap-2 text-xs mb-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>Uploading {uploadProgress.completed}/{uploadProgress.total}</span>
          </div>
          <Progress value={(uploadProgress.completed / uploadProgress.total) * 100} className="h-1" />
        </div>
      )}

      <div className="flex items-center justify-between px-3 py-2 border-b">
        <span className="text-xs font-medium">
          {selectedCount > 0
            ? `${selectedCount} selected`
            : `${files.length} file${files.length !== 1 ? "s" : ""}`
          }
        </span>
        <div className="flex items-center gap-1">
          {selectedCount > 0 ? (
            <>
              <Button variant="ghost" size="sm" className="h-6 text-xs px-2" onClick={selectAll}>
                All
              </Button>
              <Button variant="ghost" size="sm" className="h-6 text-xs px-2" onClick={clearSelection}>
                Clear
              </Button>
            </>
          ) : (
            <Button
              variant="ghost" size="icon" className="h-6 w-6"
              onClick={() => fetchFiles()} disabled={isLoading} title="Refresh"
            >
              <RefreshCw className={cn("h-3 w-3", isLoading && "animate-spin")} />
            </Button>
          )}
        </div>
      </div>

      <div
        className={cn("flex-1 overflow-y-auto px-2 py-2 relative", dragOver && "bg-primary/5")}
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
      >
        {isLoading && files.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : files.length === 0 && emptyFolders.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Upload className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p className="text-xs">No files yet</p>
            <p className="text-xs mt-1">Drop files here or use the buttons below</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            <SidebarFileTree
              node={fileTree}
              depth={0}
              expandedFolders={expandedFolders}
              selectedFiles={selectedFiles}
              pinnedFiles={pinnedFilePaths}
              onToggleFolder={toggleFolder}
              onToggleSelection={toggleSelection}
              onPreview={loadFilePreview}
              onDownload={handleDownload}
              onDelete={handleDelete}
              onDeleteFolder={handleDeleteFolder}
              onRenameFile={renameFile}
              onRenameFolder={renameFolder}
              emptyFolderPaths={emptyFolderPaths}
              isPinning={isPinning}
            />
          </div>
        )}

        {dragOver && (
          <div className="absolute inset-0 flex items-center justify-center bg-primary/10 border-2 border-dashed border-primary rounded-lg pointer-events-none">
            <div className="text-center">
              <Upload className="h-8 w-8 mx-auto mb-2 text-primary" />
              <p className="text-sm text-primary">Drop files here</p>
            </div>
          </div>
        )}

        {showNewFolderInput && (
          <div className="absolute inset-0 bg-background/80 flex items-center justify-center z-10">
            <div className="bg-background border rounded-lg shadow-lg p-4 w-56">
              <h3 className="text-sm font-medium mb-2">New Folder</h3>
              <Input
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="Folder name" className="mb-3" autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreateFolder();
                  if (e.key === "Escape") { setShowNewFolderInput(false); setNewFolderName(""); }
                }}
              />
              <div className="flex gap-2 justify-end">
                <Button variant="ghost" size="sm"
                  onClick={() => { setShowNewFolderInput(false); setNewFolderName(""); }}>
                  Cancel
                </Button>
                <Button size="sm" onClick={handleCreateFolder}
                  disabled={!newFolderName.trim() || isCreatingFolder}>
                  {isCreatingFolder ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create"}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="border-t">
        {selectedCount > 0 && (
          <div className="flex items-center justify-between px-3 py-2 bg-primary/5">
            <span className="text-xs text-muted-foreground">
              {selectedCount} file{selectedCount !== 1 ? "s" : ""}
            </span>
            <Button
              size="sm" className="h-7 text-xs"
              onClick={handlePinSelected}
              disabled={isPinning}
            >
              {isPinning ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : (
                <Pin className="h-3 w-3 mr-1" />
              )}
              Pin Selected
            </Button>
          </div>
        )}

        <div className="flex items-center gap-1 px-3 py-2">
          <Button
            variant="outline" size="sm" className="h-7 text-xs flex-1"
            onClick={() => fileInputRef.current?.click()} disabled={isUploading}
          >
            <Plus className="h-3 w-3 mr-1" /> Upload
          </Button>
          <Button
            variant="outline" size="icon" className="h-7 w-7"
            onClick={() => folderInputRef.current?.click()} disabled={isUploading}
            title="Upload folder"
          >
            <FolderUp className="h-3 w-3" />
          </Button>
          <Button
            variant="outline" size="icon" className="h-7 w-7"
            onClick={() => setShowNewFolderInput(true)} disabled={isCreatingFolder}
            title="New folder"
          >
            <FolderPlus className="h-3 w-3" />
          </Button>
        </div>
      </div>

      <Dialog open={previewData !== null || isLoadingPreview} onOpenChange={(open) => !open && setPreviewData(null)}>
        <DialogContent className="max-w-md max-h-[500px]">
          <DialogHeader>
            <DialogTitle className="text-sm truncate">
              {previewData?.key?.split("/").pop() || "Loading..."}
            </DialogTitle>
          </DialogHeader>
          <DialogBody className="overflow-auto">
            <FilePreviewContent data={previewData} isLoading={isLoadingPreview} />
            {previewData && !isLoadingPreview && (
              <div className="flex justify-end gap-2 mt-3 pt-3 border-t">
                <Button variant="outline" size="sm" onClick={() => handleDownload(previewData.key)}>
                  <Download className="h-3 w-3 mr-1" /> Download
                </Button>
                <Button variant="outline" size="sm" onClick={() => setPreviewData(null)}>
                  Close
                </Button>
              </div>
            )}
          </DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ---------- File Tree Components ---------- */

interface SidebarFileTreeProps {
  node: FileTreeNode;
  depth: number;
  expandedFolders: Set<string>;
  selectedFiles: Set<string>;
  pinnedFiles: Set<string>;
  onToggleFolder: (path: string) => void;
  onToggleSelection: (path: string) => void;
  onPreview: (key: string) => void;
  onDownload: (key: string) => void;
  onDelete: (key: string) => void;
  onDeleteFolder: (path: string) => void;
  onRenameFile: (oldPath: string, newPath: string) => Promise<boolean>;
  onRenameFolder: (oldPath: string, newPath: string) => Promise<boolean>;
  emptyFolderPaths: Set<string>;
  isPinning: boolean;
}

function SidebarFileTree({
  node, depth, expandedFolders, selectedFiles, pinnedFiles,
  onToggleFolder, onToggleSelection, onPreview, onDownload,
  onDelete, onDeleteFolder, onRenameFile, onRenameFolder,
  emptyFolderPaths, isPinning,
}: SidebarFileTreeProps) {
  const sortedChildren = Array.from(node.children.values()).sort((a, b) => {
    if (a.isFolder && !b.isFolder) return -1;
    if (!a.isFolder && b.isFolder) return 1;
    return a.name.localeCompare(b.name);
  });

  if (depth === 0) {
    return (
      <>
        {sortedChildren.map((child) => (
          <SidebarFileTree
            key={child.path} node={child} depth={1}
            expandedFolders={expandedFolders} selectedFiles={selectedFiles}
            pinnedFiles={pinnedFiles} onToggleFolder={onToggleFolder}
            onToggleSelection={onToggleSelection} onPreview={onPreview}
            onDownload={onDownload} onDelete={onDelete}
            onDeleteFolder={onDeleteFolder} onRenameFile={onRenameFile}
            onRenameFolder={onRenameFolder} emptyFolderPaths={emptyFolderPaths}
            isPinning={isPinning}
          />
        ))}
      </>
    );
  }

  const isExpanded = expandedFolders.has(node.path);
  const hasChildren = node.children.size > 0;
  const paddingLeft = (depth - 1) * 12;

  if (node.isFolder) {
    return (
      <>
        <SidebarFolderItem
          node={node} paddingLeft={paddingLeft} isExpanded={isExpanded}
          hasChildren={hasChildren} isEmptyFolder={emptyFolderPaths.has(node.path)}
          onToggle={() => hasChildren && onToggleFolder(node.path)}
          onDelete={() => onDeleteFolder(node.path)}
          onRename={(newName) => {
            const parts = node.path.split("/");
            parts[parts.length - 1] = newName;
            return onRenameFolder(node.path, parts.join("/"));
          }}
        />
        {isExpanded && hasChildren && sortedChildren.map((child) => (
          <SidebarFileTree
            key={child.path} node={child} depth={depth + 1}
            expandedFolders={expandedFolders} selectedFiles={selectedFiles}
            pinnedFiles={pinnedFiles} onToggleFolder={onToggleFolder}
            onToggleSelection={onToggleSelection} onPreview={onPreview}
            onDownload={onDownload} onDelete={onDelete}
            onDeleteFolder={onDeleteFolder} onRenameFile={onRenameFile}
            onRenameFolder={onRenameFolder} emptyFolderPaths={emptyFolderPaths}
            isPinning={isPinning}
          />
        ))}
      </>
    );
  }

  const isPinned = pinnedFiles.has(node.path);
  const isSelected = selectedFiles.has(node.path);

  return (
    <SidebarFileItem
      node={node} paddingLeft={paddingLeft}
      isSelected={isSelected} isPinned={isPinned} isPinning={isPinning}
      onToggleSelection={() => onToggleSelection(node.path)}
      onPreview={() => onPreview(node.path)}
      onDownload={() => onDownload(node.path)}
      onDelete={() => onDelete(node.path)}
      onRename={(newName) => {
        const parts = node.path.split("/");
        parts[parts.length - 1] = newName;
        return onRenameFile(node.path, parts.join("/"));
      }}
    />
  );
}

/* ---------- Folder Item ---------- */

interface SidebarFolderItemProps {
  node: FileTreeNode;
  paddingLeft: number;
  isExpanded: boolean;
  hasChildren: boolean;
  isEmptyFolder: boolean;
  onToggle: () => void;
  onDelete: () => void;
  onRename: (newName: string) => Promise<boolean>;
}

function SidebarFolderItem({
  node, paddingLeft, isExpanded, hasChildren, isEmptyFolder,
  onToggle, onDelete, onRename,
}: SidebarFolderItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState(node.name);

  const handleRename = async () => {
    if (editName.trim() && editName !== node.name) {
      const success = await onRename(editName.trim());
      if (success) setIsEditing(false);
    } else {
      setIsEditing(false);
      setEditName(node.name);
    }
  };

  return (
    <div
      className={cn(
        "flex items-center gap-1 py-1 px-1 rounded-md hover:bg-accent/50 cursor-pointer transition-colors group",
        isEmptyFolder && "border border-dashed border-muted-foreground/30"
      )}
      style={{ paddingLeft }}
      onClick={onToggle}
    >
      {hasChildren ? (
        isExpanded ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
      ) : <span className="w-3" />}
      <Folder className="h-3 w-3 shrink-0 text-muted-foreground" />
      {isEditing ? (
        <Input
          value={editName} onChange={(e) => setEditName(e.target.value)}
          onBlur={handleRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleRename();
            if (e.key === "Escape") { setIsEditing(false); setEditName(node.name); }
          }}
          className="h-5 px-1 py-0 text-xs flex-1" autoFocus
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <span className="text-xs truncate flex-1" title={node.path}>{node.name}</span>
      )}
      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
        <Button variant="ghost" size="icon" className="h-5 w-5"
          onClick={(e) => { e.stopPropagation(); setIsEditing(true); }} title="Rename">
          <Pencil className="h-3 w-3" />
        </Button>
        <Button variant="ghost" size="icon" className="h-5 w-5 text-destructive hover:text-destructive"
          onClick={(e) => { e.stopPropagation(); onDelete(); }} title="Delete folder">
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

/* ---------- File Item ---------- */

interface SidebarFileItemProps {
  node: FileTreeNode;
  paddingLeft: number;
  isSelected: boolean;
  isPinned: boolean;
  isPinning: boolean;
  onToggleSelection: () => void;
  onPreview: () => void;
  onDownload: () => void;
  onDelete: () => void;
  onRename: (newName: string) => Promise<boolean>;
}

function SidebarFileItem({
  node, paddingLeft, isSelected, isPinned, isPinning,
  onToggleSelection, onPreview, onDownload, onDelete, onRename,
}: SidebarFileItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState(node.name);

  const handleRename = async () => {
    if (editName.trim() && editName !== node.name) {
      const success = await onRename(editName.trim());
      if (success) setIsEditing(false);
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
        isPinned && "bg-primary/5",
        isPinned && isPinning && "animate-pulse"
      )}
      style={{ paddingLeft: paddingLeft + 12 }}
      onClick={onToggleSelection}
    >
      <Checkbox
        checked={isSelected}
        onCheckedChange={() => onToggleSelection()}
        onClick={(e) => e.stopPropagation()}
        className="h-3.5 w-3.5"
      />
      <div className="relative">
        <File className="h-3 w-3 shrink-0 text-muted-foreground" />
        {isPinned && (
          <Pin className="h-2 w-2 absolute -top-1 -right-1 text-primary" />
        )}
      </div>
      {isEditing ? (
        <Input
          value={editName} onChange={(e) => setEditName(e.target.value)}
          onBlur={handleRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleRename();
            if (e.key === "Escape") { setIsEditing(false); setEditName(node.name); }
          }}
          className="h-5 px-1 py-0 text-xs flex-1" autoFocus
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <div className="flex-1 min-w-0">
          <span className="text-xs truncate block" title={node.path}>{node.name}</span>
          {node.file && (
            <span className="text-[10px] text-muted-foreground">
              {formatFileSize(node.file.size)}
            </span>
          )}
        </div>
      )}
      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
        <Button variant="ghost" size="icon" className="h-5 w-5"
          onClick={(e) => { e.stopPropagation(); onPreview(); }} title="Preview">
          <Eye className="h-3 w-3" />
        </Button>
        <Button variant="ghost" size="icon" className="h-5 w-5"
          onClick={(e) => { e.stopPropagation(); onDownload(); }} title="Download">
          <Download className="h-3 w-3" />
        </Button>
        <Button variant="ghost" size="icon" className="h-5 w-5"
          onClick={(e) => { e.stopPropagation(); setIsEditing(true); }} title="Rename">
          <Pencil className="h-3 w-3" />
        </Button>
        <Button variant="ghost" size="icon" className="h-5 w-5 text-destructive hover:text-destructive"
          onClick={(e) => { e.stopPropagation(); onDelete(); }} title="Delete">
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

/* ---------- File Preview Content ---------- */

function FilePreviewContent({ data, isLoading }: { data: FilePreviewData | null; isLoading: boolean }) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!data) return null;

  if (data.presigned_url) {
    return (
      <div className="flex flex-col items-center">
        <img src={data.presigned_url} alt={data.key} className="max-w-full max-h-[300px] object-contain rounded" />
        <p className="text-xs text-muted-foreground mt-2">{formatFileSize(data.size)}</p>
      </div>
    );
  }

  if (!data.is_binary && data.content) {
    const isMarkdown = data.key.toLowerCase().endsWith(".md");
    return (
      <>
        {data.is_truncated && (
          <div className="mb-2 text-xs text-amber-500 bg-amber-500/10 p-2 rounded">
            File truncated (showing first 200KB)
          </div>
        )}
        {isMarkdown ? (
          <div className="prose prose-sm dark:prose-invert max-w-none overflow-auto text-xs">
            <MarkdownContent content={data.content} />
          </div>
        ) : (
          <pre className="text-xs whitespace-pre-wrap break-all font-mono bg-muted p-2 rounded-md overflow-auto max-h-[300px]">
            {data.content}
          </pre>
        )}
      </>
    );
  }

  return (
    <div className="text-center text-muted-foreground py-8">
      <File className="h-8 w-8 mx-auto mb-2 opacity-50" />
      <p className="text-xs">Binary file - cannot preview</p>
      <p className="text-xs mt-1">{formatFileSize(data.size)}</p>
    </div>
  );
}
