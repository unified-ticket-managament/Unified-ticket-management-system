"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { signatureService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import type { EmailSignatureList } from "@/types";

export const EMAIL_SIGNATURES_QUERY_KEY = "email-signatures";

// Preview URLs in the response are presigned for 60 minutes (backend
// storage_url_expiry_seconds) — refresh well inside that window, but
// otherwise serve every composer (Reply, Reply All, Forward, Compose,
// Ticket Reply) from this one cached query instead of refetching on
// each click.
const STALE_TIME_MS = 10 * 60 * 1000;

// Keyed by the effective user id, so starting/ending impersonation
// (which swaps the auth store's user) reads the right account's
// signatures without any manual invalidation.
export function useEmailSignatures() {
  const userId = useAuthStore((s) => s.user?.user_id);

  return useQuery<EmailSignatureList>({
    queryKey: [EMAIL_SIGNATURES_QUERY_KEY, userId],
    queryFn: () => signatureService.list(),
    enabled: !!userId,
    staleTime: STALE_TIME_MS,
  });
}

export function useInvalidateEmailSignatures() {
  const queryClient = useQueryClient();
  return useCallback(
    () => queryClient.invalidateQueries({ queryKey: [EMAIL_SIGNATURES_QUERY_KEY] }),
    [queryClient]
  );
}
