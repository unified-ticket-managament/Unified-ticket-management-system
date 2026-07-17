"use client";

import { Network, Pencil } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { OrganizationModal } from "@/components/organization/OrganizationModal";
import { AccountSummaryCard } from "@/components/profile/AccountSummaryCard";
import { ActivityFeed } from "@/components/profile/ActivityFeed";
import { ContactInfoCard } from "@/components/profile/ContactInfoCard";
import { EditProfileDialog } from "@/components/profile/EditProfileDialog";
import { NotificationSettingsPanel } from "@/components/profile/NotificationSettingsPanel";
import { PersonalInfoCard } from "@/components/profile/PersonalInfoCard";
import { PreferencesCard } from "@/components/profile/PreferencesCard";
import { ProfileSummaryCard } from "@/components/profile/ProfileSummaryCard";
import { SecurityDetailPanel } from "@/components/profile/SecurityDetailPanel";
import { SecurityPanel } from "@/components/profile/SecurityPanel";
import { ChangePasswordDialog } from "@/components/settings/change-password-dialog";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useProfileData } from "@/hooks/use-profile";
import { useSettingsStore } from "@/store/settings-store";

type ProfileTab = "personal" | "security" | "preferences" | "notifications" | "activity";

const TABS: Array<{ value: ProfileTab; label: string }> = [
  { value: "personal", label: "Personal Information" },
  { value: "security", label: "Security" },
  { value: "preferences", label: "Preferences" },
  { value: "notifications", label: "Notification Settings" },
  { value: "activity", label: "Activity" },
];

export default function ProfilePage() {
  const [activeTab, setActiveTab] = useState<ProfileTab>("personal");
  const [orgChartOpen, setOrgChartOpen] = useState(false);
  const [editProfileOpen, setEditProfileOpen] = useState(false);
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);

  const security = useSettingsStore((s) => s.security);
  const setSecurity = useSettingsStore((s) => s.setSecurity);

  const {
    user,
    record,
    extras,
    language,
    departmentName,
    teamName,
    reportsToName,
    joinedDate,
    activity,
    activityLoading,
    activityError,
    lastLogin,
    dashboardStats,
    dashboardStatsLoading,
    slaCompliancePct,
  } = useProfileData();

  const loginHistory = activity.filter((log) => log.action.startsWith("auth."));

  // The right-column widgets persist across tabs, except where they'd
  // just duplicate that tab's own primary content (Security tab already
  // shows a fuller Security panel; Activity tab already shows the full
  // feed) — see SecurityDetailPanel/ActivityFeed reuse below.
  const showSecurityWidget = activeTab !== "security";
  const showActivityWidget = activeTab !== "activity";

  return (
    <div>
      <PageHeader
        title="My Profile"
        description="View and manage your account information and preferences."
        action={
          <>
            <Button variant="outline" className="gap-2" onClick={() => setOrgChartOpen(true)}>
              <Network className="h-4 w-4" />
              Org Chart
            </Button>
            <Button className="gap-2" onClick={() => setEditProfileOpen(true)}>
              <Pencil className="h-4 w-4" />
              Edit Profile
            </Button>
          </>
        }
      />

      <div className="space-y-6">
        <ProfileSummaryCard
          user={user}
          record={record}
          avatarUrl={extras.avatarUrl}
          phone={extras.phone}
          officeLocation={extras.address}
          departmentName={departmentName}
          teamName={teamName}
          reportsToName={reportsToName}
          joinedDate={joinedDate}
        />

        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as ProfileTab)}>
          <TabsList className="h-auto w-full justify-start gap-6 rounded-none border-b border-border bg-transparent p-0">
            {TABS.map((tab) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                className="rounded-none border-b-2 border-transparent bg-transparent px-1 pb-3 text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
              >
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,3fr)]">
          <div className="space-y-6">
            {activeTab === "personal" && (
              <>
                <PersonalInfoCard
                  name={user?.name}
                  employeeId={extras.employeeId}
                  dateOfBirth={extras.dateOfBirth}
                  role={user?.role}
                  department={departmentName}
                  timezone={extras.timezone}
                  onEdit={() => setEditProfileOpen(true)}
                />
                <ContactInfoCard
                  email={user?.email}
                  alternateEmail={extras.alternateEmail}
                  phone={extras.phone}
                  officeLocation={extras.address}
                  onEdit={() => setEditProfileOpen(true)}
                />
                <PreferencesCard
                  language={language}
                  dateFormat={extras.dateFormat}
                  timeFormat={extras.timeFormat}
                  defaultDashboard={extras.defaultDashboard}
                  onEdit={() => setEditProfileOpen(true)}
                />
              </>
            )}

            {activeTab === "security" && (
              <SecurityDetailPanel
                twoFactorEnabled={security.twoFactorEnabled}
                loginAlerts={security.loginAlerts}
                onToggleLoginAlerts={(checked) => setSecurity("loginAlerts", checked)}
                lastLogin={lastLogin}
                loginHistory={loginHistory}
                activityLoading={activityLoading}
                activityError={activityError}
                onChangePassword={() => setChangePasswordOpen(true)}
              />
            )}

            {activeTab === "preferences" && (
              <PreferencesCard
                language={language}
                dateFormat={extras.dateFormat}
                timeFormat={extras.timeFormat}
                defaultDashboard={extras.defaultDashboard}
                onEdit={() => setEditProfileOpen(true)}
              />
            )}

            {activeTab === "notifications" && <NotificationSettingsPanel />}

            {activeTab === "activity" && (
              <ActivityFeed activity={activity} isLoading={activityLoading} isError={activityError} />
            )}
          </div>

          <div className="space-y-6">
            <AccountSummaryCard
              stats={dashboardStats}
              isLoading={dashboardStatsLoading}
              slaCompliancePct={slaCompliancePct}
            />

            {showSecurityWidget && (
              <SecurityPanel
                twoFactorEnabled={security.twoFactorEnabled}
                lastLogin={lastLogin}
                onChangePassword={() => setChangePasswordOpen(true)}
              />
            )}

            {showActivityWidget && (
              <ActivityFeed
                activity={activity}
                isLoading={activityLoading}
                isError={activityError}
                limit={5}
                onViewAll={() => setActiveTab("activity")}
              />
            )}
          </div>
        </div>
      </div>

      <OrganizationModal open={orgChartOpen} onOpenChange={setOrgChartOpen} />
      <EditProfileDialog open={editProfileOpen} onOpenChange={setEditProfileOpen} />
      <ChangePasswordDialog open={changePasswordOpen} onOpenChange={setChangePasswordOpen} />
    </div>
  );
}
