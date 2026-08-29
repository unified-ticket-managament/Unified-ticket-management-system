"use client";

import { CentralizedAuditLogPanel } from "@/components/audit/CentralizedAuditLogPanel";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { AccessDenied } from "@/components/shared/stats";
import { useTranslation } from "@/hooks/use-translation";
import { useAuthStore } from "@/store/auth-store";

export default function AuditLogsPage() {
  const { t } = useTranslation();
  const hasPermission = useAuthStore((s) => s.hasPermission);

  // Mirrors the backend's GET /audit-logs gate (audit:view — Full for
  // Super Admin/Site Lead, Override-only for Account Manager/Team
  // Lead/Staff). This route has no sidebar entry of its own anymore
  // (see sidebar.tsx/role-access.ts — reached instead via the ticket
  // workspace's own Audit Logs page's "View Centralized Audit Log"
  // button, or a direct link like the Super Admin dashboard's "Latest
  // Audit Logs" card) but must keep enforcing this gate for direct/
  // deep-link access.
  if (!hasPermission("audit:view")) {
    return <AccessDenied message="You do not have access to the Audit Logs page." />;
  }

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Audit Logs" }]} />

      <PageHeader title={t("auditLogs.title")} description={t("auditLogs.description")} />

      <CentralizedAuditLogPanel />
    </div>
  );
}
