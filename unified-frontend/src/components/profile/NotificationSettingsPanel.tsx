"use client";

import { Bell } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/use-toast";
import { NotificationPreferences, useSettingsStore } from "@/store/settings-store";

// Same store/toggles as the Settings page's own Notifications card
// (useSettingsStore().notifications) — surfaced here as the "Notification
// Settings" tab so it's reachable from Profile too, with no separate
// state or backend call of its own.
const NOTIFICATION_ITEMS: Array<{
  key: keyof NotificationPreferences;
  label: string;
  description: string;
}> = [
  { key: "email", label: "Email notifications", description: "Receive updates about your account via email." },
  { key: "push", label: "Push notifications", description: "Get real-time alerts in your browser." },
  { key: "productUpdates", label: "Product updates", description: "News about new features and improvements." },
  { key: "securityAlerts", label: "Security alerts", description: "Important alerts about your account's security." },
];

export function NotificationSettingsPanel() {
  const { toast } = useToast();
  const notifications = useSettingsStore((s) => s.notifications);
  const setNotification = useSettingsStore((s) => s.setNotification);

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Bell className="h-4 w-4" />
          Notification Settings
        </CardTitle>
        <CardDescription>Choose what you want to be notified about. Saved to this device.</CardDescription>
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
                toast({ title: `${item.label} ${checked ? "enabled" : "disabled"}` });
              }}
            />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
