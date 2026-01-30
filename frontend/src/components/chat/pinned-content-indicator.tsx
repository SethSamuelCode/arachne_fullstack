"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Pin, AlertTriangle, Loader2 } from "lucide-react";
import { PinnedFilesListDialog } from "./pinned-files-list";
import { usePinFiles } from "@/hooks/use-pin-files";
import { cn } from "@/lib/utils";

export interface PinnedContentIndicatorProps {
  conversationId?: string | null;
}

export function PinnedContentIndicator({
  conversationId,
}: PinnedContentIndicatorProps) {
  const [showListDialog, setShowListDialog] = useState(false);

  const {
    pinnedInfo,
    stalenessData,
    isPinning,
  } = usePinFiles({
    conversationId: conversationId || "",
    autoFetch: !!conversationId,
    autoCheckStaleness: !!conversationId,
  });

  // Don't show indicator if no conversation or no files pinned
  if (!conversationId || (!pinnedInfo && !isPinning)) {
    return null;
  }

  const fileCount = pinnedInfo?.file_paths?.length ?? 0;
  const isStale = stalenessData?.is_stale ?? false;
  const changedCount =
    (stalenessData?.changed_files?.length ?? 0) +
    (stalenessData?.added_files?.length ?? 0) +
    (stalenessData?.removed_files?.length ?? 0);

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className={cn(
          "gap-1.5 h-8 px-2",
          isStale && "text-amber-600 dark:text-amber-400"
        )}
        onClick={() => setShowListDialog(true)}
        title={
          isPinning
            ? "Pinning files..."
            : isStale
              ? `${changedCount} file${changedCount !== 1 ? "s" : ""} changed`
              : `${fileCount} file${fileCount !== 1 ? "s" : ""} pinned`
        }
      >
        {isPinning ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : isStale ? (
          <AlertTriangle className="h-4 w-4" />
        ) : (
          <Pin className="h-4 w-4" />
        )}

        {isPinning ? (
          <span className="text-xs">Pinning...</span>
        ) : (
          <Badge
            variant={isStale ? "destructive" : "secondary"}
            className="h-5 px-1.5 text-xs font-normal"
          >
            {fileCount}
          </Badge>
        )}
      </Button>

      <PinnedFilesListDialog
        open={showListDialog}
        onOpenChange={setShowListDialog}
        conversationId={conversationId}
      />
    </>
  );
}
