
"use client";

import { useCallback, useRef } from "react";
import { apiClient } from "@/lib/api-client";
import { useConversationStore, useChatStore } from "@/stores";
import type {
  Conversation,
  ConversationMessage,
  ConversationListResponse,
} from "@/types";

interface CreateConversationResponse {
  id: string;
  title?: string;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
}

interface MessagesResponse {
  items: ConversationMessage[];
  total: number;
}

export function useConversations() {
  const {
    conversations,
    currentConversationId,
    currentMessages,
    isLoading,
    error,
    setConversations,
    addConversation,
    updateConversation,
    removeConversation,
    setCurrentConversationId,
    setCurrentMessages,
    setLoading,
    setError,
  } = useConversationStore();
  const { clearMessages } = useChatStore();

  const fetchConversations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.get<ConversationListResponse>(
        "/conversations"
      );
      setConversations(response.items);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch conversations";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [setConversations, setLoading, setError]);

  const createConversation = useCallback(
    async (title?: string): Promise<Conversation | null> => {
      setLoading(true);
      setError(null);
      try {
        const response = await apiClient.post<CreateConversationResponse>(
          "/conversations",
          { title }
        );
        const newConversation: Conversation = {
          id: response.id,
          title: response.title,
          created_at: response.created_at,
          updated_at: response.updated_at,
          is_archived: response.is_archived,
        };
        addConversation(newConversation);
        return newConversation;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to create conversation";
        setError(message);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [addConversation, setLoading, setError]
  );

  const selectConversation = useCallback(
    async (id: string) => {
      setCurrentConversationId(id);
      clearMessages();
      setLoading(true);
      setError(null);
      try {
        const response = await apiClient.get<MessagesResponse>(
          `/conversations/${id}/messages`
        );
        setCurrentMessages(response.items);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to fetch messages";
        setError(message);
      } finally {
        setLoading(false);
      }
    },
    [setCurrentConversationId, clearMessages, setCurrentMessages, setLoading, setError]
  );

  const archiveConversation = useCallback(
    async (id: string) => {
      try {
        await apiClient.patch(`/conversations/${id}`, { is_archived: true });
        updateConversation(id, { is_archived: true });
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to archive conversation";
        setError(message);
      }
    },
    [updateConversation, setError]
  );

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await apiClient.delete(`/conversations/${id}`);
        removeConversation(id);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to delete conversation";
        setError(message);
      }
    },
    [removeConversation, setError]
  );

  const renameConversation = useCallback(
    async (id: string, title: string) => {
      try {
        await apiClient.patch(`/conversations/${id}`, { title });
        updateConversation(id, { title });
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to rename conversation";
        setError(message);
      }
    },
    [updateConversation, setError]
  );

  const updateConversationDetails = useCallback(
    async (id: string, updates: Partial<Conversation>) => {
      try {
        const response = await apiClient.patch<Conversation>(`/conversations/${id}`, updates);
        updateConversation(id, updates);
        return response;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to update conversation";
        setError(message);
        throw err;
      }
    },
    [updateConversation, setError]
  );

  const creatingRef = useRef<Promise<string | null> | null>(null);

  const ensureConversation = useCallback(async (): Promise<string | null> => {
    const currentId = useConversationStore.getState().currentConversationId;
    if (currentId) return currentId;
    if (creatingRef.current) return creatingRef.current;

    creatingRef.current = (async () => {
      try {
        const conv = await createConversation();
        if (conv) {
          setCurrentConversationId(conv.id);
          return conv.id;
        }
        return null;
      } finally {
        creatingRef.current = null;
      }
    })();
    return creatingRef.current;
  }, [createConversation, setCurrentConversationId]);

  const startNewChat = useCallback(() => {
    clearMessages();
    setCurrentMessages([]);
    setCurrentConversationId(null);
  }, [clearMessages, setCurrentMessages, setCurrentConversationId]);

  return {
    conversations,
    currentConversationId,
    currentMessages,
    isLoading,
    error,
    fetchConversations,
    createConversation,
    selectConversation,
    archiveConversation,
    deleteConversation,
    renameConversation,
    updateConversationDetails,
    ensureConversation,
    startNewChat,
  };
}
