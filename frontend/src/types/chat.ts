/**
 * Chat and AI Agent types.
 */

export type MessageRole = "user" | "assistant" | "system";

/**
 * Supported image MIME types for chat attachments.
 * Must match backend ALLOWED_IMAGE_MIME_TYPES.
 */
export const ALLOWED_IMAGE_MIME_TYPES = [
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/heic",
  "image/heif",
] as const;

export type AllowedImageMimeType = (typeof ALLOWED_IMAGE_MIME_TYPES)[number];

/**
 * Maximum total attachment size in bytes (20MB).
 * Must match backend MAX_TOTAL_ATTACHMENT_SIZE_BYTES.
 */
export const MAX_TOTAL_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024;

/**
 * Attachment for a chat message (image).
 */
export interface ChatAttachment {
  /** S3 object key (without user prefix) */
  s3Key: string;
  /** MIME type of the attachment */
  mimeType: AllowedImageMimeType;
  /** File size in bytes */
  sizeBytes: number;
  /** Original filename (optional) */
  filename?: string;
  /** Local preview URL for display before/after upload */
  previewUrl?: string;
  /** Upload status */
  status: "pending" | "uploading" | "uploaded" | "error";
  /** Error message if status is "error" */
  errorMessage?: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
  isStreaming?: boolean;
  /** Attachments (images) included with this message */
  attachments?: ChatAttachment[];
  /** Model's thinking/reasoning content (for models with thinking mode) */
  thinkingContent?: string;
  /** Whether thinking content is currently streaming */
  isThinkingStreaming?: boolean;
}

// Tool result content parts - can be text or images
export interface ToolContentText {
  type: "text";
  text: string;
}

export interface ToolContentImage {
  type: "image";
  media_type: string;
  data: string; // base64 encoded
}

export type ToolContentPart = ToolContentText | ToolContentImage;

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: ToolContentPart[] | string | unknown;
  status: "pending" | "running" | "completed" | "error";
}

// WebSocket event types from backend
export type WSEventType =
  | "user_prompt"
  | "user_prompt_processed"
  | "model_request_start"
  | "part_start"
  | "text_delta"
  | "thinking_delta"
  | "tool_call_delta"
  | "call_tools_start"
  | "tool_call"
  | "tool_result"
  | "final_result_start"
  | "final_result"
  | "complete"
  | "error"
  | "conversation_created"
  | "conversation_updated"
  | "message_saved";

export interface WSEvent {
  type: WSEventType;
  data?: unknown;
  timestamp?: string;
}

export interface TextDeltaEvent {
  type: "text_delta";
  data: {
    delta: string;
  };
}

export interface ToolCallEvent {
  type: "tool_call";
  data: {
    tool_name: string;
    args: Record<string, unknown>;
  };
}

export interface ToolResultEvent {
  type: "tool_result";
  data: {
    tool_name: string;
    result: unknown;
  };
}

export interface FinalResultEvent {
  type: "final_result";
  data: {
    output: string;
    tool_events: ToolCall[];
  };
}

export interface ChatState {
  messages: ChatMessage[];
  isConnected: boolean;
  isProcessing: boolean;
}
