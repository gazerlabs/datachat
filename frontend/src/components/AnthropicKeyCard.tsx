import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Eye, EyeOff } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError, AnthropicKeyStatus } from "@/lib/api";

function formatSetDate(iso: string): string {
  // Renders e.g. "May 11, 2026" using the browser's locale, falling back to
  // the raw ISO timestamp if Date can't parse it (shouldn't happen — the
  // backend hands us an isoformat() string).
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * In-app Anthropic key configuration. Lives on the Settings page so a
 * self-hoster can paste their key without editing .env. Admin-only behind the
 * scenes; we render an unconfigured banner that links here from the chat page
 * when the backend reports no effective key.
 *
 * The full key never round-trips. Backend returns a masked preview and a
 * `source` field so we can show whether the active key is admin-set (DB) or
 * coming from the deployment's env var.
 */
export function AnthropicKeyCard() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [reveal, setReveal] = useState(false);

  const { data: status, isLoading, isError, error } = useQuery<AnthropicKeyStatus>({
    queryKey: ["anthropic-key-status"],
    queryFn: api.getAnthropicKeyStatus,
    retry: false,
  });

  const isForbidden = isError && error instanceof ApiError && error.status === 403;

  const save = useMutation({
    mutationFn: (key: string) => api.setAnthropicKey(key),
    onSuccess: (s) => {
      queryClient.setQueryData(["anthropic-key-status"], s);
      setDraft("");
      toast.success("Anthropic key saved");
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : "Failed to save key";
      toast.error(msg);
    },
  });

  const remove = useMutation({
    mutationFn: api.deleteAnthropicKey,
    onSuccess: (s) => {
      queryClient.setQueryData(["anthropic-key-status"], s);
      toast.success("Anthropic key removed");
    },
  });

  // Non-admins can't view or change this — the card is hidden for them rather
  // than rendered with a permission error.
  if (isForbidden) return null;

  return (
    <Card className="mb-8">
      <CardHeader>
        <CardTitle>Anthropic API Key</CardTitle>
        <CardDescription>
          Your{" "}
          <a
            href="https://console.anthropic.com/settings/keys"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            Anthropic API key
          </a>{" "}
          powers every chat.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading status…</p>
        ) : (
          <>
            <div className="text-sm">
              {status?.effective ? (
                <span>
                  <span className="text-muted-foreground">Active key:</span>{" "}
                  <code className="px-1.5 py-0.5 rounded bg-muted text-xs">
                    {status.masked}
                  </code>{" "}
                  <span className="text-muted-foreground">
                    ({status.source === "database" && status.updated_at
                      ? `set on ${formatSetDate(status.updated_at)}`
                      : status.source === "database"
                        ? "set in Settings"
                        : "from ANTHROPIC_API_KEY env var"})
                  </span>
                </span>
              ) : (
                <span className="text-destructive">
                  No Anthropic key configured. Chat will fail until one is set.
                </span>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="anthropic-key">
                {status?.configured ? "Replace key" : "Set key"}
              </Label>
              <div className="flex gap-2">
                <Input
                  id="anthropic-key"
                  type={reveal ? "text" : "password"}
                  placeholder="sk-ant-api03-..."
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  className="font-mono text-sm"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setReveal((r) => !r)}
                  aria-label={reveal ? "Hide key" : "Show key"}
                >
                  {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={() => save.mutate(draft.trim())}
                  disabled={!draft.trim() || save.isPending}
                >
                  {save.isPending ? "Validating…" : "Save"}
                </Button>
                {status?.configured && (
                  <Button
                    variant="outline"
                    onClick={() => remove.mutate()}
                    disabled={remove.isPending}
                  >
                    {remove.isPending ? "Removing…" : "Remove"}
                  </Button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Keys are validated against Anthropic before saving and stored
                encrypted on the server. Replace any time — the new key takes
                effect on the next chat message.
              </p>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
