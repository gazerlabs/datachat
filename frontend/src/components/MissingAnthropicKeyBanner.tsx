import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

import { api, ApiError, AnthropicKeyStatus } from "@/lib/api";

/**
 * Sits just under the chat-page header until an Anthropic key is configured
 * somewhere (DB-stored or env var). Centered floating card rather than a
 * full-width strip so it doesn't look like a permanent shipping warning.
 *
 * Admin-only — the underlying endpoint 403s for non-admins, who can't fix
 * this anyway. The chat handler will still surface a friendly inline error
 * if a non-admin hits send.
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
    <div className="flex justify-center pt-4 px-4">
      <div className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 max-w-xl text-sm shadow-sm">
        <AlertTriangle className="h-4 w-4 mt-0.5 text-destructive shrink-0" />
        <div className="space-y-1">
          <p>No Anthropic API key configured. Chat will fail until one is set.</p>
          <Link to="/settings" className="font-medium underline">
            Configure in Settings
          </Link>
        </div>
      </div>
    </div>
  );
}
