"use client";

import { Calendar, Mail, MapPin, Phone } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";
import { useTranslation } from "@/hooks/use-translation";
import { cn, formatDate } from "@/lib/utils";
import { AuthUser, User } from "@/types";

interface ProfileSummaryCardProps {
  user: AuthUser | null;
  record?: User;
  avatarUrl: string;
  phone: string;
  officeLocation: string;
  joinedDate: string | null;
}

// Header card, deliberately narrow: avatar, name, email, phone, office
// location, joined date only. Role/Department/Team/Reports To used to
// render here too — removed per the Profile-page simplification pass
// (see root CLAUDE.md) since they're redundant with the Personal
// Details section of ProfileInformationCard just below, which still
// shows all four.
export function ProfileSummaryCard({
  user,
  record,
  avatarUrl,
  phone,
  officeLocation,
  joinedDate,
}: ProfileSummaryCardProps) {
  const { t } = useTranslation();
  const isActive = record?.is_active ?? true;

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardContent className="flex items-center gap-4 p-6">
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
      </CardContent>
    </Card>
  );
}
