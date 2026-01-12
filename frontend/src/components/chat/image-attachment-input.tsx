"use client";

import { useState, useRef, useCallback, type Dispatch, type SetStateAction } from "react";
import { Button } from "@/components/ui";
import { ImagePlus, X, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api-client";
import type { ChatAttachment, AllowedImageMimeType } from "@/types";
import { ALLOWED_IMAGE_MIME_TYPES, MAX_TOTAL_ATTACHMENT_SIZE_BYTES } from "@/types/chat";

interface PresignedUploadResponse {
  url: string;
  fields: Record<string, string>;
  key: string;
}

interface ImageAttachmentInputProps {
  attachments: ChatAttachment[];
  onAttachmentsChange: Dispatch<SetStateAction<ChatAttachment[]>>;
  disabled?: boolean;
}

/**
 * Validates if a file is an allowed image type.
 */
function isAllowedImageType(file: File): file is File & { type: AllowedImageMimeType } {
  return ALLOWED_IMAGE_MIME_TYPES.includes(file.type as AllowedImageMimeType);
}

/**
 * Formats file size in human-readable format.
 */
function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export function ImageAttachmentInput({
  attachments,
  onAttachmentsChange,
  disabled,
}: ImageAttachmentInputProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const totalSize = attachments.reduce((sum, a) => sum + a.sizeBytes, 0);
  const remainingSize = MAX_TOTAL_ATTACHMENT_SIZE_BYTES - totalSize;

  const uploadFile = useCallback(
    async (file: File) => {
      if (!isAllowedImageType(file)) {
        console.error(`Invalid file type: ${file.type}`);
        return;
      }

      if (file.size > remainingSize) {
        console.error(`File too large. Max remaining: ${formatFileSize(remainingSize)}`);
        return;
      }

      // Create preview URL
      const previewUrl = URL.createObjectURL(file);

      // Add pending attachment and get its index
      let attachmentIndex = -1;
      
      onAttachmentsChange((prev) => {
        attachmentIndex = prev.length;
        return [
          ...prev,
          {
            s3Key: "", // Will be set after upload
            mimeType: file.type as AllowedImageMimeType,
            sizeBytes: file.size,
            filename: file.name,
            previewUrl,
            status: "uploading",
          },
        ];
      });

      try {
        // Get presigned upload URL
        const presigned = await apiClient.post<PresignedUploadResponse>("/files", {
          filename: file.name,
          content_type: file.type,
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
          throw new Error(`Upload failed: ${uploadResponse.statusText}`);
        }

        // Update attachment with S3 key and mark as uploaded
        onAttachmentsChange((prev) => {
          const updated = [...prev];
          if (updated[attachmentIndex]) {
            updated[attachmentIndex] = {
              ...updated[attachmentIndex],
              s3Key: presigned.key,
              status: "uploaded",
            };
          }
          return updated;
        });
      } catch (error) {
        console.error("Upload failed:", error);
        // Mark as error
        onAttachmentsChange((prev) => {
          const updated = [...prev];
          if (updated[attachmentIndex]) {
            updated[attachmentIndex] = {
              ...updated[attachmentIndex],
              status: "error",
              errorMessage: error instanceof Error ? error.message : "Upload failed",
            };
          }
          return updated;
        });
      }
    },
    [onAttachmentsChange, remainingSize]
  );

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files) {
      Array.from(files).forEach(uploadFile);
    }
    // Reset input so same file can be selected again
    event.target.value = "";
  };

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setIsDragOver(false);
    const files = event.dataTransfer.files;
    if (files) {
      Array.from(files).forEach(uploadFile);
    }
  };

  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const removeAttachment = (index: number) => {
    const attachment = attachments[index];
    // Revoke preview URL to free memory
    if (attachment?.previewUrl) {
      URL.revokeObjectURL(attachment.previewUrl);
    }
    onAttachmentsChange(attachments.filter((_, i) => i !== index));
  };

  const acceptedTypes = ALLOWED_IMAGE_MIME_TYPES.join(",");

  return (
    <div
      className={`transition-colors ${isDragOver ? "bg-primary/5" : ""}`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      {/* Attachment Previews */}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {attachments.map((attachment, index) => (
            <div
              key={index}
              className="relative group rounded-lg overflow-hidden border border-border bg-muted"
            >
              {/* Preview Image */}
              {attachment.previewUrl && (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={attachment.previewUrl}
                  alt={attachment.filename || "Attachment"}
                  className="h-16 w-16 object-cover"
                />
              )}

              {/* Loading/Error Overlay */}
              {attachment.status === "uploading" && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                  <Loader2 className="h-5 w-5 animate-spin text-white" />
                </div>
              )}
              {attachment.status === "error" && (
                <div className="absolute inset-0 flex items-center justify-center bg-red-500/50">
                  <span className="text-xs text-white">Error</span>
                </div>
              )}

              {/* Remove Button */}
              <button
                type="button"
                onClick={() => removeAttachment(index)}
                className="absolute top-0.5 right-0.5 p-0.5 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                title="Remove"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add Image Button */}
      <input
        ref={fileInputRef}
        type="file"
        accept={acceptedTypes}
        multiple
        onChange={handleFileSelect}
        className="hidden"
        disabled={disabled}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={() => fileInputRef.current?.click()}
        disabled={disabled || remainingSize <= 0}
        title={
          remainingSize <= 0
            ? "Maximum attachment size reached"
            : `Attach image (${formatFileSize(remainingSize)} remaining)`
        }
        className="h-8 w-8"
      >
        <ImagePlus className="h-4 w-4" />
        <span className="sr-only">Attach image</span>
      </Button>
    </div>
  );
}
