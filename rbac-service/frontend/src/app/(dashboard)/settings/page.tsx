"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { AxiosError } from "axios";
import {
  Bell,
  Check,
  Globe,
  Laptop,
  Loader2,
  Monitor,
  Moon,
  ShieldCheck,
  Smartphone,
  Sun,
  UserRound,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ChangePasswordDialog } from "@/components/settings/change-password-dialog";
import { PageHeader } from "@/components/layout/dashboard-shell";
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
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
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
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { Language, LANGUAGES } from "@/lib/i18n/translations";
import { cn } from "@/lib/utils";
import { authService } from "@/services";
import { Theme, useAuthStore, useThemeStore } from "@/store/auth-store";
import { useProfileExtrasStore } from "@/store/profile-extras-store";
import { useSettingsStore } from "@/store/settings-store";

const THEME_OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

const accountSchema = z.object({
  name: z.string().min(1, "Name is required"),
  email: z.string().email("Enter a valid email"),
  phone: z.string().optional(),
  address: z.string().optional(),
  avatarUrl: z.string().optional(),
});

type AccountValues = z.infer<typeof accountSchema>;

export default function SettingsPage() {
  const { toast } = useToast();
  const { t } = useTranslation();
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);

  const currentUser = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const { phone, address, avatarUrl, setProfileExtras } = useProfileExtrasStore();
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);

  const notifications = useSettingsStore((s) => s.notifications);
  const setNotification = useSettingsStore((s) => s.setNotification);
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);
  const security = useSettingsStore((s) => s.security);
  const setSecurity = useSettingsStore((s) => s.setSecurity);
  const sessions = useSettingsStore((s) => s.sessions);
  const revokeSession = useSettingsStore((s) => s.revokeSession);
  const revokeAllOtherSessions = useSettingsStore((s) => s.revokeAllOtherSessions);

  const otherSessionsCount = sessions.filter((s) => !s.current).length;

  const accountForm = useForm<AccountValues>({
    resolver: zodResolver(accountSchema),
    defaultValues: {
      name: currentUser?.name ?? "",
      email: currentUser?.email ?? "",
      phone,
      address,
      avatarUrl,
    },
  });

  useEffect(() => {
    if (currentUser) {
      accountForm.reset({
        name: currentUser.name,
        email: currentUser.email,
        phone,
        address,
        avatarUrl,
      });
    }
    // Only re-sync when the logged-in user changes, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser?.user_id]);

  const watchedAvatarUrl = accountForm.watch("avatarUrl");

  const accountMutation = useMutation({
    mutationFn: async (values: AccountValues) => {
      if (values.name !== currentUser?.name || values.email !== currentUser?.email) {
        await authService.updateProfile({ name: values.name, email: values.email });
      }
      setProfileExtras({
        phone: values.phone ?? "",
        address: values.address ?? "",
        avatarUrl: values.avatarUrl ?? "",
      });
    },
    onSuccess: async () => {
      const me = await authService.me();
      setUser(me);
      toast({ title: "Account updated", description: "Your changes have been saved." });
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to update account",
        description: error.response?.data?.detail ?? "Please check your details and try again.",
      });
    },
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("settings.title")}
        description={t("settings.description")}
      />

      {/* Account Settings */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <UserRound className="h-4 w-4" />
            {t("settings.accountSettings")}
          </CardTitle>
          <CardDescription>Update your personal information.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={accountForm.handleSubmit((values) => accountMutation.mutate(values))}
            className="space-y-4"
          >
            <div className="flex items-center gap-4">
              <Avatar className="h-16 w-16">
                {watchedAvatarUrl && (
                  <AvatarImage src={watchedAvatarUrl} alt={currentUser?.name ?? "Avatar"} />
                )}
                <AvatarFallback className="text-xl">
                  {currentUser?.name?.charAt(0).toUpperCase() ?? "U"}
                </AvatarFallback>
              </Avatar>
              <div className="flex-1 space-y-2">
                <Label htmlFor="avatarUrl">Profile Picture URL</Label>
                <Input
                  id="avatarUrl"
                  placeholder="https://example.com/avatar.jpg"
                  {...accountForm.register("avatarUrl")}
                />
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" {...accountForm.register("name")} />
                {accountForm.formState.errors.name && (
                  <p className="text-sm text-destructive">
                    {accountForm.formState.errors.name.message}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" {...accountForm.register("email")} />
                {accountForm.formState.errors.email && (
                  <p className="text-sm text-destructive">
                    {accountForm.formState.errors.email.message}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="phone">Phone</Label>
                <Input id="phone" placeholder="+1 555 000 1234" {...accountForm.register("phone")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="address">Address</Label>
                <Input id="address" placeholder="Street, City, Country" {...accountForm.register("address")} />
              </div>
            </div>

            <div className="flex justify-end">
              <Button type="submit" disabled={accountMutation.isPending}>
                {accountMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                Save Changes
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Theme */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("settings.theme")}</CardTitle>
          <CardDescription>Choose how the platform looks on this device.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {THEME_OPTIONS.map((option) => {
              const Icon = option.icon;
              const active = theme === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setTheme(option.value)}
                  className={cn(
                    "relative flex flex-col items-center gap-2 rounded-xl border p-4 text-sm font-medium transition-all hover:-translate-y-0.5 hover:shadow-md",
                    active
                      ? "border-primary bg-primary/5 ring-2 ring-primary/40"
                      : "border-border bg-card"
                  )}
                >
                  {active && (
                    <div className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                      <Check className="h-3 w-3" />
                    </div>
                  )}
                  <Icon className="h-5 w-5" />
                  {option.label}
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Notifications */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Bell className="h-4 w-4" />
            {t("settings.notifications")}
          </CardTitle>
          <CardDescription>
            Choose what you want to be notified about. Saved to this device.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {[
            { key: "email" as const, label: "Email notifications", description: "Receive updates about your account via email." },
            { key: "push" as const, label: "Push notifications", description: "Get real-time alerts in your browser." },
            { key: "productUpdates" as const, label: "Product updates", description: "News about new features and improvements." },
            { key: "securityAlerts" as const, label: "Security alerts", description: "Important alerts about your account's security." },
          ].map((item) => (
            <div key={item.key} className="flex items-center justify-between rounded-lg border border-border p-3">
              <div>
                <p className="text-sm font-medium">{item.label}</p>
                <p className="text-xs text-muted-foreground">{item.description}</p>
              </div>
              <Switch
                checked={notifications[item.key]}
                onCheckedChange={(checked) => {
                  setNotification(item.key, checked);
                  toast({ title: `${item.label} ${checked ? "enabled" : "disabled"}` });
                }}
              />
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Language */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Globe className="h-4 w-4" />
            {t("settings.language")}
          </CardTitle>
          <CardDescription>Choose your preferred display language.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="max-w-xs space-y-2">
            <Label>Display language</Label>
            <Select
              value={language}
              onValueChange={(value) => {
                setLanguage(value as Language);
                toast({ title: "Language preference saved" });
              }}
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
        </CardContent>
      </Card>

      {/* Security */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4" />
            {t("settings.security")}
          </CardTitle>
          <CardDescription>Manage authentication and account protection.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">Two-factor authentication</p>
              <p className="text-xs text-muted-foreground">
                Require a verification code in addition to your password.
              </p>
            </div>
            <Switch
              checked={security.twoFactorEnabled}
              onCheckedChange={(checked) => {
                setSecurity("twoFactorEnabled", checked);
                toast({ title: `Two-factor authentication ${checked ? "enabled" : "disabled"}` });
              }}
            />
          </div>

          <div className="flex items-center justify-between rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">Login alerts</p>
              <p className="text-xs text-muted-foreground">
                Get notified when your account is signed in from a new device.
              </p>
            </div>
            <Switch
              checked={security.loginAlerts}
              onCheckedChange={(checked) => setSecurity("loginAlerts", checked)}
            />
          </div>

          <div className="flex items-center justify-between rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">Password</p>
              <p className="text-xs text-muted-foreground">
                Update your account password.
              </p>
            </div>
            <Button variant="outline" onClick={() => setChangePasswordOpen(true)}>
              Change Password
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
            <CardDescription>Devices currently signed in to your account.</CardDescription>
          </div>

          {otherSessionsCount > 0 && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" size="sm">
                  Sign out all other sessions
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Sign out all other sessions?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will sign you out on every device except this one.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => {
                      revokeAllOtherSessions();
                      toast({ title: "Signed out of all other sessions" });
                    }}
                  >
                    Sign out
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
                        This device
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
                    toast({ title: "Session revoked" });
                  }}
                >
                  Revoke
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
