"use client";

import { useEffect, useRef, useCallback } from "react";
import { useChat, useConversations, useModelCapabilities } from "@/hooks";
import { MessageList } from "./message-list";
import { ChatInput } from "./chat-input";
import { Button } from "@/components/ui";
import { Wifi, WifiOff, RotateCcw, Bot, PanelRightOpen, PanelRightClose } from "lucide-react";
import { useConversationStore, useChatStore, useAuthStore, useFilesSidebarStore } from "@/stores";
import { useRouter } from "@/i18n/navigation";
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle, useDefaultLayout } from "react-resizable-panels";
import { SystemPromptSettings } from "./system-prompt-settings";
import { PinnedContentIndicator } from "./pinned-content-indicator";
import { ChatFilesSidebar } from "./chat-files-sidebar";
import { usePinnedContentStore } from "@/stores/pinned-content-store";
import { useState } from "react";
import { Settings2 } from "lucide-react";
import { FileBrowser } from "@/components/files";

export function ChatContainer() {
  const { isAuthenticated, isLoading } = useAuthStore();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading || !isAuthenticated) {
    return null;
  }

  return <AuthenticatedChatContainer />;
}

function AuthenticatedChatContainer() {
  const { currentConversationId, currentMessages, conversations } = useConversationStore();
  const { addMessage: addChatMessage } = useChatStore();
  const { fetchConversations, updateConversationDetails, ensureConversation } = useConversations();
  const prevConversationIdRef = useRef<string | null | undefined>(undefined);
  
  const [systemPrompt, setSystemPrompt] = useState("");

  // Sync System Prompt
  useEffect(() => {
    if (currentConversationId) {
        const conv = conversations.find(c => c.id === currentConversationId);
        if (conv) {
             setSystemPrompt(conv.system_prompt || "");
        }
    } else {
        setSystemPrompt("");
    }
  }, [currentConversationId, conversations]);

  const handleSystemPromptSave = async (newPrompt: string) => {
      if (currentConversationId) {
          await updateConversationDetails(currentConversationId, { system_prompt: newPrompt });
      }
  };

  const handleConversationCreated = useCallback(() => {
    fetchConversations();
  }, [fetchConversations]);

  const {
    messages,
    isConnected,
    isProcessing,
    connect,
    disconnect,
    sendMessage,
    clearMessages,
  } = useChat({
    conversationId: currentConversationId,
    onConversationCreated: handleConversationCreated,
    ensureConversation,
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isUserNearBottomRef = useRef(true);

  // Track if user is near the bottom of the scroll container
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    
    const threshold = 100; // pixels from bottom to consider "at bottom"
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    isUserNearBottomRef.current = distanceFromBottom <= threshold;
  }, []);

  // Clear messages when conversation changes, but NOT when going from null to a new ID
  // (that happens when a new chat is saved - we want to keep the messages)
  useEffect(() => {
    const prevId = prevConversationIdRef.current;
    const currId = currentConversationId;

    // Skip initial mount
    if (prevId === undefined) {
      prevConversationIdRef.current = currId;
      return;
    }

    // Clear messages when:
    // 1. Going from a conversation to null (new chat)
    // 2. Switching between two different conversations
    // Do NOT clear when going from null to a conversation (new chat being saved)
    const shouldClear =
      currId === null || // Going to new chat
      (prevId !== null && prevId !== currId); // Switching between conversations

    if (shouldClear) {
      clearMessages();
    }

    prevConversationIdRef.current = currId;
  }, [currentConversationId, clearMessages]);

  // Load messages from conversation store when switching to a saved conversation
  useEffect(() => {
    if (currentMessages.length > 0) {
      currentMessages.forEach((msg) => {
        addChatMessage({
          id: msg.id,
          role: msg.role,
          content: msg.content,
          timestamp: new Date(msg.created_at),
          thinkingContent: msg.thinking_content || undefined,
          toolCalls: msg.tool_calls?.map((tc) => ({
            id: tc.tool_call_id,
            name: tc.tool_name,
            args: tc.args,
            result: tc.result,
            status: tc.status === "failed" ? "error" : tc.status,
          })),
        });
      });
    }
  }, [currentMessages, addChatMessage]);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  // Auto-scroll to bottom only if user is near the bottom
  useEffect(() => {
    if (isUserNearBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  return (
    <ChatUI
      messages={messages}
      isConnected={isConnected}
      isProcessing={isProcessing}
      sendMessage={(content, attachments) => sendMessage(content, attachments, systemPrompt)}
      clearMessages={clearMessages}
      messagesEndRef={messagesEndRef}
      scrollContainerRef={scrollContainerRef}
      onScroll={handleScroll}
      systemPrompt={systemPrompt}
      setSystemPrompt={setSystemPrompt}
      onSystemPromptSave={handleSystemPromptSave}
      currentConversationId={currentConversationId}
      ensureConversation={ensureConversation}
    />
  );
}

interface ChatUIProps {
  messages: import("@/types").ChatMessage[];
  isConnected: boolean;
  isProcessing: boolean;
  sendMessage: (content: string, attachments?: import("@/types").ChatAttachment[]) => void;
  clearMessages: () => void;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  systemPrompt?: string;
  setSystemPrompt?: (prompt: string) => void;
  onSystemPromptSave?: (prompt: string) => Promise<void>;
  currentConversationId?: string | null;
  ensureConversation?: () => Promise<string | null>;
}

function ChatUI({
  messages,
  isConnected,
  isProcessing,
  sendMessage,
  clearMessages,
  messagesEndRef,
  scrollContainerRef,
  onScroll,
  systemPrompt,
  setSystemPrompt,
  onSystemPromptSave,
  currentConversationId,
  ensureConversation,
}: ChatUIProps) {
  const { isOpen: sidebarOpen, toggle: toggleSidebar } = useFilesSidebarStore();
  const modalities = useModelCapabilities();
  const stalenessData = usePinnedContentStore((s) => s.stalenessData);
  const isStale = currentConversationId
    ? stalenessData[currentConversationId]?.is_stale ?? false
    : false;

  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: "chat-files-sidebar",
  });

  // Use saved layout or default to 70/30 split when sidebar is open
  const effectiveLayout = sidebarOpen 
    ? (defaultLayout && Object.keys(defaultLayout).length === 2 ? defaultLayout : { 0: 70, 1: 30 })
    : undefined;

  return (
    <PanelGroup 
      orientation="horizontal" 
      defaultLayout={effectiveLayout} 
      onLayoutChanged={sidebarOpen ? onLayoutChanged : undefined}
    >
      <Panel minSize={40}>
        <div className="flex flex-col h-full mx-auto w-full">
          <div
            ref={scrollContainerRef}
            onScroll={onScroll}
            className="flex-1 overflow-y-auto px-2 py-4 sm:px-4 sm:py-6 scrollbar-thin"
          >
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-4">
                <div className="w-14 h-14 sm:w-16 sm:h-16 rounded-full bg-secondary flex items-center justify-center">
                  <Bot className="h-7 w-7 sm:h-8 sm:w-8" />
                </div>
                <div className="text-center px-4">
                  <p className="text-base sm:text-lg font-medium text-foreground">Arachne Chat</p>
                  <p className="text-sm">Start a conversation to get help</p>

                  {setSystemPrompt && (
                    <div className="mt-4">
                         <SystemPromptSettings
                          systemPrompt={systemPrompt || ""}
                          setSystemPrompt={setSystemPrompt}
                          onSave={onSystemPromptSave}
                       >
                         <Button variant="outline" size="sm" className="gap-2">
                            <Settings2 className="h-4 w-4" />
                            Customize System Prompt
                         </Button>
                       </SystemPromptSettings>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <MessageList messages={messages} />
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="px-2 pb-2 sm:px-4 sm:pb-0">
            <div className="rounded-xl border bg-card shadow-sm p-3 sm:p-4">
              <ChatInput
                onSend={sendMessage}
                disabled={!isConnected || isProcessing}
                isProcessing={isProcessing}
                supportsImages={modalities.images}
              />
              <div className="flex items-center justify-between mt-3 pt-3 border-t">
                <div className="flex items-center gap-2">
                  {isConnected ? (
                    <Wifi className="h-3.5 w-3.5 text-green-500" />
                  ) : (
                    <WifiOff className="h-3.5 w-3.5 text-red-500" />
                  )}
                  <span className="text-xs text-muted-foreground">
                    {isConnected ? "Connected" : "Disconnected"}
                  </span>
                  {currentConversationId && (
                    <PinnedContentIndicator conversationId={currentConversationId} />
                  )}
                </div>
                <div className="flex items-center gap-1">
                    {!sidebarOpen && <FileBrowser />}
                    {setSystemPrompt && (
                       <SystemPromptSettings
                          systemPrompt={systemPrompt || ""}
                          setSystemPrompt={setSystemPrompt}
                          onSave={onSystemPromptSave}
                          isLoading={isProcessing}
                       />
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={toggleSidebar}
                      className="relative h-8 px-2"
                      title={sidebarOpen ? "Close files sidebar" : "Open files sidebar"}
                    >
                      {sidebarOpen ? (
                        <PanelRightClose className="h-3.5 w-3.5" />
                      ) : (
                        <PanelRightOpen className="h-3.5 w-3.5" />
                      )}
                      {isStale && !sidebarOpen && (
                        <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-amber-500" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={clearMessages}
                      className="text-xs h-8 px-3"
                    >
                      <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
                      Reset
                    </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Panel>
      {sidebarOpen && (
        <>
          <PanelResizeHandle className="hidden md:flex w-1.5 bg-border hover:bg-primary/20 transition-colors" />
          <Panel defaultSize={30} minSize={25} className="hidden md:flex">
            <ChatFilesSidebar conversationId={currentConversationId ?? null} onConversationNeeded={ensureConversation} />
          </Panel>
        </>
      )}
    </PanelGroup>
  );
}
