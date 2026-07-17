"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Bell, Laptop, Loader2, Settings2, ShieldCheck, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ChangePasswordDialog } from "@/components/settings/change-password-dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { PROFILE_RECORD_QUERY_KEY } from "@/hooks/use-profile";
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { Language, LANGUAGES } from "@/lib/i18n/translations";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { useSettingsStore } from "@/store/settings-store";
import { User } from "@/types";

const DATE_FORMAT_OPTIONS = ["MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD"];

interface PreferencesValues {
  language: string;
  timeZone: string;
  dateFormat: string;
  timeFormat: string;
  defaultDashboard: string;
}

function preferencesFromRecord(record: User | undefined): PreferencesValues {
  return {
    language: record?.language ?? "en",
    timeZone: record?.time_zone ?? "",
    dateFormat: record?.date_format ?? "MM/DD/YYYY",
    timeFormat: record?.time_format ?? "12h",
    defaultDashboard: record?.default_dashboard ?? "Dashboard",
  };
}

interface SettingsPanelProps {
  open: boolean;
  record?: User;
}

// The previously-standalone /settings page's non-identity content
// (application preferences, notifications, security, sessions),
// relocated to render inside a Dialog on the Profile page (opened via
// its Settings gear button). The old "Account Settings" card (name/
// email/phone/address/avatar) was removed outright — those fields are
// owned exclusively by the Profile page's own Edit Profile dialog now,
// so editing them never appears twice. Language/Time Zone/Date Format/
// Time Format/Default Dashboard moved the other direction, from Edit
// Profile into here, for the same reason: one field, one edit surface.
// See root CLAUDE.md's Profile module section.
export function SettingsPanel({ open, record }: SettingsPanelProps) {
  const { toast } = useToast();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const setUser = useAuthStore((s) => s.setUser);
  const setLanguage = useSettingsStore((s) => s.setLanguage);

  const [changePasswordOpen, setChangePasswordOpen] = useState(false);

  const notifications = useSettingsStore((s) => s.notifications);
  const setNotification = useSettingsStore((s) => s.setNotification);
  const security = useSettingsStore((s) => s.security);
  const setSecurity = useSettingsStore((s) => s.setSecurity);
  const sessions = useSettingsStore((s) => s.sessions);
  const revokeSession = useSettingsStore((s) => s.revokeSession);
  const revokeAllOtherSessions = useSettingsStore((s) => s.revokeAllOtherSessions);

  const otherSessionsCount = sessions.filter((s) => !s.current).length;

  const TIME_FORMAT_OPTIONS = [
    { value: "12h", label: t("common.timeFormat12h") },
    { value: "24h", label: t("common.timeFormat24h") },
  ];

  const NOTIFICATION_ITEMS = [
    { key: "email" as const, label: t("settings.notifEmail"), description: t("settings.notifEmailDesc") },
    { key: "push" as const, label: t("settings.notifPush"), description: t("settings.notifPushDesc") },
    {
      key: "productUpdates" as const,
      label: t("settings.notifProductUpdates"),
      description: t("settings.notifProductUpdatesDesc"),
    },
    {
      key: "securityAlerts" as const,
      label: t("settings.notifSecurityAlerts"),
      description: t("settings.notifSecurityAlertsDesc"),
    },
  ];

  const form = useForm<PreferencesValues>({
    defaultValues: preferencesFromRecord(record),
  });

  useEffect(() => {
    if (open) {
      form.reset(preferencesFromRecord(record));
    }
    // Only re-sync when the dialog opens or the underlying record
    // loads/changes, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, record]);

  const mutation = useMutation({
    mutationFn: async (values: PreferencesValues) => {
      await authService.updateProfile({
        language: values.language || null,
        time_zone: values.timeZone || null,
        date_format: values.dateFormat || null,
        time_format: values.timeFormat || null,
        default_dashboard: values.defaultDashboard || null,
      });

      if (values.language && values.language !== useSettingsStore.getState().language) {
        setLanguage(values.language as Language);
      }
    },
    onSuccess: async () => {
      const me = await authService.me();
      setUser(me);
      await queryClient.invalidateQueries({ queryKey: [PROFILE_RECORD_QUERY_KEY] });
      toast({
        title: t("settings.preferencesUpdatedToast"),
        description: t("settings.preferencesUpdatedDescription"),
      });
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: t("settings.preferencesUpdateFailedToast"),
        description: error.response?.data?.detail ?? t("common.checkDetailsError"),
      });
    },
  });

  return (
    <div className="space-y-6">
      {/* Preferences */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Settings2 className="h-4 w-4" />
            {t("profile.preferences")}
          </CardTitle>
          <CardDescription>{t("settings.preferencesDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
            className="space-y-4"
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>{t("settings.displayLanguage")}</Label>
                <Select
                  value={form.watch("language")}
                  onValueChange={(value) => form.setValue("language", value)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LANGUAGES.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="timeZone">{t("profile.timeZone")}</Label>
                <Input
                  id="timeZone"
                  placeholder={t("settings.timeZonePlaceholder")}
                  {...form.register("timeZone")}
                />
              </div>
              <div className="space-y-2">
                <Label>{t("profile.dateFormat")}</Label>
                <Select
                  value={form.watch("dateFormat")}
                  onValueChange={(value) => form.setValue("dateFormat", value)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DATE_FORMAT_OPTIONS.map((option) => (
                      <SelectItem key={option} value={option}>
                        {option}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("profile.timeFormat")}</Label>
                <Select
                  value={form.watch("timeFormat")}
                  onValueChange={(value) => form.setValue("timeFormat", value)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TIME_FORMAT_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="defaultDashboard">{t("profile.defaultDashboard")}</Label>
                <Input id="defaultDashboard" {...form.register("defaultDashboard")} />
              </div>
            </div>

            <div className="flex justify-end">
              <Button type="submit" disabled={form.formState.isSubmitting || mutation.isPending}>
                {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                {t("common.saveChanges")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Notifications */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Bell className="h-4 w-4" />
            {t("settings.notifications")}
          </CardTitle>
          <CardDescription>{t("settings.notificationsDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {NOTIFICATION_ITEMS.map((item) => (
            <div key={item.key} className="flex items-center justify-between rounded-lg border border-border p-3">
              <div>
                <p className="text-sm font-medium">{item.label}</p>
                <p className="text-xs text-muted-foreground">{item.description}</p>
              </div>
              <Switch
                checked={notifications[item.key]}
                onCheckedChange={(checked) => {
                  setNotification(item.key, checked);
                  toast({
                    title: t("settings.toggleToast", {
                      label: item.label,
                      status: t(checked ? "settings.enabled" : "settings.disabled"),
                    }),
                  });
                }}
              />
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Security */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4" />
            {t("settings.security")}
          </CardTitle>
          <CardDescription>{t("settings.securityDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">{t("settings.twoFactorAuth")}</p>
              <p className="text-xs text-muted-foreground">{t("settings.twoFactorAuthDesc")}</p>
            </div>
            <Switch
              checked={security.twoFactorEnabled}
              onCheckedChange={(checked) => {
                setSecurity("twoFactorEnabled", checked);
                toast({
                  title: t("settings.toggleToast", {
                    label: t("settings.twoFactorAuth"),
                    status: t(checked ? "settings.enabled" : "settings.disabled"),
                  }),
                });
              }}
            />
          </div>

          <div className="flex items-center justify-between rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">{t("settings.loginAlerts")}</p>
              <p className="text-xs text-muted-foreground">{t("settings.loginAlertsDesc")}</p>
            </div>
            <Switch
              checked={security.loginAlerts}
              onCheckedChange={(checked) => setSecurity("loginAlerts", checked)}
            />
          </div>

          <div className="flex items-center justify-between rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">{t("settings.password")}</p>
              <p className="text-xs text-muted-foreground">{t("settings.passwordDesc")}</p>
            </div>
            <Button variant="outline" onClick={() => setChangePasswordOpen(true)}>
              {t("settings.changePassword")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Session Management */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Laptop className="h-4 w-4" />
              {t("settings.sessionManagement")}
            </CardTitle>
            <CardDescription>{t("settings.sessionManagementDescription")}</CardDescription>
          </div>

          {otherSessionsCount > 0 && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" size="sm">
                  {t("settings.signOutAllOtherSessions")}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t("settings.signOutAllOtherSessionsConfirmTitle")}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {t("settings.signOutAllOtherSessionsConfirmDescription")}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => {
                      revokeAllOtherSessions();
                      toast({ title: t("settings.signedOutAllOtherSessionsToast") });
                    }}
                  >
                    {t("settings.signOutConfirm")}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {sessions.map((session) => (
            <div
              key={session.id}
              className="flex items-center justify-between gap-3 rounded-lg border border-border p-3"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  {session.device.toLowerCase().includes("iphone") ||
                  session.device.toLowerCase().includes("android") ? (
                    <Smartphone className="h-4 w-4" />
                  ) : (
                    <Laptop className="h-4 w-4" />
                  )}
                </div>
                <div>
                  <p className="text-sm font-medium">
                    {session.device}
                    {session.current && (
                      <span className="ml-2 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-500">
                        {t("settings.thisDevice")}
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {session.location} · {session.lastActive}
                  </p>
                </div>
              </div>

              {!session.current && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => {
                    revokeSession(session.id);
                    toast({ title: t("settings.sessionRevokedToast") });
                  }}
                >
                  {t("settings.revoke")}
                </Button>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <ChangePasswordDialog open={changePasswordOpen} onOpenChange={setChangePasswordOpen} />
    </div>
  );
}
