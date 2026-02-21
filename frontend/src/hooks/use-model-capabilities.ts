"use client";

import { useState, useEffect } from "react";
import { useAuthStore } from "@/stores";

type Modalities = {
  images: boolean;
  audio: boolean;
  video: boolean;
};

type ModelEntry = {
  id: string;
  modalities: Modalities;
};

// Default: all true — safe fallback when models list hasn't loaded yet
// or when the active model is unknown. Avoids hiding the UI unexpectedly.
const DEFAULT_MODALITIES: Modalities = { images: true, audio: true, video: true };

/**
 * Returns the modality capabilities of the current user's active model.
 *
 * Fetches the models list from /api/models once per session and cross-references
 * the user's default_model from the auth store.
 *
 * Falls back to all-true (permissive) if the fetch fails or the model is unknown.
 */
export function useModelCapabilities(): Modalities {
  const user = useAuthStore((state) => state.user);
  const [models, setModels] = useState<ModelEntry[]>([]);

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: ModelEntry[]) => setModels(data))
      .catch(() => setModels([]));
  }, []);

  if (!user?.default_model || models.length === 0) {
    return DEFAULT_MODALITIES;
  }

  const active = models.find((m) => m.id === user.default_model);
  return active?.modalities ?? DEFAULT_MODALITIES;
}
