"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types";
import { ToolCallCard } from "./tool-call-card";
import { MarkdownContent } from "./markdown-content";
import { CopyButton } from "./copy-button";
import { User, Bot, X } from "lucide-react";

interface MessageItemProps {
  message: ChatMessage;
}

/**
 * Lightbox component for viewing images in full size.
 */
function ImageLightbox({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <button
        onClick={onClose}
        className="absolute top-4 right-4 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
      >
        <X className="h-6 w-6" />
      </button>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        className="max-h-[90vh] max-w-[90vw] object-contain rounded-lg"
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  );
}

export function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === "user";
  const [lightboxImage, setLightboxImage] = useState<{
    src: string;
    alt: string;
  } | null>(null);

  return (
    <>
      <div
        className={cn(
          "group flex gap-2 sm:gap-4 py-3 sm:py-4",
          isUser && "flex-row-reverse"
        )}
      >
        <div
          className={cn(
            "flex-shrink-0 w-8 h-8 sm:w-9 sm:h-9 rounded-full flex items-center justify-center",
            isUser ? "bg-primary text-primary-foreground" : "bg-orange-500/10 text-orange-500"
          )}
        >
          {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4 sm:h-5 sm:w-5" />}
        </div>

        <div className={cn(
          "flex-1 space-y-2 overflow-hidden max-w-[88%] sm:max-w-[85%]",
          isUser && "flex flex-col items-end"
        )}>
          {/* Attached Images */}
          {message.attachments && message.attachments.length > 0 && (
            <div className={cn(
              "flex flex-wrap gap-2",
              isUser && "justify-end"
            )}>
              {message.attachments.map((attachment, index) => (
                <button
                  key={index}
                  onClick={() =>
                    attachment.previewUrl &&
                    setLightboxImage({
                      src: attachment.previewUrl,
                      alt: attachment.filename || `Image ${index + 1}`,
                    })
                  }
                  className="block rounded-lg overflow-hidden border border-border hover:border-primary/50 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  {attachment.previewUrl ? (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img
                      src={attachment.previewUrl}
                      alt={attachment.filename || `Attachment ${index + 1}`}
                      className="h-32 w-auto max-w-48 object-cover"
                    />
                  ) : (
                    <div className="h-32 w-32 flex items-center justify-center bg-muted text-muted-foreground text-xs">
                      {attachment.filename || "Image"}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}

          {/* Only show message bubble if there's content or if it's streaming without tool calls */}
          {(message.content || (message.isStreaming && (!message.toolCalls || message.toolCalls.length === 0))) && (
            <div className={cn(
              "relative rounded-2xl px-3 py-2 sm:px-4 sm:py-2.5",
              isUser
                ? "bg-primary text-primary-foreground rounded-tr-sm"
                : "bg-muted rounded-tl-sm"
            )}>
              {isUser ? (
                <p className="whitespace-pre-wrap break-words text-sm">
                  {message.content}
                </p>
              ) : (
                <div className="text-sm prose-sm max-w-none">
                  <MarkdownContent content={message.content} />
                  {message.isStreaming && (
                    <span className="inline-block w-1.5 h-4 ml-1 bg-current animate-pulse rounded-full" />
                  )}
                </div>
              )}

              {!isUser && message.content && !message.isStreaming && (
                <div className="absolute -right-1 -top-1 sm:opacity-0 sm:group-hover:opacity-100">
                  <CopyButton
                    text={message.content}
                    className="bg-background/80 hover:bg-background shadow-sm"
                  />
                </div>
              )}
            </div>
          )}

          {message.toolCalls && message.toolCalls.length > 0 && (
            <div className="space-y-2 w-full">
              {message.toolCalls.map((toolCall) => (
                <ToolCallCard key={toolCall.id} toolCall={toolCall} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Lightbox */}
      {lightboxImage && (
        <ImageLightbox
          src={lightboxImage.src}
          alt={lightboxImage.alt}
          onClose={() => setLightboxImage(null)}
        />
      )}
    </>
  );
}
