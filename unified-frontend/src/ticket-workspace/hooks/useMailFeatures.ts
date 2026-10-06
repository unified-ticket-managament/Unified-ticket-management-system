import { useEffect, useState } from "react";

import { getMailFeatures } from "@tw/api/inbox";
import type { MailFeatures } from "@tw/types";

// Everything off until the backend says otherwise: a failed or pending
// lookup must never show a feature the backend hasn't enabled.
const DEFAULT_FEATURES: MailFeatures = { read_receipts_enabled: false };

// One lookup per page load, shared by every consumer (the composers are
// opened/closed constantly, and a feature switch only changes on a
// backend restart). Only a successful answer is cached, so a transient
// failure is retried the next time a consumer mounts.
let cachedFeatures: MailFeatures | null = null;
let inFlight: Promise<MailFeatures> | null = null;
const listeners = new Set<(features: MailFeatures) => void>();

// Record a feature state we have just learned elsewhere (e.g. the Settings
// card after an administrator toggles Read Receipts), so every mounted
// consumer — an open composer included — updates immediately instead of
// waiting for a page reload.
export function setMailFeatures(features: MailFeatures): void {
  const next: MailFeatures = { read_receipts_enabled: features.read_receipts_enabled === true };
  cachedFeatures = next;
  listeners.forEach((listener) => listener(next));
}

async function loadMailFeatures(): Promise<MailFeatures> {
  if (cachedFeatures) return cachedFeatures;
  if (!inFlight) {
    inFlight = (async () => {
      try {
        const features = await getMailFeatures();
        cachedFeatures = {
          read_receipts_enabled: features?.read_receipts_enabled === true,
        };
        return cachedFeatures;
      } catch {
        // A missing/failed lookup (including a test double that does not
        // define the call) leaves every optional feature off.
        return DEFAULT_FEATURES;
      } finally {
        inFlight = null;
      }
    })();
  }
  return inFlight;
}

// Which optional Mail features the backend has switched on. Mirrors the
// backend setting (the single source of truth); there is no separate
// frontend flag to keep in sync. Defaults to everything off.
export function useMailFeatures(): MailFeatures {
  const [features, setFeatures] = useState<MailFeatures>(cachedFeatures ?? DEFAULT_FEATURES);

  useEffect(() => {
    listeners.add(setFeatures);
    let cancelled = false;
    if (cachedFeatures) {
      setFeatures(cachedFeatures);
    } else {
      void loadMailFeatures().then((loaded) => {
        if (!cancelled) setFeatures(loaded);
      });
    }
    return () => {
      cancelled = true;
      listeners.delete(setFeatures);
    };
  }, []);

  return features;
}

// Test hook: forget the cached answer between tests.
export function resetMailFeaturesCacheForTests(): void {
  cachedFeatures = null;
  inFlight = null;
  listeners.clear();
}
