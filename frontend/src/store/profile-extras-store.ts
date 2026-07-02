import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface ProfileExtras {
  phone: string;
  address: string;
  avatarUrl: string;
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
      setProfileExtras: (extras) => set((state) => ({ ...state, ...extras })),
    }),
    { name: "profile-extras-storage" }
  )
);
