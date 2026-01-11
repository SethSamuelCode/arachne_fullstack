"use client";

import { cloneElement, isValidElement, useEffect, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Settings } from "lucide-react";
import { useConversationStore } from "@/stores";

interface SystemPromptSettingsProps {
  systemPrompt: string;
  setSystemPrompt: (value: string) => void;
  onSave?: (value: string) => Promise<void>;
  isLoading?: boolean;
  children?: React.ReactNode;
}

export function SystemPromptSettings({
  systemPrompt,
  setSystemPrompt,
  onSave,
  isLoading,
  children
}: SystemPromptSettingsProps) {
  const [localPrompt, setLocalPrompt] = useState(systemPrompt);
  const [isOpen, setIsOpen] = useState(false);
  const { currentConversationId } = useConversationStore();

  // Sync local prompt when prop changes (e.g. switching conversations)
  useEffect(() => {
    setLocalPrompt(systemPrompt);
  }, [systemPrompt]);

  const handleSave = async () => {
    if (onSave) {
        await onSave(localPrompt);
    }
    setSystemPrompt(localPrompt);
    setIsOpen(false);
  };

  const trigger = children || (
    <Button variant="ghost" size="icon" title="System Prompt & Memory Settings">
      <Settings className="h-5 w-5" />
    </Button>
  );

  return (
    <>
      {isValidElement(trigger) 
        ? cloneElement(trigger as React.ReactElement<React.HTMLAttributes<HTMLElement>>, { onClick: () => setIsOpen(true) })
        : <div onClick={() => setIsOpen(true)}>{trigger}</div>
      }

      <Sheet open={isOpen} onOpenChange={setIsOpen}>
        <SheetContent>
            <SheetHeader>
            <SheetTitle>Conversation Settings</SheetTitle>
            <div className="text-sm text-muted-foreground">
                Configure the specific instructions and memory for this conversation.
            </div>
            </SheetHeader>
            <div className="p-4 space-y-6">
            <div className="space-y-2">
                <Label htmlFor="system-prompt">System Prompt</Label>
                <p className="text-xs text-muted-foreground">
                Pinned context that guides the AI&apos;s behavior.
                </p>
                <textarea
                id="system-prompt"
                className="flex min-h-[300px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-y"
                value={localPrompt}
                onChange={(e) => setLocalPrompt(e.target.value)}
                placeholder="You are a helpful assistant..."
                />
            </div>
            
            <div className="space-y-2">
                <Label>Semantic Memory</Label>
                <div className="text-sm text-muted-foreground">
                Context window size: <strong>1000 messages</strong> (Auto-enabled)
                </div>
            </div>
            </div>
            
            <div className="border-t p-4">
                <Button onClick={handleSave} disabled={isLoading} className="w-full">
                    {isLoading ? "Saving..." : "Save Changes"}
                </Button>
            </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
