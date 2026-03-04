"use client";

import { useCallback, useRef, useState } from "react";
import { nanoid } from "nanoid";
import { useChatStore, useConversationStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
import type { ChatMessage, ChatAttachment, ToolCall } from "@/types";

interface UseAgentRunOptions {
  conversationId?: string | null;
  onConversationCreated?: (conversationId: string) => void;
  ensureConversation?: () => Promise<string | null>;
}

interface AgentRunResponse {
  job_id: string;
  conversation_id: string;
  stream_url: string;
}

/**
 * Attachment payload format sent to backend.
 * Matches backend AttachmentInMessage schema.
 */
interface AttachmentPayload {
  s3_key: string;
  mime_type: string;
  size_bytes: number;
  filename?: string;
}

/** SSE event types we listen for */
const SSE_EVENT_TYPES = [
  "conversation_created",
  "conversation_updated",
  "model_request_start",
  "thinking_delta",
  "text_delta",
  "tool_call_delta",
  "call_tools_start",
  "tool_call",
  "tool_result",
  "final_result_start",
  "final_result",
  "complete",
  "cancelled",
  "error",
] as const;

/**
 * Hook for SSE-based agent execution (replaces WebSocket-based useChat).
 *
 * Starts agent runs via HTTP POST, streams events via SSE with
 * browser-native Last-Event-ID reconnection support.
 */
export function useAgentRun(options: UseAgentRunOptions = {}) {
  const { conversationId, onConversationCreated, ensureConversation } = options;
  const { setCurrentConversationId } = useConversationStore();
  const {
    messages,
    addMessage,
    updateMessage,
    addToolCall,
    updateToolCall,
    clearMessages,
  } = useChatStore();

  const [isProcessing, setIsProcessing] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const currentMessageIdRef = useRef<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const cleanup = useCallback(() => {
    setIsProcessing(false);
    setCurrentJobId(null);
    currentMessageIdRef.current = null;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const handleSSEEvent = useCallback(
    (type: string, data: Record<string, unknown>) => {
      const currentMessageId = currentMessageIdRef.current;

      switch (type) {
        case "conversation_created": {
          const convId = data.conversation_id as string;
          setCurrentConversationId(convId);
          onConversationCreated?.(convId);
          break;
        }

        case "conversation_updated": {
          const { conversation_id, title } = data as {
            conversation_id: string;
            title: string;
          };
          useConversationStore
            .getState()
            .updateConversation(conversation_id, { title });
          break;
        }

        case "model_request_start": {
          const newMsgId = nanoid();
          currentMessageIdRef.current = newMsgId;
          addMessage({
            id: newMsgId,
            role: "assistant",
            content: "",
            timestamp: new Date(),
            isStreaming: true,
            isThinkingStreaming: false,
            thinkingContent: "",
            toolCalls: [],
          });
          break;
        }

        case "thinking_delta": {
          if (currentMessageId) {
            const content = data.content as string;
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              thinkingContent: (msg.thinkingContent || "") + content,
              isThinkingStreaming: true,
            }));
          }
          break;
        }

        case "text_delta": {
          if (currentMessageId) {
            const content = data.content as string;
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              content: msg.content + content,
            }));
          }
          break;
        }

        case "tool_call": {
          if (currentMessageId) {
            const { tool_name, args, tool_call_id } = data as {
              tool_name: string;
              args: Record<string, unknown>;
              tool_call_id: string;
            };
            const toolCall: ToolCall = {
              id: tool_call_id,
              name: tool_name,
              args,
              status: "running",
            };
            addToolCall(currentMessageId, toolCall);
          }
          break;
        }

        case "tool_result": {
          if (currentMessageId) {
            const { tool_call_id, content } = data as {
              tool_call_id: string;
              content: string;
            };
            updateToolCall(currentMessageId, tool_call_id, {
              result: content,
              status: "completed",
            });
          }
          break;
        }

        case "final_result": {
          if (currentMessageId) {
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              isStreaming: false,
              isThinkingStreaming: false,
            }));
          }
          break;
        }

        case "error": {
          if (currentMessageId) {
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              content: msg.content + "\n\n[Error occurred]",
              isStreaming: false,
            }));
          }
          cleanup();
          break;
        }

        case "cancelled": {
          if (currentMessageId) {
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              content: msg.content + "\n\n[Cancelled]",
              isStreaming: false,
            }));
          }
          cleanup();
          break;
        }

        case "complete": {
          cleanup();
          break;
        }
      }
    },
    [
      addMessage,
      updateMessage,
      addToolCall,
      updateToolCall,
      setCurrentConversationId,
      onConversationCreated,
      cleanup,
    ]
  );

  const connectToStream = useCallback(
    (streamUrl: string) => {
      const eventSource = new EventSource(`/api${streamUrl}`, {
        withCredentials: true,
      });
      eventSourceRef.current = eventSource;

      for (const type of SSE_EVENT_TYPES) {
        eventSource.addEventListener(type, (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            handleSSEEvent(type, data);
          } catch {
            handleSSEEvent(type, {});
          }
        });
      }

      eventSource.onerror = () => {
        // EventSource auto-reconnects with Last-Event-ID.
        // If the job is done, the reconnect will get a 404 and stop.
        console.warn("SSE connection error, auto-reconnecting...");
      };
    },
    [handleSSEEvent]
  );

  const sendMessage = useCallback(
    async (
      content: string,
      attachments?: ChatAttachment[],
      systemPrompt?: string
    ) => {
      // Ensure a conversation exists before sending
      let activeConversationId = conversationId || null;
      if (!activeConversationId && ensureConversation) {
        activeConversationId = await ensureConversation();
      }

      // Only include uploaded attachments
      const uploadedAttachments =
        attachments?.filter((a) => a.status === "uploaded") || [];

      // Add user message to local store
      const userMessage: ChatMessage = {
        id: nanoid(),
        role: "user",
        content,
        timestamp: new Date(),
        attachments:
          uploadedAttachments.length > 0 ? uploadedAttachments : undefined,
      };
      addMessage(userMessage);

      // Build attachment payload
      const attachmentPayloads: AttachmentPayload[] = uploadedAttachments.map(
        (a) => ({
          s3_key: a.s3Key,
          mime_type: a.mimeType,
          size_bytes: a.sizeBytes,
          filename: a.filename,
        })
      );

      setIsProcessing(true);

      try {
        // Start agent run via HTTP POST
        const response = await apiClient.post<AgentRunResponse>(
          "/agent/run",
          {
            content,
            conversation_id: activeConversationId,
            system_prompt: systemPrompt,
            attachments:
              attachmentPayloads.length > 0 ? attachmentPayloads : undefined,
          }
        );

        setCurrentJobId(response.job_id);

        // If this created a new conversation, notify
        if (!activeConversationId && response.conversation_id) {
          setCurrentConversationId(response.conversation_id);
          onConversationCreated?.(response.conversation_id);
        }

        // Connect to SSE stream
        connectToStream(response.stream_url);
      } catch (error) {
        console.error("Failed to start agent run:", error);
        setIsProcessing(false);
      }
    },
    [
      addMessage,
      conversationId,
      ensureConversation,
      connectToStream,
      setCurrentConversationId,
      onConversationCreated,
    ]
  );

  const cancelRun = useCallback(async () => {
    if (!currentJobId) return;
    try {
      await apiClient.post(`/agent/run/${currentJobId}/cancel`);
    } catch (error) {
      console.error("Failed to cancel agent run:", error);
    }
  }, [currentJobId]);

  return {
    messages,
    isProcessing,
    sendMessage,
    cancelRun,
    clearMessages,
    currentJobId,
  };
}
