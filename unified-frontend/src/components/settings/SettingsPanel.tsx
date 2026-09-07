"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Loader2, PenLine, Settings2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ChangePasswordDialog } from "@/components/settings/change-password-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RichTextEditor } from "@tw/components/mail/RichTextEditor";
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
import { AuthUser, User } from "@/types";

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
  // The signature field is self-service-only (see
  // shared_models.models.User.signature_html's own docstring) and
  // deliberately absent from `record` (GET /users/{id}, the general
  // admin user-CRUD shape any privileged role's Edit User form also
  // uses) — exposing it there would let an admin set it on someone
  // else's account. `/auth/me`'s own AuthUser is the only shape that
  // carries it, hence this separate prop.
  authUser?: AuthUser | null;
}

// The previously-standalone /settings page's non-identity content
// (application preferences, security), relocated to render inside a
// Dialog on the Profile page (opened via its Settings gear button).
// Notifications and Session Management were later removed outright
// (no longer offered anywhere in the product). The old "Account
// Settings" card (name/
// email/phone/address/avatar) was removed outright — those fields are
// owned exclusively by the Profile page's own Edit Profile dialog now,
// so editing them never appears twice. Language/Time Zone/Date Format/
// Time Format/Default Dashboard moved the other direction, from Edit
// Profile into here, for the same reason: one field, one edit surface.
// See root CLAUDE.md's Profile module section.
export function SettingsPanel({ open, record, authUser }: SettingsPanelProps) {
  const { toast } = useToast();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const setUser = useAuthStore((s) => s.setUser);
  const setLanguage = useSettingsStore((s) => s.setLanguage);

  const [changePasswordOpen, setChangePasswordOpen] = useState(false);

  // Own state, own card, own save button — deliberately not folded
  // into `form`/`mutation` above: this is a distinct edit surface with
  // its own error shape (the backend rejects an <img> in a signature
  // with its own 400 detail message, see AuthService.update_profile),
  // not a form-validated preference field.
  const [signatureHtml, setSignatureHtml] = useState(authUser?.signature_html ?? "");

  const security = useSettingsStore((s) => s.security);
  const setSecurity = useSettingsStore((s) => s.setSecurity);

  const TIME_FORMAT_OPTIONS = [
    { value: "12h", label: t("common.timeFormat12h") },
    { value: "24h", label: t("common.timeFormat24h") },
  ];

  const form = useForm<PreferencesValues>({
    defaultValues: preferencesFromRecord(record),
  });

  useEffect(() => {
    if (open) {
      form.reset(preferencesFromRecord(record));
      setSignatureHtml(authUser?.signature_html ?? "");
    }
    // Only re-sync when the dialog opens or the underlying record
    // loads/changes, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, record, authUser]);

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

  const signatureMutation = useMutation({
    mutationFn: async (html: string) => {
      await authService.updateProfile({ signature_html: html || null });
    },
    onSuccess: async () => {
      const me = await authService.me();
      setUser(me);
      await queryClient.invalidateQueries({ queryKey: [PROFILE_RECORD_QUERY_KEY] });
      toast({
        title: t("settings.signatureUpdatedToast"),
        description: t("settings.signatureUpdatedDescription"),
      });
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: t("settings.signatureUpdateFailedToast"),
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

      {/* Email Signature */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <PenLine className="h-4 w-4" />
            {t("settings.emailSignature")}
          </CardTitle>
          <CardDescription>{t("settings.emailSignatureDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <RichTextEditor
            value={signatureHtml}
            onChange={setSignatureHtml}
            placeholder={t("settings.signaturePlaceholder")}
            minHeight="6rem"
          />
          <div className="flex justify-end">
            <Button
              type="button"
              disabled={signatureMutation.isPending}
              onClick={() => signatureMutation.mutate(signatureHtml)}
            >
              {signatureMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t("common.saveChanges")}
            </Button>
          </div>
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

      <ChangePasswordDialog open={changePasswordOpen} onOpenChange={setChangePasswordOpen} />
    </div>
  );
}
