"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, Mail, MapPin, Phone } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { PROFILE_RECORD_QUERY_KEY } from "@/hooks/use-profile";
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { cn, formatDate } from "@/lib/utils";
import { authService } from "@/services";
import { AuthUser, User } from "@/types";

interface ProfileSummaryCardProps {
  user: AuthUser | null;
  record?: User;
  avatarUrl: string;
  phone: string;
  officeLocation: string;
  joinedDate: string | null;
}

// Header card, deliberately narrow: avatar, name, designation, email,
// phone, office location, joined date only. Role/Department/Team/
// Reports To render in the Personal Details section of
// ProfileInformationCard just below instead, which still shows all
// four — the subtitle directly under the name shows the user's real-
// world Designation (e.g. "Sr. AR Associate"), not their RBAC Role,
// since Role is already visible there. `designation` has no edit
// surface of its own (same as `team`) — it's sourced from the org
// import, display only.
export function ProfileSummaryCard({
  user,
  record,
  avatarUrl,
  phone,
  officeLocation,
  joinedDate,
}: ProfileSummaryCardProps) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const isActive = record?.is_active ?? true;
  const designation = record?.designation ?? user?.designation;

  // Local, optimistic mirror of record.is_on_leave — re-synced whenever
  // the underlying profile record (re)loads, same pattern the admin
  // drawer's own Leave toggle used before this control moved here.
  const [isOnLeave, setIsOnLeave] = useState(record?.is_on_leave ?? false);
  useEffect(() => {
    setIsOnLeave(record?.is_on_leave ?? false);
  }, [record?.is_on_leave]);

  const leaveMutation = useMutation({
    mutationFn: (nextIsOnLeave: boolean) =>
      authService.updateProfile({ is_on_leave: nextIsOnLeave }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PROFILE_RECORD_QUERY_KEY] });
    },
    onError: (_error, nextIsOnLeave) => {
      setIsOnLeave(!nextIsOnLeave);
      toast({ variant: "destructive", title: t("profile.toastUpdateFailedTitle") });
    },
  });

  function handleLeaveToggle(checked: boolean) {
    setIsOnLeave(checked);
    leaveMutation.mutate(checked);
  }

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardContent className="flex items-start justify-between gap-4 p-6">
        <div className="flex items-center gap-4">
          <div className="relative shrink-0">
            <Avatar className="h-20 w-20">
              {avatarUrl && <AvatarImage src={avatarUrl} alt={user?.name ?? "Avatar"} />}
              <AvatarFallback className="text-2xl">
                {user?.name?.charAt(0).toUpperCase() ?? "U"}
              </AvatarFallback>
            </Avatar>
            <span
              className={cn(
                "absolute bottom-1 right-1 h-3.5 w-3.5 rounded-full border-2 border-card",
                isActive ? "bg-success" : "bg-muted-foreground"
              )}
              aria-label={isActive ? t("profile.statusOnline") : t("profile.statusOffline")}
              title={isActive ? t("profile.statusActive") : t("profile.statusInactive")}
            />
          </div>

          <div className="min-w-0 space-y-1.5">
            <p className="text-xl font-semibold leading-tight">{user?.name ?? "—"}</p>
            <p className="text-sm text-muted-foreground">{designation || t("profile.notSet")}</p>

            <div className="flex flex-col gap-1 text-sm text-muted-foreground sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:gap-y-1">
              <span className="flex items-center gap-1.5">
                <Mail className="h-3.5 w-3.5" />
                {user?.email ?? "—"}
              </span>
              <span className="flex items-center gap-1.5">
                <Phone className="h-3.5 w-3.5" />
                {phone || t("profile.notSet")}
              </span>
              <span className="flex items-center gap-1.5">
                <MapPin className="h-3.5 w-3.5" />
                {officeLocation || t("profile.notSet")}
              </span>
              <span className="flex items-center gap-1.5">
                <Calendar className="h-3.5 w-3.5" />
                {t("profile.joined")} {joinedDate ? formatDate(joinedDate) : "—"}
              </span>
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">{t("profile.leave")}</span>
          <Switch
            checked={isOnLeave}
            onCheckedChange={handleLeaveToggle}
            disabled={leaveMutation.isPending}
            aria-label="Toggle leave status"
          />
        </div>
      </CardContent>
    </Card>
  );
}
