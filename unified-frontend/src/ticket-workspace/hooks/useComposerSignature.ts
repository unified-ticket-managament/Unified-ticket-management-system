"use client";

import { type MutableRefObject, useCallback, useEffect, useMemo, useRef } from "react";

import type { EmailSignatureList } from "@/types";
import {
  buildSignatureBlockHtml,
  composerSignatureOptions,
  findSignatureId,
  replaceSignatureBlock,
} from "@tw/lib/signatures";

/**
 * The block a brand-new composer should start with — the user's
 * default signature (or the legacy fallback when they have none saved)
 * — or null when there is nothing to insert or signatures haven't
 * loaded yet (useComposerSignature then inserts it once they have).
 */
export function initialSignatureBlockHtml(list: EmailSignatureList | undefined): string | null {
  const { initial } = composerSignatureOptions(list);
  return initial ? buildSignatureBlockHtml(initial, list?.image_urls ?? {}) : null;
}

// No text and no image — nothing the user typed yet.
function isBlank(html: string): boolean {
  if (/<img\b/i.test(html)) return false;
  return html.replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").trim() === "";
}

interface UseComposerSignatureParams {
  signatures: EmailSignatureList | undefined;
  bodyHtml: string;
  setBodyHtml: (html: string) => void;
  /**
   * True only for a genuinely new composer session. A reopened draft
   * never gets a signature injected — its saved HTML (including a
   * signature the user picked, or deliberately removed) is
   * authoritative.
   */
  autoInsert: boolean;
  /**
   * For a composer that stays mounted across sessions (TicketComposer
   * switching tickets): a new key re-arms the one-time auto-insert.
   */
  autoInsertKey?: string | null;
  /**
   * The composer's own "untouched body" baseline (its initial-body ref).
   * While the body still equals it, a signature inserted/swapped here
   * moves the baseline along with it, so a signature-only body keeps
   * counting as empty (no Send, no phantom draft auto-save).
   */
  baselineRef: MutableRefObject<string | null>;
}

/**
 * Per-composer signature selection. The selected signature is read
 * straight from the managed block in the body itself (findSignatureId)
 * — so it is saved and restored with a draft for free — and changing
 * it rewrites only that block. Nothing here ever changes the user's
 * permanent default; that is Settings' "Set as default" alone.
 */
export function useComposerSignature({
  signatures,
  bodyHtml,
  setBodyHtml,
  autoInsert,
  autoInsertKey = null,
  baselineRef,
}: UseComposerSignatureParams) {
  const { options, initial, hasSavedSignatures } = useMemo(
    () => composerSignatureOptions(signatures),
    [signatures]
  );
  const selectedId = useMemo(() => findSignatureId(bodyHtml), [bodyHtml]);

  const imageUrls = signatures?.image_urls;

  const applyBlock = useCallback(
    (blockHtml: string | null) => {
      const next = replaceSignatureBlock(bodyHtml, blockHtml);
      if (next === bodyHtml) return;
      if (bodyHtml === baselineRef.current || isBlank(bodyHtml)) baselineRef.current = next;
      setBodyHtml(next);
    },
    [bodyHtml, baselineRef, setBodyHtml]
  );

  const selectSignature = useCallback(
    (signatureId: string | null) => {
      const option = signatureId ? options.find((o) => o.id === signatureId) : null;
      applyBlock(option ? buildSignatureBlockHtml(option, imageUrls ?? {}) : null);
    },
    [applyBlock, options, imageUrls]
  );

  // Late arrival: a new composer opened before the (normally cached)
  // signatures query resolved gets its default inserted once, as soon
  // as they load — and only if the body has no signature block yet.
  const autoInsertDoneRef = useRef(false);
  const autoInsertKeyRef = useRef(autoInsertKey);
  useEffect(() => {
    if (autoInsertKeyRef.current !== autoInsertKey) {
      autoInsertKeyRef.current = autoInsertKey;
      autoInsertDoneRef.current = false;
    }
    if (!autoInsert || autoInsertDoneRef.current || !signatures) return;
    autoInsertDoneRef.current = true;
    if (!initial || findSignatureId(bodyHtml)) return;
    applyBlock(buildSignatureBlockHtml(initial, imageUrls ?? {}));
  }, [autoInsert, autoInsertKey, signatures, initial, applyBlock, bodyHtml, imageUrls]);

  return { options, selectedId, hasSavedSignatures, selectSignature };
}
