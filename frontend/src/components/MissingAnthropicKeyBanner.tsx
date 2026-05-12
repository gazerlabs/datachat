import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

import { api, ApiError, AnthropicKeyStatus } from "@/lib/api";

/**
 * Sits at the top of the chat page until an Anthropic key is configured
 * somewhere (DB-stored or env var). Admin-only — the underlying endpoint
 * 403s for non-admins, who can't fix this anyway. The chat handler will
 * still surface a friendly inline message if a non-admin hits send.
 */
export function MissingAnthropicKeyBanner() {
  const { data, isError, error } = useQuery<AnthropicKeyStatus>({
    queryKey: ["anthropic-key-status"],
    queryFn: api.getAnthropicKeyStatus,
    retry: false,
    staleTime: 30_000,
  });

  const isForbidden = isError && error instanceof ApiError && error.status === 403;
  if (isForbidden) return null;
  if (!data || data.effective) return null;

  return (
    <div className="border-b border-destructive/40 bg-destructive/10">
      <div className="container mx-auto px-4 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 text-sm">
          <AlertTriangle className="h-4 w-4 text-destructive shrink-0" />
          <span>
            No Anthropic API key configured. Chat will fail until one is set.
          </span>
        </div>
        <Link
          to="/settings"
          className="text-sm font-medium underline shrink-0"
        >
          Configure in Settings
        </Link>
      </div>
    </div>
  );
}
