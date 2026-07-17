"use client";

import { UserRound } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/utils";

interface PersonalInfoCardProps {
  name: string | undefined;
  employeeId: string;
  dateOfBirth: string;
  role: string | undefined;
  department: string | null;
  timezone: string;
  onEdit: () => void;
}

export function PersonalInfoCard({
  name,
  employeeId,
  dateOfBirth,
  role,
  department,
  timezone,
  onEdit,
}: PersonalInfoCardProps) {
  const fields = [
    { label: "Full Name", value: name || "—" },
    { label: "Employee ID", value: employeeId || "Not set" },
    { label: "Date of Birth", value: dateOfBirth ? formatDate(dateOfBirth) : "Not set" },
    { label: "Role", value: role || "—" },
    { label: "Department", value: department ?? "Not set" },
    { label: "Time Zone", value: timezone || "Not set" },
  ];

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <UserRound className="h-4 w-4" />
          Personal Information
        </CardTitle>
        <Button variant="ghost" size="sm" onClick={onEdit}>
          Edit
        </Button>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-2">
          {fields.map((field) => (
            <div key={field.label}>
              <dt className="text-sm text-muted-foreground">{field.label}</dt>
              <dd className="mt-0.5 text-sm font-medium">{field.value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
