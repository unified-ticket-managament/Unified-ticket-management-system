"use client";

import Link from "next/link";
import { KeyRound, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/utils";

interface SecurityPanelProps {
  twoFactorEnabled: boolean;
  lastLogin: string | null;
  onChangePassword: () => void;
}

// Reused verbatim in both the right-column "Security" widget and the
// Security tab's main content — same data, same actions, just a
// differently sized container around it. Two-factor state is the
// existing settings-store toggle (see unified-frontend/CLAUDE.md — it's
// a UI-only preference today, no real 2FA flow); "Manage 2FA" links to
// the Settings page, where that toggle already lives, rather than
// duplicating it here.
export function SecurityPanel({ twoFactorEnabled, lastLogin, onChangePassword }: SecurityPanelProps) {
  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-4 w-4" />
          Security
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium">Password</p>
            <p className="text-xs text-muted-foreground">••••••••</p>
          </div>
          <Button variant="outline" size="sm" onClick={onChangePassword}>
            <KeyRound className="h-4 w-4" />
            Change Password
          </Button>
        </div>

        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium">Last Login</p>
            <p className="text-xs text-muted-foreground">
              {lastLogin ? formatDate(lastLogin) : "No login activity recorded yet"}
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3">
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
      </CardContent>
    </Card>
  );
}
