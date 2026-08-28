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
  // Main sidebar's user-chosen width (px) — device-local, persisted
  // the same way language/security are, survives navigation/refresh/
  // logout-login on this browser. See components/layout/sidebar.tsx.
  sidebarWidth: number;
  // Mail Inbox's Message-List/Message-Details divider width (px) — same
  // persistence convention as sidebarWidth. null means "never dragged
  // yet": unlike the sidebar, this panel has no single fixed default,
  // it's computed from a ratio against the workspace's measured width.
  // The OTHER divider in that same workspace (folders | list) is
  // deliberately not persisted here. See MailWorkspaceLayout.tsx.
  mailMessageListWidth: number | null;
  // Mail Inbox message-list pagination page size — device-local,
  // same persistence convention as the two fields above. See
  // MessageList.tsx's PAGE_SIZE_OPTIONS (the only valid values).
  mailMessagesPerPage: number;
  setLanguage: (language: Language) => void;
  setSecurity: (key: keyof SecurityPreferences, value: boolean) => void;
  setSidebarWidth: (width: number) => void;
  setMailMessageListWidth: (width: number) => void;
  setMailMessagesPerPage: (pageSize: number) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      language: "en",
      security: {
        twoFactorEnabled: false,
        loginAlerts: true,
      },
      sidebarWidth: 256,
      mailMessageListWidth: null,
      mailMessagesPerPage: 50,
      setLanguage: (language) => set({ language }),
      setSecurity: (key, value) =>
        set((state) => ({
          security: { ...state.security, [key]: value },
        })),
      setSidebarWidth: (sidebarWidth) => set({ sidebarWidth }),
      setMailMessageListWidth: (mailMessageListWidth) => set({ mailMessageListWidth }),
      setMailMessagesPerPage: (mailMessagesPerPage) => set({ mailMessagesPerPage }),
    }),
    { name: "settings-storage" }
  )
);
