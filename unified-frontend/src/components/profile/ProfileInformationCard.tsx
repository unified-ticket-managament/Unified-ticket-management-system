"use client";

import { Contact, IdCard, Settings2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTranslation } from "@/hooks/use-translation";
import { TranslationKey } from "@/lib/i18n/translations";
import { formatDate } from "@/lib/utils";

interface Field {
  labelKey: TranslationKey;
  value: string | null | undefined;
}

function FieldGrid({ fields, notSetLabel }: { fields: Field[]; notSetLabel: string }) {
  const { t } = useTranslation();
  return (
    <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {fields.map((field) => (
        <div key={field.labelKey}>
          <dt className="text-sm text-muted-foreground">{t(field.labelKey)}</dt>
          <dd className="mt-0.5 text-sm font-medium">{field.value || notSetLabel}</dd>
        </div>
      ))}
    </dl>
  );
}

interface ProfileInformationCardProps {
  // Personal
  fullName: string | null | undefined;
  employeeId: string | null | undefined;
  dateOfBirth: string | null | undefined;
  role: string | null | undefined;
  department: string | null | undefined;
  team: string | null | undefined;
  reportsTo: string | null | undefined;
  // Contact
  email: string | null | undefined;
  alternateEmail: string | null | undefined;
  phoneNumber: string | null | undefined;
  officeLocation: string | null | undefined;
  // Preferences
  language: string | null | undefined;
  timeFormat: string | null | undefined;
  dateFormat: string | null | undefined;
  timeZone: string | null | undefined;
  defaultDashboard: string | null | undefined;
}

// Merges what used to be three separate cards (Personal/Contact/
// Preferences Information) into one "Profile Information" card — every
// field here is sourced from the real `users` table (see
// shared_models.models.User), not a client-only store. This card is
// display-only: it used to carry its own secondary "Edit" button, but
// that was removed as a duplicate of the page header's own "Edit
// Profile" button — the single header button is the only entry point
// into editing now. Every label/heading is translated (see
// useTranslation) — the field *values* themselves are real database
// data (names, IDs, dates, etc.) and are never translated, only
// locale-formatted where `formatDate` already does so.
export function ProfileInformationCard({
  fullName,
  employeeId,
  dateOfBirth,
  role,
  department,
  team,
  reportsTo,
  email,
  alternateEmail,
  phoneNumber,
  officeLocation,
  language,
  timeFormat,
  dateFormat,
  timeZone,
  defaultDashboard,
}: ProfileInformationCardProps) {
  const { t } = useTranslation();
  const notSetLabel = t("profile.notSet");

  const personalFields: Field[] = [
    { labelKey: "profile.fullName", value: fullName },
    { labelKey: "profile.employeeId", value: employeeId },
    { labelKey: "profile.dateOfBirth", value: dateOfBirth ? formatDate(dateOfBirth) : null },
    { labelKey: "profile.role", value: role },
    { labelKey: "profile.department", value: department },
    { labelKey: "profile.team", value: team },
    { labelKey: "profile.reportsTo", value: reportsTo },
  ];

  const contactFields: Field[] = [
    { labelKey: "profile.email", value: email },
    { labelKey: "profile.alternateEmail", value: alternateEmail },
    { labelKey: "profile.phoneNumber", value: phoneNumber },
    { labelKey: "profile.officeLocation", value: officeLocation },
  ];

  const preferenceFields: Field[] = [
    { labelKey: "settings.language", value: language },
    { labelKey: "profile.timeFormat", value: timeFormat },
    { labelKey: "profile.dateFormat", value: dateFormat },
    { labelKey: "profile.timeZone", value: timeZone },
    { labelKey: "profile.defaultDashboard", value: defaultDashboard },
  ];

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-base">{t("profile.informationTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="space-y-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            <IdCard className="h-4 w-4" />
            {t("profile.personalDetails")}
          </h3>
          <FieldGrid fields={personalFields} notSetLabel={notSetLabel} />
        </section>

        <section className="space-y-3 border-t border-border pt-5">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            <Contact className="h-4 w-4" />
            {t("profile.contactDetails")}
          </h3>
          <FieldGrid fields={contactFields} notSetLabel={notSetLabel} />
        </section>

        <section className="space-y-3 border-t border-border pt-5">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            <Settings2 className="h-4 w-4" />
            {t("profile.preferences")}
          </h3>
          <FieldGrid fields={preferenceFields} notSetLabel={notSetLabel} />
        </section>
      </CardContent>
    </Card>
  );
}
