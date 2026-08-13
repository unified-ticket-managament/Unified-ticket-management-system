import { create } from "zustand";
import { persist } from "zustand/middleware";

import { Language } from "@/lib/i18n/translations";

export interface SecurityPreferences {
  twoFactorEnabled: boolean;
  loginAlerts: boolean;
}

interface SettingsState {
  language: Language;
  security: SecurityPreferences;
  setLanguage: (language: Language) => void;
  setSecurity: (key: keyof SecurityPreferences, value: boolean) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      language: "en",
      security: {
        twoFactorEnabled: false,
        loginAlerts: true,
      },
      setLanguage: (language) => set({ language }),
      setSecurity: (key, value) =>
        set((state) => ({
          security: { ...state.security, [key]: value },
        })),
    }),
    { name: "settings-storage" }
  )
);
