"use client";

import { useState, useCallback, useRef } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { apiClient } from "@/lib/api-client";
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
  FolderUp
} from "lucide-react";

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

interface UploadProgress {
  completed: number;
  total: number;
  currentFile: string;
}

interface EmptyFolder {
  path: string;
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

export function FileBrowser({ children }: FileBrowserProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [emptyFolders, setEmptyFolders] = useState<EmptyFolder[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  // Concurrency limit for uploads
  const UPLOAD_CONCURRENCY = 5;

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

  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => {
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
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
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
                <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* File List Header */}
            <div className="flex items-center justify-between px-4 pb-2">
              <span className="text-sm font-medium">
                {files.length} file{files.length !== 1 ? "s" : ""}
                {emptyFolders.length > 0 && `, ${emptyFolders.length} empty folder${emptyFolders.length !== 1 ? "s" : ""}`}
              </span>
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
                <div className="space-y-2">
                  {/* Empty folders */}
                  {emptyFolders.map((folder) => (
                    <div
                      key={`folder-${folder.path}`}
                      className="p-3 border rounded-lg bg-card/50 border-dashed"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0 flex items-center gap-2">
                          <Folder className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium truncate text-muted-foreground" title={folder.path}>
                              {folder.path}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              Empty folder
                            </p>
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive hover:text-destructive"
                          onClick={() => setEmptyFolders((prev) => prev.filter((f) => f.path !== folder.path))}
                          title="Remove from list"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                  {/* Files */}
                  {files.map((file) => (
                    <div
                      key={file.key}
                      className="p-3 border rounded-lg bg-card hover:bg-accent/50 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate" title={file.key}>
                            {file.key}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {formatFileSize(file.size)} • {formatDate(file.last_modified)}
                          </p>
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => downloadFile(file.key)}
                            title="Download"
                          >
                            <Download className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive hover:text-destructive"
                            onClick={() => deleteFile(file.key)}
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
