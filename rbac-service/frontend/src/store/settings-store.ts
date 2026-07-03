import { create } from "zustand";
import { persist } from "zustand/middleware";

import { Language } from "@/lib/i18n/translations";

export interface NotificationPreferences {
  email: boolean;
  push: boolean;
  productUpdates: boolean;
  securityAlerts: boolean;
}

export interface SecurityPreferences {
  twoFactorEnabled: boolean;
  loginAlerts: boolean;
}

export interface SessionEntry {
  id: string;
  device: string;
  location: string;
  lastActive: string;
  current: boolean;
}

const INITIAL_SESSIONS: SessionEntry[] = [
  {
    id: "session-current",
    device: "This device — Chrome on Windows",
    location: "Detected from current connection",
    lastActive: "Active now",
    current: true,
  },
  {
    id: "session-2",
    device: "Safari on iPhone",
    location: "Last seen — Mumbai, India",
    lastActive: "2 hours ago",
    current: false,
  },
  {
    id: "session-3",
    device: "Chrome on macOS",
    location: "Last seen — Bengaluru, India",
    lastActive: "1 day ago",
    current: false,
  },
];

interface SettingsState {
  notifications: NotificationPreferences;
  language: Language;
  security: SecurityPreferences;
  sessions: SessionEntry[];
  setNotification: (key: keyof NotificationPreferences, value: boolean) => void;
  setLanguage: (language: Language) => void;
  setSecurity: (key: keyof SecurityPreferences, value: boolean) => void;
  revokeSession: (id: string) => void;
  revokeAllOtherSessions: () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      notifications: {
        email: true,
        push: true,
        productUpdates: false,
        securityAlerts: true,
      },
      language: "en",
      security: {
        twoFactorEnabled: false,
        loginAlerts: true,
      },
      sessions: INITIAL_SESSIONS,
      setNotification: (key, value) =>
        set((state) => ({
          notifications: { ...state.notifications, [key]: value },
        })),
      setLanguage: (language) => set({ language }),
      setSecurity: (key, value) =>
        set((state) => ({
          security: { ...state.security, [key]: value },
        })),
      revokeSession: (id) =>
        set((state) => ({
          sessions: state.sessions.filter((session) => session.id !== id),
        })),
      revokeAllOtherSessions: () =>
        set((state) => ({
          sessions: state.sessions.filter((session) => session.current),
        })),
    }),
    { name: "settings-storage" }
  )
);
