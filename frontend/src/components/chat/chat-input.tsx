"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui";
import { Send, Loader2 } from "lucide-react";
import { ImageAttachmentInput } from "./image-attachment-input";
import type { ChatAttachment } from "@/types";

interface ChatInputProps {
  onSend: (message: string, attachments?: ChatAttachment[]) => void;
  disabled?: boolean;
  isProcessing?: boolean;
  supportsImages?: boolean;
}

export function ChatInput({ onSend, disabled, isProcessing, supportsImages = true }: ChatInputProps) {
  const [message, setMessage] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Check if there are any uploading attachments
  const hasUploadingAttachments = attachments.some((a) => a.status === "uploading");
  const hasReadyAttachments = attachments.some((a) => a.status === "uploaded");

  useEffect(() => {
    if (!isProcessing && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [isProcessing]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [message]);

  useEffect(() => {
    if (!supportsImages && attachments.length > 0) {
      attachments.forEach((a) => {
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      });
      setAttachments([]);
    }
  }, [supportsImages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const canSend = (message.trim() || hasReadyAttachments) && !disabled && !hasUploadingAttachments;
    if (canSend) {
      onSend(message.trim(), attachments.length > 0 ? attachments : undefined);
      setMessage("");
      // Clean up preview URLs and clear attachments
      attachments.forEach((a) => {
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      });
      setAttachments([]);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const canSubmit =
    (message.trim() || hasReadyAttachments) && !disabled && !hasUploadingAttachments;

  return (
    <form onSubmit={handleSubmit} className="relative">
      {/* Attachment Input */}
      <div className="flex items-end gap-2">
        {supportsImages && (
          <ImageAttachmentInput
            attachments={attachments}
            onAttachmentsChange={setAttachments}
            disabled={disabled}
          />
        )}

        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              attachments.length > 0
                ? "Add a message about the image(s)..."
                : "Type a message..."
            }
            disabled={disabled}
            rows={1}
            className="w-full resize-none bg-transparent pr-14 text-sm sm:text-base placeholder:text-muted-foreground focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
          <Button
            type="submit"
            size="icon"
            disabled={!canSubmit}
            className="absolute right-0 top-0 h-10 w-10 rounded-lg"
          >
            {isProcessing || hasUploadingAttachments ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Send className="h-5 w-5" />
            )}
            <span className="sr-only">Send message</span>
          </Button>
        </div>
      </div>
    </form>
  );
}
