"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ColumnDef,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { Lock, RefreshCw, Search, Download } from "lucide-react";
import { useMemo, useState } from "react";

import { AuditEventList } from "@/components/audit/AuditEventList";
import { AuditEventDetailsDrawer } from "@/components/audit/AuditEventDetailsDrawer";
import {
  normalizeCentralizedAuditEvent,
  type CentralizedAuditEventInput,
} from "@/components/audit/normalizeAuditEvent";
import { DataTablePagination } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/stats";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { auditService, roleService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { AuditLog, Role, User } from "@/types";

// Same shape the shared details drawer expects — see
// normalizeAuditEvent.ts's own doc comment for why this row is built
// once here (a userMap/roleMap join) and normalized before it ever
// reaches the shared AuditEventRow/AuditEventDetailsDrawer.
type AuditRow = CentralizedAuditEventInput;

interface CentralizedAuditLogPanelProps {
  /** Default true — the caller decides whether Export makes sense in
   * its own context; the button is still independently gated on
   * audit:export internally either way. */
  showExport?: boolean;
}

/**
 * The Centralized/system-wide Audit Log — RBAC's own `audit_logs`
 * data (logins, user/role/permission/category changes, permission
 * overrides/requests, impersonation, and now also Rule/Mail-Folder/
 * SLA-Policy administrative changes — see root CLAUDE.md's audit-log
 * separation section). Extracted out of app/(dashboard)/audit-logs/
 * page.tsx so both that page and the ticket-workspace's own Audit
 * Logs page (gated there on `audit:view`, see AuditLogPage.tsx) can
 * render the identical data/behavior without duplicating it.
 *
 * Deliberately owns no page-level chrome (PageHeader/Breadcrumbs) and
 * no permission gate — both callers already gate on `audit:view`
 * before rendering this, and each wants different surrounding chrome.
 */
