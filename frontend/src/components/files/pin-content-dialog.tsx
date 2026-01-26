"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogClose,
  DialogBody,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  usePinContent,
  type PinProgress,
  type PinWarning,
  type PinnedContentInfo,
} from "@/hooks/use-pin-content";
import { useConversationStore } from "@/stores";
import {
  Pin,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  FileText,
  Clock,
  Hash,
} from "lucide-react";
import { cn } from "@/lib/utils";

// =============================================================================
// Types
// =============================================================================

interface PinContentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selectedFiles: string[];
  onPinComplete?: () => void;
}

// =============================================================================
// Component
// =============================================================================

export function PinContentDialog({
  open,
  onOpenChange,
  selectedFiles,
  onPinComplete,
}: PinContentDialogProps) {
  const t = useTranslations("pinContent");
  const tCommon = useTranslations("common");
  const { currentConversationId } = useConversationStore();

  const {
    isPinning,
    progress,
    warnings,
    error,
    result,
    pinnedInfo,
    pinContent,
    fetchPinnedInfo,
    cancel,
    reset,
  } = usePinContent();

  const [showExisting, setShowExisting] = useState(false);

  // Fetch existing pinned info when dialog opens
  useEffect(() => {
    if (open && currentConversationId) {
      fetchPinnedInfo(currentConversationId);
    }
  }, [open, currentConversationId, fetchPinnedInfo]);

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      reset();
      setShowExisting(false);
    }
  }, [open, reset]);

  const handlePin = async () => {
    if (!currentConversationId || selectedFiles.length === 0) return;

    const success = await pinContent(currentConversationId, selectedFiles);
    if (success) {
      onPinComplete?.();
    }
  };

  const handleClose = () => {
    if (isPinning) {
      cancel();
    }
    onOpenChange(false);
  };

  const getProgressPercent = (prog: PinProgress | null): number => {
    if (!prog) return 0;
    if (prog.phase === "complete") return 100;
    if (prog.total === 0) return 0;
    return Math.round((prog.current / prog.total) * 100);
  };

  const getPhaseLabel = (phase: string): string => {
    switch (phase) {
      case "fetching":
        return t("phaseFetching");
      case "serializing":
        return t("phaseSerializing");
      case "uploading":
        return t("phaseUploading");
      case "complete":
        return t("phaseComplete");
      default:
        return phase;
    }
  };

  const formatTokens = (tokens: number): string => {
    if (tokens >= 1_000_000) {
      return `${(tokens / 1_000_000).toFixed(1)}M`;
    }
    if (tokens >= 1_000) {
      return `${(tokens / 1_000).toFixed(1)}K`;
    }
    return tokens.toString();
  };

  const formatDate = (dateStr: string): string => {
    return new Date(dateStr).toLocaleString();
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Pin className="h-5 w-5" />
            {t("title")}
          </DialogTitle>
          <DialogClose onClick={handleClose} />
        </DialogHeader>

        <DialogBody className="space-y-4">
          {/* No conversation selected */}
          {!currentConversationId && (
            <div className="text-center py-8 text-muted-foreground">
              <AlertTriangle className="h-8 w-8 mx-auto mb-2" />
              <p>{t("noConversation")}</p>
            </div>
          )}

          {/* Existing pinned content info */}
          {pinnedInfo && !isPinning && !result && (
            <div className="bg-muted/50 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{t("existingPinned")}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowExisting(!showExisting)}
                >
                  {showExisting ? tCommon("close") : t("showDetails")}
                </Button>
              </div>
              {showExisting && (
                <ExistingPinnedInfo info={pinnedInfo} formatTokens={formatTokens} formatDate={formatDate} t={t} />
              )}
              <p className="text-xs text-muted-foreground">
                {t("willReplace")}
              </p>
            </div>
          )}

          {/* Selected files summary */}
          {currentConversationId && !isPinning && !result && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <FileText className="h-4 w-4" />
                <span>
                  {t("selectedFiles", { count: selectedFiles.length })}
                </span>
              </div>
              <div className="max-h-32 overflow-y-auto bg-muted/30 rounded p-2 text-xs font-mono">
                {selectedFiles.map((path) => (
                  <div key={path} className="truncate">
                    {path}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Progress */}
          {isPinning && progress && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-sm font-medium">
                  {getPhaseLabel(progress.phase)}
                </span>
              </div>
              <Progress value={getProgressPercent(progress)} className="h-2" />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>
                  {progress.current} / {progress.total}
                </span>
                <span>{getProgressPercent(progress)}%</span>
              </div>
              {progress.currentFile && (
                <p className="text-xs text-muted-foreground truncate">
                  {progress.currentFile}
                </p>
              )}
            </div>
          )}

          {/* Warnings */}
          {warnings.length > 0 && (
            <div className="space-y-2">
              {warnings.map((warning, idx) => (
                <WarningItem key={idx} warning={warning} />
              ))}
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-3 flex items-start gap-2">
              <XCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-destructive">
                  {error.code}
                </p>
                <p className="text-xs text-destructive/80">{error.message}</p>
              </div>
            </div>
          )}

          {/* Success result */}
          {result && (
            <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2 text-green-600">
                <CheckCircle2 className="h-5 w-5" />
                <span className="font-medium">{t("success")}</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-muted-foreground" />
                  <span>
                    {t("filesCount", { count: result.file_count })}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Hash className="h-4 w-4 text-muted-foreground" />
                  <span>{formatTokens(result.total_tokens)} tokens</span>
                </div>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            {isPinning ? (
              <Button variant="outline" onClick={cancel}>
                {tCommon("cancel")}
              </Button>
            ) : result ? (
              <Button onClick={handleClose}>{tCommon("close")}</Button>
            ) : (
              <>
                <Button variant="outline" onClick={handleClose}>
                  {tCommon("cancel")}
                </Button>
                <Button
                  onClick={handlePin}
                  disabled={!currentConversationId || selectedFiles.length === 0}
                >
                  <Pin className="h-4 w-4 mr-2" />
                  {t("pinButton")}
                </Button>
              </>
            )}
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

// =============================================================================
// Sub-components
// =============================================================================

function WarningItem({ warning }: { warning: PinWarning }) {
  return (
    <div
      className={cn(
        "rounded-lg p-3 flex items-start gap-2",
        warning.type === "budget_warning"
          ? "bg-yellow-500/10 border border-yellow-500/20"
          : "bg-orange-500/10 border border-orange-500/20"
      )}
    >
      <AlertTriangle
        className={cn(
          "h-4 w-4 mt-0.5 shrink-0",
          warning.type === "budget_warning"
            ? "text-yellow-600"
            : "text-orange-600"
        )}
      />
      <div className="text-sm">
        <p>{warning.message}</p>
        {warning.path && (
          <p className="text-xs text-muted-foreground mt-1">{warning.path}</p>
        )}
      </div>
    </div>
  );
}

interface ExistingPinnedInfoProps {
  info: PinnedContentInfo;
  formatTokens: (tokens: number) => string;
  formatDate: (dateStr: string) => string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: (key: string, values?: any) => string;
}

function ExistingPinnedInfo({
  info,
  formatTokens,
  formatDate,
  t,
}: ExistingPinnedInfoProps) {
  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <Clock className="h-3 w-3 text-muted-foreground" />
        <span>{formatDate(info.pinned_at)}</span>
      </div>
      <div className="flex items-center gap-2">
        <FileText className="h-3 w-3 text-muted-foreground" />
        <span>{t("filesCount", { count: info.file_paths.length })}</span>
      </div>
      <div className="flex items-center gap-2">
        <Hash className="h-3 w-3 text-muted-foreground" />
        <span>{formatTokens(info.total_tokens)} tokens</span>
      </div>
      <div className="max-h-24 overflow-y-auto bg-background/50 rounded p-2 font-mono">
        {info.file_paths.map((path) => (
          <div key={path} className="truncate">
            {path}
          </div>
        ))}
      </div>
    </div>
  );
}
