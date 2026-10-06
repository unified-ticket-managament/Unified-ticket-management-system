"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Mail } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { getReadReceiptSetting, updateReadReceiptSetting } from "@tw/api/appSettings";
import { setMailFeatures } from "@tw/hooks/useMailFeatures";

export const READ_RECEIPT_SETTING_QUERY_KEY = ["app-settings", "read-receipts"] as const;

// "Email & Communication" > Read Receipts — a system-wide switch for
// whether agents may request read receipts. Default OFF. Everyone can see
// the current state; only holders of `ticket:system_config` (Super Admin
// by default, reported by the server as `can_manage`) can change it, and
// the server re-checks on every update. The database setting behind this
// is the single source of truth (there is no environment-variable
// counterpart).
export function ReadReceiptsSettingCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: READ_RECEIPT_SETTING_QUERY_KEY,
    queryFn: getReadReceiptSetting,
  });

  const mutation = useMutation({
    mutationFn: (enabled: boolean) => updateReadReceiptSetting(enabled),
    onSuccess: (saved) => {
      queryClient.setQueryData(READ_RECEIPT_SETTING_QUERY_KEY, saved);
      // Composers opened later (or already open) see the change at once.
      setMailFeatures({ read_receipts_enabled: saved.read_receipts_enabled });
      toast({
        title: t("settings.readReceiptsSaved", {
          status: t(saved.read_receipts_enabled ? "settings.enabled" : "settings.disabled"),
        }),
      });
    },
    onError: () => {
      toast({ title: t("settings.readReceiptsSaveError"), variant: "destructive" });
    },
  });

  const enabled = query.data?.read_receipts_enabled === true;
  const canManage = query.data?.can_manage === true;
  const busy = mutation.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Mail className="h-4 w-4" />
          {t("settings.emailCommunication")}
        </CardTitle>
        <CardDescription>{t("settings.emailCommunicationDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-4 rounded-lg border border-border p-3">
          <div className="min-w-0">
            <p className="text-sm font-medium">{t("settings.readReceipts")}</p>
            <p className="text-xs text-muted-foreground">{t("settings.readReceiptsDesc")}</p>
          </div>
          {query.isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Loading" />
          ) : (
            <Switch
              aria-label={t("settings.readReceipts")}
              checked={enabled}
              disabled={!canManage || busy || query.isError}
              onCheckedChange={(checked) => mutation.mutate(checked)}
            />
          )}
        </div>

        {query.isError ? (
          <p className="text-xs text-destructive">{t("settings.readReceiptsLoadError")}</p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {t(enabled ? "settings.readReceiptsOnHelp" : "settings.readReceiptsOffHelp")}
            </p>
            {!query.isLoading && !canManage && (
              <p className="text-xs text-muted-foreground">{t("settings.readReceiptsAdminOnly")}</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
