import { create } from "zustand";
import { persist } from "zustand/middleware";

// Avatar URL has no backend column — client-side only, not synced
// across devices. `phone`/`address` used to live here too (the old
// standalone Settings page's "Account Settings" card) but that card
// was removed outright — those fields, along with everything else the
// Profile page displays/edits, are real `users` table columns now
// (see shared_models.models.User) — see root CLAUDE.md's Profile
// module section.
export interface ProfileExtras {
  avatarUrl: string;
}

interface ProfileExtrasState extends ProfileExtras {
  setProfileExtras: (extras: Partial<ProfileExtras>) => void;
}

export const useProfileExtrasStore = create<ProfileExtrasState>()(
  persist(
    (set) => ({
      avatarUrl: "",
      setProfileExtras: (extras) => set((state) => ({ ...state, ...extras })),
    }),
    { name: "profile-extras-storage" }
  )
);
