"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Pin,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Trash2,
  Loader2,
} from "lucide-react";
import { usePinFiles } from "@/hooks/use-pin-files";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";

const PHASE_LABELS: Record<string, string> = {
  fetching: "Fetching files",
  validating: "Validating files",
  hashing: "Hashing content",
  serializing: "Serializing to XML",
  estimating: "Estimating tokens",
  uploading: "Uploading to cache",
  creating: "Creating cache",
  storing: "Storing metadata",
};

interface PinnedContentSummaryProps {
  conversationId: string | null;
}

function getChangedFileCount(stalenessData: {
  changed_files?: unknown[];
  added_files?: unknown[];
  removed_files?: unknown[];
} | null): number {
  if (!stalenessData) return 0;
  return (
    (stalenessData.changed_files?.length ?? 0) +
    (stalenessData.added_files?.length ?? 0) +
    (stalenessData.removed_files?.length ?? 0)
  );
}

export function PinnedContentSummary({ conversationId }: PinnedContentSummaryProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  const {
    pinnedInfo,
    stalenessData,
    isPinning,
    pinProgress,
    error,
    repin,
    clearPinned,
  } = usePinFiles({
    conversationId: conversationId || "",
    autoFetch: !!conversationId,
    autoCheckStaleness: !!conversationId,
  });

  if (!conversationId || (!pinnedInfo && !isPinning)) {
    return null;
  }

  const fileCount = pinnedInfo?.file_paths?.length ?? 0;
  const totalTokens = pinnedInfo?.total_tokens ?? 0;
  const isStale = stalenessData?.is_stale ?? false;
  const changedCount = getChangedFileCount(stalenessData);
  const pinnedAt = pinnedInfo?.pinned_at
    ? formatDistanceToNow(new Date(pinnedInfo.pinned_at), { addSuffix: true })
    : null;

  async function handleRepin(): Promise<void> {
    try {
      await repin();
    } catch (err) {
      console.error("Repin failed:", err);
    }
  }

  async function handleClear(): Promise<void> {
    if (confirm("Clear all pinned content? This removes the cache.")) {
      await clearPinned();
    }
  }

  if (isCollapsed) {
    return (
      <div
        className="flex items-center gap-2 px-3 py-2 border-b cursor-pointer hover:bg-accent/50 transition-colors"
        onClick={() => setIsCollapsed(false)}
      >
        <ChevronRight className="h-3 w-3 text-muted-foreground" />
        <Pin className={cn("h-3 w-3", isStale ? "text-amber-500" : "text-muted-foreground")} />
        <span className="text-xs text-muted-foreground">
          {fileCount} pinned
        </span>
        {isStale && (
          <Badge variant="destructive" className="h-4 px-1 text-[10px]">
            {changedCount} changed
          </Badge>
        )}
        {isPinning && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
      </div>
    );
  }

  const progressLabel =
    pinProgress?.message || PHASE_LABELS[pinProgress?.phase ?? ""] || "Processing...";

  return (
    <div className="border-b">
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-accent/50 transition-colors"
        onClick={() => setIsCollapsed(true)}
      >
        <ChevronDown className="h-3 w-3 text-muted-foreground" />
        <Pin className={cn("h-3 w-3", isStale ? "text-amber-500" : "text-muted-foreground")} />
        <span className="text-xs font-medium flex-1">Pinned Content</span>
        <Badge variant="secondary" className="h-5 px-1.5 text-xs">
          {fileCount}
        </Badge>
      </div>

      <div className="px-3 pb-3 space-y-2">
        {isStale && (
          <div className="flex items-start gap-2 p-2 bg-amber-500/10 border border-amber-500/20 rounded text-amber-600 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <p className="text-xs">
              {changedCount} file{changedCount !== 1 ? "s" : ""} changed since last pin
            </p>
          </div>
        )}

        {isPinning && pinProgress && (
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>{progressLabel}</span>
            </div>
            <Progress value={pinProgress.percentage ?? 0} className="h-1" />
            {pinProgress.currentFile && (
              <p className="text-[10px] text-muted-foreground truncate">
                {pinProgress.currentFile}
              </p>
            )}
          </div>
        )}

        {error && (
          <p className="text-xs text-destructive">{error}</p>
        )}

        {!isPinning && pinnedInfo && (
          <div className="text-xs text-muted-foreground space-y-0.5">
            <p>~{totalTokens.toLocaleString()} tokens</p>
            {pinnedAt && <p>Pinned {pinnedAt}</p>}
          </div>
        )}

        <div className="flex items-center gap-1">
          {isStale && (
            <Button
              variant="outline"
              size="sm"
              className="h-6 text-xs px-2"
              onClick={handleRepin}
              disabled={isPinning}
            >
              {isPinning ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : (
                <RefreshCw className="h-3 w-3 mr-1" />
              )}
              Repin All
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs px-2 text-destructive"
            onClick={handleClear}
            disabled={isPinning}
          >
            <Trash2 className="h-3 w-3 mr-1" />
            Clear
          </Button>
        </div>
      </div>
    </div>
  );
}
