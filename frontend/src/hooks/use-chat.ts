"use client";

import { useCallback, useState, useEffect } from "react";
import { nanoid } from "nanoid";
import { useWebSocket } from "./use-websocket";
import { useChatStore } from "@/stores";
import type { ChatMessage, ChatAttachment, ToolCall, WSEvent } from "@/types";
import { WS_URL } from "@/lib/constants";
import { useConversationStore } from "@/stores";

interface UseChatOptions {
  conversationId?: string | null;
  onConversationCreated?: (conversationId: string) => void;
}

/**
 * Attachment payload format sent to WebSocket.
 * Matches backend AttachmentInMessage schema.
 */
interface AttachmentPayload {
  s3_key: string;
  mime_type: string;
  size_bytes: number;
  filename?: string;
}

export function useChat(options: UseChatOptions = {}) {
  const { conversationId, onConversationCreated } = options;
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
  const [currentMessageId, setCurrentMessageId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/auth/token")
      .then((res) => {
        if (res.ok) return res.json();
        return null;
      })
      .then((data) => {
        if (data?.access_token) {
          setToken(data.access_token);
        }
      })
      .catch(() => {
        // Ignore error
      });
  }, []);

  const handleWebSocketMessage = useCallback(
    (event: MessageEvent) => {
      const wsEvent: WSEvent = JSON.parse(event.data);

      switch (wsEvent.type) {
        case "conversation_created": {
          // Handle new conversation created by backend
          const { conversation_id } = wsEvent.data as { conversation_id: string };
          setCurrentConversationId(conversation_id);
          onConversationCreated?.(conversation_id);
          break;
        }

        case "message_saved": {
          // Message was saved to database, update local ID if needed
          // We don't need to do anything special here for now
          break;
        }

        case "model_request_start": {
          // Create new assistant message placeholder
          const newMsgId = nanoid();
          setCurrentMessageId(newMsgId);
          addMessage({
            id: newMsgId,
            role: "assistant",
            content: "",
            timestamp: new Date(),
            isStreaming: true,
            toolCalls: [],
          });
          break;
        }

        case "text_delta": {
          // Append text delta to current message
          if (currentMessageId) {
            const content = (wsEvent.data as { index: number; content: string }).content;
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              content: msg.content + content,
            }));
          }
          break;
        }

        case "tool_call": {
          // Add tool call to current message
          if (currentMessageId) {
            const { tool_name, args, tool_call_id } = wsEvent.data as {
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
          // Update tool call with result
          if (currentMessageId) {
            const { tool_call_id, content } = wsEvent.data as {
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
          // Finalize message
          if (currentMessageId) {
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              isStreaming: false,
            }));
          }
          setIsProcessing(false);
          setCurrentMessageId(null);
          break;
        }

        case "error": {
          // Handle error
          if (currentMessageId) {
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              content: msg.content + "\n\n[Error occurred]",
              isStreaming: false,
            }));
          }
          setIsProcessing(false);
          break;
        }

        case "complete": {
          setIsProcessing(false);
          break;
        }
      }
    },
    [currentMessageId, addMessage, updateMessage, addToolCall, updateToolCall, setCurrentConversationId, onConversationCreated]
  );

  const handleWebSocketClose = useCallback((event: CloseEvent) => {
    if (event.code === 4001) {
      console.error("WebSocket authentication failed");
    }
  }, []);

  const wsUrl = token 
    ? `${WS_URL}/api/v1/ws/agent?token=${token}` 
    : null;

  const { isConnected, connect, disconnect, sendMessage } = useWebSocket({
    url: wsUrl,
    onMessage: handleWebSocketMessage,
    onClose: handleWebSocketClose,
  });

  const sendChatMessage = useCallback(
    (content: string, attachments?: ChatAttachment[], systemPrompt?: string) => {
      // Only include uploaded attachments
      const uploadedAttachments = attachments?.filter(a => a.status === "uploaded") || [];

      // Add user message with attachments
      const userMessage: ChatMessage = {
        id: nanoid(),
        role: "user",
        content,
        timestamp: new Date(),
        attachments: uploadedAttachments.length > 0 ? uploadedAttachments : undefined,
      };
      addMessage(userMessage);

      // Build attachment payload for WebSocket (convert to snake_case)
      const attachmentPayloads: AttachmentPayload[] = uploadedAttachments.map(a => ({
        s3_key: a.s3Key,
        mime_type: a.mimeType,
        size_bytes: a.sizeBytes,
        filename: a.filename,
      }));

      // Send to WebSocket
      setIsProcessing(true);
      sendMessage({
        message: content,
        conversation_id: conversationId || null,
        system_prompt: systemPrompt,
        attachments: attachmentPayloads.length > 0 ? attachmentPayloads : undefined,
      });
    },
    [addMessage, sendMessage, conversationId]
  );

  return {
    messages,
    isConnected,
    isProcessing,
    connect,
    disconnect,
    sendMessage: sendChatMessage,
    clearMessages,
  };
}
