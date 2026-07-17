"use client";

import { useQuery } from "@tanstack/react-query";

import { userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { useProfileExtrasStore } from "@/store/profile-extras-store";
import { User } from "@/types";

export const PROFILE_RECORD_QUERY_KEY = "profile-full-record";

// Composes the data sources the (now single-card) Profile page needs:
// the RBAC user record and the resolved manager/teamlead name behind
// its read-only "Reports To" field.
export function useProfileData() {
  const user = useAuthStore((s) => s.user);
  const extras = useProfileExtrasStore();

  const userRecordQuery = useQuery({
    queryKey: [PROFILE_RECORD_QUERY_KEY, user?.user_id],
    queryFn: async () => (await userService.get(user!.user_id)) as User,
    enabled: !!user?.user_id,
  });
  const record = userRecordQuery.data;

  const managerQuery = useQuery({
    queryKey: ["profile-manager", record?.manager_id],
    queryFn: async () => (await userService.get(record!.manager_id as string)) as User,
    enabled: !!record?.manager_id,
  });

  const teamleadQuery = useQuery({
    queryKey: ["profile-teamlead", record?.teamlead_id],
    queryFn: async () => (await userService.get(record!.teamlead_id as string)) as User,
    enabled: !!record?.teamlead_id,
  });

  const reportsToName = managerQuery.data?.name ?? teamleadQuery.data?.name ?? null;

  return {
    user,
    record,
    extras,
    reportsToName,
    joinedDate: record?.created_at ?? null,
  };
}
