"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Brain } from "lucide-react";
import { cn } from "@/lib/utils";

interface ThinkingBlockProps {
  content: string;
  isStreaming?: boolean;
  /** Maximum characters to show in collapsed preview */
  previewLength?: number;
}

/**
 * Collapsible block to display model's thinking/reasoning content.
 * Shows a truncated preview when collapsed, full content when expanded.
 */
export function ThinkingBlock({
  content,
  isStreaming = false,
  previewLength = 500,
}: ThinkingBlockProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!content && !isStreaming) {
    return null;
  }

  const needsTruncation = content.length > previewLength;
  const displayContent = isExpanded || !needsTruncation
    ? content
    : content.slice(0, previewLength) + "...";

  return (
    <div className="rounded-lg border border-muted bg-muted/30 overflow-hidden">
      {/* Header - clickable to toggle */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:bg-muted/50 transition-colors"
      >
        {isExpanded ? (
          <ChevronDown className="h-3 w-3 flex-shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 flex-shrink-0" />
        )}
        <Brain className="h-3 w-3 flex-shrink-0" />
        <span className="italic">
          {isStreaming ? "Thinking..." : "Show thinking"}
        </span>
        {isStreaming && (
          <span className="ml-auto inline-block w-1.5 h-3 bg-current animate-pulse rounded-full" />
        )}
      </button>

      {/* Content - collapsible */}
      <div
        className={cn(
          "overflow-hidden transition-all duration-200",
          isExpanded ? "max-h-[2000px]" : "max-h-0"
        )}
      >
        <div className="px-3 py-2 border-t border-muted">
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap break-words font-mono leading-relaxed">
            {displayContent}
          </pre>
          {!isExpanded && needsTruncation && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setIsExpanded(true);
              }}
              className="mt-1 text-xs text-primary hover:underline"
            >
              Show more
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
