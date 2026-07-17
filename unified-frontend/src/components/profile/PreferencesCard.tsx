"use client";

import { Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Language, LANGUAGES } from "@/lib/i18n/translations";

const TIME_FORMAT_LABELS: Record<string, string> = {
  "12h": "12-hour",
  "24h": "24-hour",
};

interface PreferencesCardProps {
  language: Language;
  dateFormat: string;
  timeFormat: string;
  defaultDashboard: string;
  onEdit: () => void;
}

export function PreferencesCard({
  language,
  dateFormat,
  timeFormat,
  defaultDashboard,
  onEdit,
}: PreferencesCardProps) {
  const languageLabel = LANGUAGES.find((option) => option.value === language)?.label ?? language;

  const fields = [
    { label: "Language", value: languageLabel },
    { label: "Date Format", value: dateFormat || "Not set" },
    { label: "Time Format", value: TIME_FORMAT_LABELS[timeFormat] ?? (timeFormat || "Not set") },
    { label: "Default Dashboard", value: defaultDashboard || "Not set" },
  ];

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Settings2 className="h-4 w-4" />
          Preferences
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
