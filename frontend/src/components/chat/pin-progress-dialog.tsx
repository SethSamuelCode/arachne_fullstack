"use client";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { CheckCircle2, Loader2, AlertCircle, XCircle } from "lucide-react";
import type { PinProgress } from "@/types/pinned-content";

export interface PinProgressDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  progress: PinProgress | null;
  isPinning: boolean;
  error: string | null;
  onRetry?: () => void;
  onClose?: () => void;
}

const PHASE_LABELS: Record<string, string> = {
  fetching: "Fetching files",
  validating: "Validating files",
  hashing: "Hashing content",
  serializing: "Serializing to XML",
  estimating: "Estimating tokens",
  creating: "Creating cache",
  storing: "Storing metadata",
};

const PHASE_ORDER = [
  "fetching",
  "validating",
  "hashing",
  "serializing",
  "estimating",
  "creating",
  "storing",
];

export function PinProgressDialog({
  open,
  onOpenChange,
  progress,
  isPinning,
  error,
  onRetry,
  onClose,
}: PinProgressDialogProps) {
  const currentPhaseIndex = progress
    ? PHASE_ORDER.indexOf(progress.phase)
    : -1;

  const progressPercentage = progress?.percentage ?? 0;

  const isComplete = !isPinning && !error && progress !== null;
  const hasWarning =
    progress?.budgetUsedPercent && progress.budgetUsedPercent >= 30;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {error
              ? "Pin Failed"
              : isComplete
                ? "Pinning Complete"
                : "Pinning Files to Cache"}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Error Display */}
          {error && (
            <div className="flex items-start gap-3 p-3 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive">
              <XCircle className="h-5 w-5 shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm font-medium">Error</p>
                <p className="text-sm mt-1">{error}</p>
              </div>
            </div>
          )}

          {/* Success Display */}
          {isComplete && !error && (
            <div className="flex items-center gap-3 p-3 bg-green-500/10 border border-green-500/20 rounded-lg text-green-600 dark:text-green-400">
              <CheckCircle2 className="h-5 w-5 shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-medium">Success!</p>
                <p className="text-sm mt-1">
                  Files pinned successfully. {progress?.tokens && `~${progress.tokens.toLocaleString()} tokens cached.`}
                </p>
              </div>
            </div>
          )}

          {/* Progress Bar */}
          {isPinning && progress && (
            <>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">
                    {progress.message}
                  </span>
                  <span className="text-muted-foreground font-medium">
                    {Math.round(progressPercentage)}%
                  </span>
                </div>
                <Progress value={progressPercentage} className="h-2" />
                {progress.currentFile && (
                  <p className="text-xs text-muted-foreground truncate">
                    {progress.currentFile}
                  </p>
                )}
              </div>

              {/* Phase List */}
              <div className="space-y-1.5">
                {PHASE_ORDER.map((phase, index) => {
                  const isCurrentPhase = index === currentPhaseIndex;
                  const isCompleted = index < currentPhaseIndex;
                  const isPending = index > currentPhaseIndex;

                  return (
                    <div
                      key={phase}
                      className="flex items-center gap-2 text-sm"
                    >
                      {isCompleted && (
                        <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400 shrink-0" />
                      )}
                      {isCurrentPhase && (
                        <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />
                      )}
                      {isPending && (
                        <div className="h-4 w-4 border-2 border-muted rounded-full shrink-0" />
                      )}
                      <span
                        className={
                          isCurrentPhase
                            ? "font-medium"
                            : isCompleted
                              ? "text-muted-foreground line-through"
                              : "text-muted-foreground"
                        }
                      >
                        {PHASE_LABELS[phase] || phase}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Token Budget Warning */}
              {hasWarning && progress.budgetUsedPercent && (
                <div className="flex items-start gap-2 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-600 dark:text-amber-400">
                  <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <div className="text-sm">
                    <p className="font-medium">
                      Token budget at {Math.round(progress.budgetUsedPercent)}%
                    </p>
                    <p className="text-xs mt-0.5">
                      Consider reducing the number of files to stay under 40% budget.
                    </p>
                  </div>
                </div>
              )}

              {/* Token Estimate */}
              {progress.tokens && (
                <div className="text-sm text-muted-foreground">
                  <p>
                    Estimated tokens: ~{progress.tokens.toLocaleString()}
                    {progress.budgetUsedPercent && (
                      <span className="ml-2">
                        ({Math.round(progress.budgetUsedPercent)}% of budget)
                      </span>
                    )}
                  </p>
                </div>
              )}
            </>
          )}

          {/* Action Buttons */}
          <div className="flex justify-end gap-2 pt-2">
            {error && onRetry && (
              <Button onClick={onRetry} variant="outline">
                Retry
              </Button>
            )}
            <Button
              onClick={() => {
                onClose?.();
                onOpenChange(false);
              }}
              variant={isComplete ? "default" : "outline"}
            >
              {isComplete ? "Done" : error ? "Close" : "Cancel"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
