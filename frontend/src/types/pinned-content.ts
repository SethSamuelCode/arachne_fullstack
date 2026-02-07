/**
 * Type definitions for pinned content feature
 * Enables pinning files to chat cache for 75% cost reduction via Gemini CachedContent API
 */

export interface PinContentRequest {
  /** Map of file paths to content (direct file upload) */
  files?: Record<string, string>;
  /** List of S3 file paths to pin */
  s3_paths?: string[];
  /** Map of file paths to MIME types */
  mime_types?: Record<string, string>;
  /** AI model name to use for cache */
  model_name?: string;
}

export type PinEventType = "progress" | "warning" | "error" | "complete";

export interface PinEvent {
  event: PinEventType;
  data: PinProgressEvent | PinWarningEvent | PinErrorEvent | PinCompleteEvent;
}

export type PinPhase =
  | "fetching"
  | "validating"
  | "hashing"
  | "serializing"
  | "estimating"
  | "uploading"
  | "creating"
  | "storing";

export interface PinProgressEvent {
  phase: PinPhase;
  current?: number;
  total?: number;
  message?: string;
  current_file?: string;
  currentFile?: string;
  percentage?: number;
  tokens?: number;
  content_hash?: string;
  status?: string;
  budget_used_pct?: number;
}

export type PinWarningType = "token_budget" | "budget" | "budget_exceeded" | "file_error" | "partial_failure";

export interface PinWarningEvent {
  type: PinWarningType;
  message: string;
  percent?: number;
  path?: string;
  details?: unknown;
}

export interface PinErrorEvent {
  code: string;
  message: string;
}

export interface PinCompleteEvent {
  content_hash: string;
  total_tokens: number;
  file_count: number;
  cache_name: string;
  budget_percent?: number;
  message?: string;
}

export interface PinnedContentInfo {
  content_hash: string;
  file_paths: string[];
  file_hashes: Record<string, string>;
  total_tokens: number;
  pinned_at: string;
}

export interface StalenessResponse {
  is_stale: boolean;
  changed_files: string[];
  added_files: string[];
  removed_files: string[];
  has_pinned_content: boolean;
}

/** Progress state for UI components */
export interface PinProgress {
  phase: PinPhase;
  current?: number;
  total?: number;
  message?: string;
  currentFile?: string;
  percentage?: number;
  tokens?: number;
  budgetUsedPercent?: number;
}
