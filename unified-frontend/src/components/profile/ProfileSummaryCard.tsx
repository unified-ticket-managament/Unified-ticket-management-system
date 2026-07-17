"use client";

import { Calendar, Mail, MapPin, Phone } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn, formatDate } from "@/lib/utils";
import { AuthUser, User } from "@/types";

interface ProfileSummaryCardProps {
  user: AuthUser | null;
  record?: User;
  avatarUrl: string;
  phone: string;
  officeLocation: string;
  departmentName: string | null;
  teamName: string | null;
  reportsToName: string | null;
  joinedDate: string | null;
}

export function ProfileSummaryCard({
  user,
  record,
  avatarUrl,
  phone,
  officeLocation,
  departmentName,
  teamName,
  reportsToName,
  joinedDate,
}: ProfileSummaryCardProps) {
  const rightFields = [
    { label: "Role", value: user?.role ?? "—" },
    { label: "Department", value: departmentName ?? "Not set" },
    { label: "Team", value: teamName ?? "Not set" },
    { label: "Reports To", value: reportsToName ?? "Not set" },
  ];

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardContent className="flex flex-col gap-6 p-6 lg:flex-row lg:items-center lg:justify-between">
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
                record?.is_active ?? true ? "bg-success" : "bg-muted-foreground"
              )}
              aria-label={record?.is_active ?? true ? "Online" : "Offline"}
              title={record?.is_active ?? true ? "Active" : "Inactive"}
            />
          </div>

          <div className="min-w-0 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xl font-semibold leading-tight">{user?.name ?? "—"}</p>
              <Badge>{user?.role ?? "—"}</Badge>
            </div>

            <div className="flex flex-col gap-1 text-sm text-muted-foreground sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:gap-y-1">
              <span className="flex items-center gap-1.5">
                <Mail className="h-3.5 w-3.5" />
                {user?.email ?? "—"}
              </span>
              <span className="flex items-center gap-1.5">
                <Phone className="h-3.5 w-3.5" />
                {phone || "Not set"}
              </span>
              <span className="flex items-center gap-1.5">
                <MapPin className="h-3.5 w-3.5" />
                {officeLocation || "Not set"}
              </span>
              <span className="flex items-center gap-1.5">
                <Calendar className="h-3.5 w-3.5" />
                Joined {joinedDate ? formatDate(joinedDate) : "—"}
              </span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-x-8 gap-y-3 border-t border-border pt-4 sm:grid-cols-4 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
          {rightFields.map((field) => (
            <div key={field.label}>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {field.label}
              </p>
              <p className="mt-0.5 text-sm font-semibold">{field.value}</p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
