"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AlertTriangle, File, RefreshCw, Trash2, Loader2 } from "lucide-react";
import { usePinFiles } from "@/hooks/use-pin-files";
import { useAuthStore } from "@/stores";
import { PinProgressDialog } from "./pin-progress-dialog";
import { formatDistanceToNow } from "date-fns";

export interface PinnedFilesListDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  conversationId: string;
}

export function PinnedFilesListDialog({
  open,
  onOpenChange,
  conversationId,
}: PinnedFilesListDialogProps) {
  const [showProgressDialog, setShowProgressDialog] = useState(false);
  const { user } = useAuthStore();

  const {
    pinnedInfo,
    stalenessData,
    isPinning,
    pinProgress,
    error,
    repin,
    clearPinned,
  } = usePinFiles({
    conversationId,
    modelName: user?.default_model,
    autoFetch: true,
    autoCheckStaleness: true,
  });

  const isStale = stalenessData?.is_stale ?? false;
  const changedFiles = new Set([
    ...(stalenessData?.changed_files ?? []),
    ...(stalenessData?.added_files ?? []),
  ]);

  const handleRepin = async () => {
    setShowProgressDialog(true);
    try {
      await repin();
    } catch (err) {
      console.error("Repin failed:", err);
    }
  };

  const handleClearAll = async () => {
    if (
      confirm(
        "Are you sure you want to clear all pinned content? This will remove the cache."
      )
    ) {
      await clearPinned();
      onOpenChange(false);
    }
  };

  if (!pinnedInfo) {
    return null;
  }

  const fileCount = pinnedInfo.file_paths.length;
  const totalTokens = pinnedInfo.total_tokens;
  const pinnedAt = pinnedInfo.pinned_at
    ? formatDistanceToNow(new Date(pinnedInfo.pinned_at), { addSuffix: true })
    : "Unknown";

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Pinned Files ({fileCount})</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            {/* Staleness Warning */}
            {isStale && (
              <div className="flex items-start gap-3 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-600 dark:text-amber-400">
                <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-sm font-medium">
                    {changedFiles.size} file{changedFiles.size !== 1 ? "s have" : " has"} changed
                  </p>
                  <p className="text-xs mt-0.5">
                    The pinned content is outdated. Click &quot;Repin All&quot; to update the cache.
                  </p>
                </div>
              </div>
            )}

            {/* File List */}
            <ScrollArea className="h-64 w-full rounded-md border">
              <div className="p-4 space-y-2">
                {pinnedInfo.file_paths.map((filePath) => {
                  const isChanged = changedFiles.has(filePath);
                  const isRemoved = stalenessData?.removed_files?.includes(filePath);

                  return (
                    <div
                      key={filePath}
                      className="flex items-start gap-2 p-2 rounded hover:bg-accent/50 transition-colors"
                    >
                      {isChanged && (
                        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-500" />
                      )}
                      {isRemoved && (
                        <Trash2 className="h-4 w-4 shrink-0 mt-0.5 text-destructive" />
                      )}
                      {!isChanged && !isRemoved && (
                        <File className="h-4 w-4 shrink-0 mt-0.5 text-muted-foreground" />
                      )}
                      <div className="flex-1 min-w-0">
                        <p
                          className={`text-sm font-mono truncate ${
                            isRemoved ? "line-through text-muted-foreground" : ""
                          }`}
                          title={filePath}
                        >
                          {filePath}
                        </p>
                        {isChanged && (
                          <p className="text-xs text-amber-600 dark:text-amber-400">
                            Modified
                          </p>
                        )}
                        {isRemoved && (
                          <p className="text-xs text-destructive">Deleted</p>
                        )}
                      </div>
                    </div>
                  );
                })}

                {/* Show added files */}
                {stalenessData?.added_files?.map((filePath) => (
                  <div
                    key={filePath}
                    className="flex items-start gap-2 p-2 rounded hover:bg-accent/50 transition-colors"
                  >
                    <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-green-500" />
                    <div className="flex-1 min-w-0">
                      <p
                        className="text-sm font-mono truncate"
                        title={filePath}
                      >
                        {filePath}
                      </p>
                      <p className="text-xs text-green-600 dark:text-green-400">
                        Added
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>

            {/* Metadata */}
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <div className="space-y-0.5">
                <p>
                  Total tokens: ~{totalTokens.toLocaleString()}
                </p>
                <p className="text-xs">Pinned {pinnedAt}</p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex justify-between gap-2 pt-2 border-t">
              <Button
                variant="outline"
                onClick={handleClearAll}
                className="text-destructive"
                disabled={isPinning}
              >
                <Trash2 className="h-4 w-4 mr-2" />
                Clear All
              </Button>
              <div className="flex gap-2">
                {isStale && (
                  <Button
                    onClick={handleRepin}
                    disabled={isPinning}
                  >
                    {isPinning ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Repinning...
                      </>
                    ) : (
                      <>
                        <RefreshCw className="h-4 w-4 mr-2" />
                        Repin All
                      </>
                    )}
                  </Button>
                )}
                <Button variant="outline" onClick={() => onOpenChange(false)}>
                  Close
                </Button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <PinProgressDialog
        open={showProgressDialog}
        onOpenChange={setShowProgressDialog}
        progress={pinProgress}
        isPinning={isPinning}
        error={error}
        onRetry={handleRepin}
        onClose={() => setShowProgressDialog(false)}
      />
    </>
  );
}
