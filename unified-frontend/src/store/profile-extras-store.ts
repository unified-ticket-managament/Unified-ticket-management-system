import { create } from "zustand";
import { persist } from "zustand/middleware";

// Fields with no backend column (see unified-frontend/CLAUDE.md's store
// notes) — client-side only, not synced across devices. phone/address/
// avatarUrl are the original set; the rest were added for the redesigned
// Profile page's Personal/Contact/Preferences cards, which the backend
// User model has no equivalent columns for.
export interface ProfileExtras {
  phone: string;
  address: string;
  avatarUrl: string;
  employeeId: string;
  dateOfBirth: string;
  timezone: string;
  alternateEmail: string;
  dateFormat: string;
  timeFormat: string;
  defaultDashboard: string;
}

interface ProfileExtrasState extends ProfileExtras {
  setProfileExtras: (extras: Partial<ProfileExtras>) => void;
}

export const useProfileExtrasStore = create<ProfileExtrasState>()(
  persist(
    (set) => ({
      phone: "",
      address: "",
      avatarUrl: "",
      employeeId: "",
      dateOfBirth: "",
      timezone: "",
      alternateEmail: "",
      dateFormat: "MM/DD/YYYY",
      timeFormat: "12h",
      defaultDashboard: "Dashboard",
      setProfileExtras: (extras) => set((state) => ({ ...state, ...extras })),
    }),
    { name: "profile-extras-storage" }
  )
);
