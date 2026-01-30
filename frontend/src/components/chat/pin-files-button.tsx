"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Pin } from "lucide-react";
import { FileBrowser } from "@/components/files/file-browser";
import { PinProgressDialog } from "./pin-progress-dialog";
import { usePinFiles } from "@/hooks/use-pin-files";

export interface PinFilesButtonProps {
  conversationId: string;
}

export function PinFilesButton({ conversationId }: PinFilesButtonProps) {
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [showProgressDialog, setShowProgressDialog] = useState(false);

  const { pinFiles, isPinning, pinProgress, error } = usePinFiles({
    conversationId,
    autoFetch: false,
    autoCheckStaleness: false,
  });

  const handlePinFiles = async (filePaths: string[]) => {
    setShowProgressDialog(true);
    try {
      await pinFiles(filePaths);
      setSelectedFiles([]); // Clear selection after successful pin
    } catch (err) {
      console.error("Pin failed:", err);
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
        <Button variant="ghost" size="icon" title="Pin Files">
          <Pin className="h-5 w-5" />
        </Button>
      </FileBrowser>

      <PinProgressDialog
        open={showProgressDialog}
        onOpenChange={setShowProgressDialog}
        progress={pinProgress}
        isPinning={isPinning}
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
