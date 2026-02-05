"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Pin, Loader2 } from "lucide-react";
import { FileBrowser } from "@/components/files/file-browser";
import { PinProgressDialog } from "./pin-progress-dialog";
import { usePinFiles } from "@/hooks/use-pin-files";
import { useConversations } from "@/hooks/use-conversations";
import { useConversationStore, useAuthStore } from "@/stores";
import { usePinnedContentStore } from "@/stores/pinned-content-store";
import { apiClient } from "@/lib/api-client";
import type {
  PinProgressEvent,
  PinWarningEvent,
  PinErrorEvent,
  PinCompleteEvent,
} from "@/types/pinned-content";

export interface PinFilesButtonProps {
  conversationId?: string | null;
}

export function PinFilesButton({ conversationId }: PinFilesButtonProps) {
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [showProgressDialog, setShowProgressDialog] = useState(false);
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);

  const { user } = useAuthStore();
  const { createConversation } = useConversations();
  const { setCurrentConversationId } = useConversationStore();
  const {
    setPinProgress,
    setIsPinning,
    setPinnedContent,
    isPinning: globalIsPinning,
    pinProgress: globalPinProgress,
  } = usePinnedContentStore();

  const { pinFiles, error } = usePinFiles({
    conversationId: conversationId || "",
    modelName: user?.default_model,
    autoFetch: false,
    autoCheckStaleness: false,
  });

  const handlePinFiles = async (filePaths: string[]) => {
    let activeConversationId = conversationId;
    let wasConversationCreated = false;

    // Create conversation if needed
    if (!activeConversationId) {
      setIsCreatingConversation(true);
      try {
        const newConv = await createConversation("Pinned Files");
        if (!newConv) {
          console.error("Failed to create conversation");
          return;
        }
        activeConversationId = newConv.id;
        setCurrentConversationId(newConv.id);
        wasConversationCreated = true;
      } catch (err) {
        console.error("Error creating conversation:", err);
        return;
      } finally {
        setIsCreatingConversation(false);
      }
    }

    setShowProgressDialog(true);

    // If we just created a conversation, use apiClient directly to ensure correct conversationId
    if (wasConversationCreated && activeConversationId) {
      setIsPinning(true);
      try {
        const request = {
          s3_paths: filePaths,
        };

        for await (const event of apiClient.pinFiles(activeConversationId, request)) {
          if (event.event === "progress") {
            const progressData = event.data as PinProgressEvent;
            const current = progressData.current ?? 0;
            const total = progressData.total ?? 0;
            setPinProgress({
              phase: progressData.phase,
              current,
              total,
              message: progressData.message,
              currentFile: progressData.current_file || progressData.currentFile,
              percentage: total > 0 ? Math.round((current / total) * 100) : undefined,
              tokens: progressData.tokens,
              budgetUsedPercent: progressData.budget_used_pct,
            });
          } else if (event.event === "complete") {
            const completeData = event.data as PinCompleteEvent;
            console.log("Pin complete:", completeData.message || "Files pinned successfully");

            // Fetch pinned content metadata from API
            const pinnedData = await apiClient.getPinnedContent(activeConversationId);
            if (pinnedData) {
              setPinnedContent(activeConversationId, pinnedData);
            }
            // Keep progress set so isComplete can detect success
            setPinProgress({
              phase: "storing",
              current: completeData.file_count,
              total: completeData.file_count,
              tokens: completeData.total_tokens,
            });
          } else if (event.event === "error") {
            const errorData = event.data as PinErrorEvent;
            console.error("Pin error:", errorData.message);
            throw new Error(errorData.message || "Pin operation failed");
          } else if (event.event === "warning") {
            const warningData = event.data as PinWarningEvent;
            console.warn("Pin warning:", warningData.message);
          }
        }

        setSelectedFiles([]); // Clear selection after successful pin
      } catch (err) {
        console.error("Pin failed:", err);
      } finally {
        setIsPinning(false);
      }
    } else {
      // Use the hook's pinFiles for existing conversations
      try {
        await pinFiles(filePaths);
        setSelectedFiles([]); // Clear selection after successful pin
      } catch (err) {
        console.error("Pin failed:", err);
      }
    }
  };

  const handleRetry = () => {
    if (selectedFiles.length > 0) {
      handlePinFiles(selectedFiles);
    }
  };

  return (
    <>
      <FileBrowser
        selectionMode={true}
        selectedFiles={selectedFiles}
        onSelectionChange={setSelectedFiles}
        showPinAction={true}
        onPinFiles={handlePinFiles}
      >
        <Button
          variant="ghost"
          size="icon"
          title={conversationId ? "Pin Files" : "Pin Files (creates new conversation)"}
          disabled={isCreatingConversation}
        >
          {isCreatingConversation ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Pin className="h-5 w-5" />
          )}
        </Button>
      </FileBrowser>

      <PinProgressDialog
        open={showProgressDialog}
        onOpenChange={setShowProgressDialog}
        progress={globalPinProgress}
        isPinning={globalIsPinning}
        error={error}
        onRetry={handleRetry}
        onClose={() => {
          setShowProgressDialog(false);
          setSelectedFiles([]);
        }}
      />
    </>
  );
}
