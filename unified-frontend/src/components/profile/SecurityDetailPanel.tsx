"use client";

import Link from "next/link";
import { KeyRound, ShieldCheck } from "lucide-react";

import { ActivityFeed } from "@/components/profile/ActivityFeed";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { formatDate } from "@/lib/utils";
import { AuditLog } from "@/types";

interface SecurityDetailPanelProps {
  twoFactorEnabled: boolean;
  loginAlerts: boolean;
  onToggleLoginAlerts: (checked: boolean) => void;
  lastLogin: string | null;
  loginHistory: AuditLog[];
  activityLoading: boolean;
  activityError: boolean;
  onChangePassword: () => void;
}

// The Security tab's main content — a fuller view than the right-column
// Security widget (same Password/2FA facts, plus Login Alerts and a
// login-history list filtered from the same audit-log query everything
// else on this page already uses). Reuses ChangePasswordDialog's own
// trigger, the existing settings-store Login Alerts toggle, and
// ActivityFeed rather than building new equivalents.
export function SecurityDetailPanel({
  twoFactorEnabled,
  loginAlerts,
  onToggleLoginAlerts,
  lastLogin,
  loginHistory,
  activityLoading,
  activityError,
  onChangePassword,
}: SecurityDetailPanelProps) {
  return (
    <div className="space-y-6">
      <Card className="rounded-md border-border shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4" />
            Security
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">Password</p>
              <p className="text-xs text-muted-foreground">••••••••</p>
            </div>
            <Button variant="outline" size="sm" onClick={onChangePassword}>
              <KeyRound className="h-4 w-4" />
              Change Password
            </Button>
          </div>

          <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">Last Login</p>
              <p className="text-xs text-muted-foreground">
                {lastLogin ? formatDate(lastLogin) : "No login activity recorded yet"}
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">Two-Factor Authentication</p>
              <Badge variant={twoFactorEnabled ? "success" : "secondary"} className="mt-1">
                {twoFactorEnabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
            <Button variant="outline" size="sm" asChild>
              <Link href="/settings">Manage 2FA</Link>
            </Button>
          </div>

          <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">Login Alerts</p>
              <p className="text-xs text-muted-foreground">
                Get notified when your account is signed in from a new device.
              </p>
            </div>
            <Switch checked={loginAlerts} onCheckedChange={onToggleLoginAlerts} />
          </div>
        </CardContent>
      </Card>

      <ActivityFeed
        activity={loginHistory}
        isLoading={activityLoading}
        isError={activityError}
        title="Login History"
        description="Recent sign-ins to your account."
      />
    </div>
  );
}
