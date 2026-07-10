"use client";

import { useCallback } from "react";

import { Language, TranslationKey, translate } from "@/lib/i18n/translations";
import { useSettingsStore } from "@/store/settings-store";

export function useTranslation() {
  const language = useSettingsStore((s) => s.language);

  const t = useCallback(
    (key: TranslationKey, params?: Record<string, string | number>) =>
      translate(language, key, params),
    [language]
  );

  return { t, language };
}