export function CentralizedAuditLogPanel({ showExport = true }: CentralizedAuditLogPanelProps) {
  const { toast } = useToast();
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "timestamp", desc: true }]);
  const [isExporting, setIsExporting] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerRow, setDrawerRow] = useState<AuditRow | null>(null);

  const auditQuery = useQuery({
    queryKey: ["audit-logs-table"],
    queryFn: () => auditService.list({ page: 1, page_size: 100 }),
  });

  // Same key as the Users page's own "users-table" query (and Roles'
  // matching query) — identical call/params, so TanStack Query's
  // cache (staleTime: 30_000, see query-provider.tsx) shares one
  // request across every page that needs it instead of a fresh
  // identical fetch every time any of them mounts.
  const usersQuery = useQuery({
    queryKey: ["users-table"],
    queryFn: () => userService.list({ page: 1, page_size: 100 }),
  });

  const rolesQuery = useQuery({
    queryKey: ["roles-for-audit"],
    queryFn: () => roleService.list({ page: 1, page_size: 100 }),
  });

  const userMap = useMemo(() => {
    const map = new Map<string, User>();
    (usersQuery.data?.users ?? []).forEach((user: User) => map.set(user.user_id, user));
    return map;
  }, [usersQuery.data]);

  const roleMap = useMemo(() => {
    const map = new Map<string, Role>();
    (rolesQuery.data?.roles ?? []).forEach((role: Role) => map.set(role.role_id, role));
    return map;
  }, [rolesQuery.data]);

  const rows: AuditRow[] = useMemo(() => {
    const logs: AuditLog[] = auditQuery.data?.logs ?? [];
    return logs.map((log) => {
      const user = log.user_id ? userMap.get(log.user_id) : undefined;
      const impersonator = log.impersonator_id ? userMap.get(log.impersonator_id) : undefined;
      return {
        ...log,
        userName: user?.name ?? (log.user_id ? "Unknown User" : "System"),
        userEmail: user?.email ?? null,
        userRole: user ? roleMap.get(user.role_id)?.name ?? null : null,
        impersonatorName: impersonator?.name ?? log.impersonator_name ?? null,
      };
    });
  }, [auditQuery.data, userMap, roleMap]);

  const filteredRows = useMemo(() => {
    return rows.filter((log) => {
      if (search.trim()) {
        const query = search.toLowerCase();
        const matches =
          log.action.toLowerCase().includes(query) ||
          log.entity_type.toLowerCase().includes(query) ||
          log.userName.toLowerCase().includes(query) ||
          (log.userEmail ?? "").toLowerCase().includes(query) ||
          (log.userRole ?? "").toLowerCase().includes(query);
        if (!matches) return false;
      }

      const timestamp = new Date(log.timestamp).getTime();

      if (dateFrom) {
        const from = new Date(dateFrom).getTime();
        if (timestamp < from) return false;
      }

      if (dateTo) {
        const to = new Date(dateTo).getTime() + 24 * 60 * 60 * 1000 - 1;
        if (timestamp > to) return false;
      }

      return true;
    });
  }, [rows, search, dateFrom, dateTo]);

  const columns = useMemo<ColumnDef<AuditRow>[]>(
    () => [
      {
        accessorKey: "userName",
        header: "User",
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{row.original.userName}</p>
            {row.original.userEmail && (
              <p className="truncate text-xs text-muted-foreground">{row.original.userEmail}</p>
            )}
            {row.original.impersonatorName && (
              <p className="truncate text-xs font-medium text-warning">
                Impersonated by {row.original.impersonatorName} (Super Admin)
              </p>
            )}
          </div>
        ),
      },
      {
        accessorKey: "userRole",
        header: "Role",
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.userRole ?? "—"}</span>
        ),
      },
      {
        accessorKey: "action",
        header: "Action",
      },
      {
        accessorKey: "entity_type",
        header: "Entity",
      },
      {
        accessorKey: "timestamp",
        header: "Timestamp",
      },
    ],
    []
  );

  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 10 } },
  });

  if (auditQuery.isError) {
    return <ErrorState message="Failed to load audit logs. Please try again." />;
  }

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const blob = await auditService.export({
        search: search.trim() || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `audit-logs-export-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(url);

      toast({ title: "Export ready", description: "Audit logs exported." });
    } catch {
      toast({
        title: "Export failed",
        description: "You may not have permission to export audit logs, or the request failed. Please try again.",
        variant: "destructive",
      });
    } finally {
      setIsExporting(false);
    }
  };

  const isLoading = auditQuery.isLoading || usersQuery.isLoading || rolesQuery.isLoading;
  const isRefreshing = auditQuery.isFetching || usersQuery.isFetching || rolesQuery.isFetching;
  const pageRows = table.getRowModel().rows;

  // Presentation is entirely delegated to the shared AuditEventRow (via
  // AuditEventList) — this component only normalizes its own RBAC
  // audit_logs rows into the domain-agnostic UnifiedAuditEvent shape.
  // See normalizeAuditEvent.ts and the ticket Audit Log's own
  // (symmetric) use of normalizeTicketAuditEvent.
  const normalizedEvents = useMemo(
    () => pageRows.map((row) => normalizeCentralizedAuditEvent(row.original)),
    [pageRows]
  );

  function handleRefresh() {
    auditQuery.refetch();
    usersQuery.refetch();
    rolesQuery.refetch();
  }

  function handleRowClick(log: AuditRow) {
    setDrawerRow(log);
    setDrawerOpen(true);
  }

  function closeDrawer() {
    setDrawerOpen(false);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2.5 rounded-md2 border border-border bg-surface p-3.5 shadow-xs">
        <div className="relative min-w-[220px] flex-1">
          <Search size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by user, action, or entity..."
            className="w-full rounded-md2 border border-border bg-canvas py-2.5 pl-10 pr-3 text-sm text-slate-900 shadow-xs transition-all placeholder:text-muted-foreground/70 focus:border-accent focus:bg-surface focus:outline-none focus:ring-4 focus:ring-accent/10"
          />
        </div>

        <div className="flex items-center gap-1.5">
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            aria-label="From date"
            className="rounded-md2 border border-border bg-surface px-3 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10"
          />
          <span className="text-xs text-muted-foreground">to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            aria-label="To date"
            className="rounded-md2 border border-border bg-surface px-3 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10"
          />
        </div>

        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          disabled={isRefreshing}
          onClick={handleRefresh}
          aria-label="Refresh audit log"
        >
          <RefreshCw size={14} className={isRefreshing ? "animate-spin" : ""} />
        </Button>

        {showExport && hasPermission("audit:export") && (
          <Button size="sm" variant="outline" className="gap-1.5" onClick={handleExport} disabled={isExporting}>
            <Download size={14} />
            {isExporting ? "Exporting..." : "Export"}
          </Button>
        )}

        <span
          title="Audit entries are immutable — they are never edited or deleted."
          className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
        >
          <Lock size={11} /> Read-only
        </span>
      </div>

      <p className="text-xs text-muted-foreground">
        {auditQuery.data
          ? `${auditQuery.data.total} total system-wide audit events`
          : "Loading system-wide audit events…"}
      </p>

      <AuditEventList
        events={normalizedEvents}
        isLoading={isLoading}
        onEventClick={(event) => {
          const row = pageRows.find((r) => r.original.audit_log_id === event.id)?.original;
          if (row) handleRowClick(row);
        }}
        emptyTitle="No audit logs found"
        emptyDescription="Try adjusting your search or date range."
      />

      <DataTablePagination table={table} />

      <AuditEventDetailsDrawer
        open={drawerOpen}
        event={drawerRow ? normalizeCentralizedAuditEvent(drawerRow) : null}
        onClose={closeDrawer}
      />
    </div>
  );
}
