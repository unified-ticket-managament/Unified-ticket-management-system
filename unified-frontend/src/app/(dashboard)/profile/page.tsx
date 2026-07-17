"use client";

import { Network, Pencil, Settings } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { OrganizationModal } from "@/components/organization/OrganizationModal";
import { EditProfileDialog } from "@/components/profile/EditProfileDialog";
import { ProfileInformationCard } from "@/components/profile/ProfileInformationCard";
import { ProfileSummaryCard } from "@/components/profile/ProfileSummaryCard";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useProfileData } from "@/hooks/use-profile";
import { useTranslation } from "@/hooks/use-translation";
import { LANGUAGES } from "@/lib/i18n/translations";

const TIME_FORMAT_LABEL_KEYS: Record<string, "common.timeFormat12h" | "common.timeFormat24h"> = {
  "12h": "common.timeFormat12h",
  "24h": "common.timeFormat24h",
};

export default function ProfilePage() {
  const { t } = useTranslation();
  const [orgChartOpen, setOrgChartOpen] = useState(false);
  const [editProfileOpen, setEditProfileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const { user, record, extras, reportsToName, joinedDate } = useProfileData();

  const languageLabel =
    LANGUAGES.find((option) => option.value === record?.language)?.label ?? record?.language ?? null;
  const timeFormatLabel = record?.time_format
    ? t(TIME_FORMAT_LABEL_KEYS[record.time_format] ?? "common.timeFormat12h")
    : null;

  return (
    <div>
      <PageHeader
        title={t("profile.pageTitle")}
        description={t("profile.pageDescription")}
        action={
          <>
            <Button variant="outline" className="gap-2" onClick={() => setOrgChartOpen(true)}>
              <Network className="h-4 w-4" />
              {t("profile.orgChartButton")}
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => setSettingsOpen(true)}>
              <Settings className="h-4 w-4" />
              {t("nav.settings")}
            </Button>
            <Button className="gap-2" onClick={() => setEditProfileOpen(true)}>
              <Pencil className="h-4 w-4" />
              {t("profile.editProfile")}
            </Button>
          </>
        }
      />

      <div className="space-y-6">
        <ProfileSummaryCard
          user={user}
          record={record}
          avatarUrl={extras.avatarUrl}
          phone={record?.phone_number ?? ""}
          officeLocation={record?.office_location ?? ""}
          joinedDate={joinedDate}
        />

        <ProfileInformationCard
          fullName={record?.name ?? user?.name}
          employeeId={record?.user_id ?? user?.user_id}
          dateOfBirth={record?.date_of_birth}
          role={user?.role}
          department={record?.department}
          team={record?.team}
          reportsTo={reportsToName}
          email={record?.email ?? user?.email}
          alternateEmail={record?.alternate_email}
          phoneNumber={record?.phone_number}
          officeLocation={record?.office_location}
          language={languageLabel}
          timeFormat={timeFormatLabel}
          dateFormat={record?.date_format}
          timeZone={record?.time_zone}
          defaultDashboard={record?.default_dashboard}
        />
      </div>

      <OrganizationModal open={orgChartOpen} onOpenChange={setOrgChartOpen} />
      <EditProfileDialog open={editProfileOpen} onOpenChange={setEditProfileOpen} record={record} />

      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("nav.settings")}</DialogTitle>
          </DialogHeader>
          <SettingsPanel open={settingsOpen} record={record} />
        </DialogContent>
      </Dialog>
    </div>
  );
}
