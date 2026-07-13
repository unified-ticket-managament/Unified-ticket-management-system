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
import { CheckCircle2, Download, Search, XCircle } from "lucide-react";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { actionBadgeVariant, ActionIcon } from "@/components/shared/audit";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { DataTablePagination } from "@/components/shared/data-table";
import { EmptyState, ErrorState } from "@/components/shared/stats";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { formatDate } from "@/lib/utils";
import { auditService, roleService, userService } from "@/services";
import { AuditLog, Role, User } from "@/types";

type AuditRow = AuditLog & {
  userName: string;
  userEmail: string | null;
  userRole: string | null;
};

// The only outcome this system currently distinguishes is a failed
// login attempt / a rejected request — every other logged action only
// ever gets written after it already succeeded (an exception aborts
// the request before any audit_logs row is created), so anything else
// is genuinely "Success," not a hardcoded assumption.
function isFailureAction(action: string): boolean {
  const value = action.toLowerCase();
  return value.includes("failed") || value.includes("reject");
}

export default function AuditLogsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "timestamp", desc: true }]);

  const auditQuery = useQuery({
    queryKey: ["audit-logs-table"],
    queryFn: () => auditService.list({ page: 1, page_size: 100 }),
  });

  // Same key as the Users page's own "users-table" query (and Roles'
  // matching query) — identical call/params, so TanStack Query's
  // cache (staleTime: 30_000, see query-provider.tsx) shares one
  // request across all three pages instead of a fresh identical fetch
  // every time any of them mounts. Also means a user mutated from the
  // Users page (which invalidates "users-table") correctly
  // invalidates this page's copy too, instead of it silently staying
  // stale until its own 30s window happened to expire.
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
      return {
        ...log,
        userName: user?.name ?? (log.user_id ? "Unknown User" : "System"),
        userEmail: user?.email ?? null,
        userRole: user ? roleMap.get(user.role_id)?.name ?? null : null,
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
          <div className="flex items-center gap-3">
            <Avatar className="h-8 w-8">
              <AvatarFallback className="text-xs">
                {row.original.userName.charAt(0).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{row.original.userName}</p>
              {row.original.userEmail && (
                <p className="truncate text-xs text-muted-foreground">{row.original.userEmail}</p>
              )}
            </div>
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
        cell: ({ row }) => (
          <Badge variant={actionBadgeVariant(row.original.action)} className="gap-1.5">
            <ActionIcon action={row.original.action} />
            {row.original.action}
          </Badge>
        ),
      },
      {
        accessorKey: "entity_type",
        header: "Entity",
        cell: ({ row }) => (
          <div>
            <p className="text-sm">{row.original.entity_type}</p>
            {row.original.entity_id && (
              <p className="font-mono text-xs text-muted-foreground">
                {row.original.entity_id.slice(0, 8)}
              </p>
            )}
          </div>
        ),
      },
      {
        accessorKey: "timestamp",
        header: "Timestamp",
        cell: ({ row }) => (
          <span className="text-muted-foreground">{formatDate(row.original.timestamp)}</span>
        ),
      },
      {
        id: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) =>
          isFailureAction(row.original.action) ? (
            <Badge variant="destructive" className="gap-1.5">
              <XCircle className="h-3 w-3" />
              Failed
            </Badge>
          ) : (
            <Badge variant="success" className="gap-1.5">
              <CheckCircle2 className="h-3 w-3" />
              Success
            </Badge>
          ),
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

  const handleExport = () => {
    const header = ["User", "Email", "Role", "Action", "Entity", "Entity ID", "Status", "Timestamp", "IP Address"];
    const csvRows = filteredRows.map((log) =>
      [
        log.userName,
        log.userEmail ?? "",
        log.userRole ?? "",
        log.action,
        log.entity_type,
        log.entity_id ?? "",
        isFailureAction(log.action) ? "Failed" : "Success",
        log.timestamp,
        log.ip_address ?? "",
      ]
        .map((value) => `"${String(value).replace(/"/g, '""')}"`)
        .join(",")
    );
    const csv = [header.join(","), ...csvRows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `audit-logs-export-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);

    toast({ title: "Export ready", description: `${filteredRows.length} log(s) exported.` });
  };

  const isLoading = auditQuery.isLoading || usersQuery.isLoading || rolesQuery.isLoading;
  const pageRows = table.getRowModel().rows;

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Audit Logs" }]} />

      <PageHeader
        title={t("auditLogs.title")}
        description={`${t("auditLogs.description")}${auditQuery.data ? ` — ${auditQuery.data.total} ${t("common.total")}` : ""}.`}
        action={
          <Button variant="outline" className="gap-2" onClick={handleExport}>
            <Download className="h-4 w-4" />
            Export
          </Button>
        }
      />

      <Card>
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          <div className="flex-1">
            <Label className="mb-1.5 block text-xs text-muted-foreground">Search</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search by user, action, or entity..."
                className="pl-9"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">From</Label>
            <Input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="w-full sm:w-40"
            />
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">To</Label>
            <Input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="w-full sm:w-40"
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-5">
          {isLoading ? (
            <div className="space-y-6">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : pageRows.length === 0 ? (
            <EmptyState title="No audit logs found" description="Try adjusting your search or date range." />
          ) : (
            <ol>
              {pageRows.map((row, index) => {
                const log = row.original;
                return (
                  <li key={log.audit_log_id} className="relative flex gap-4 pl-2">
                    <div className="flex flex-col items-center">
                      <Avatar className="h-9 w-9 shrink-0 border border-border">
                        <AvatarFallback className="text-xs">
                          {log.userName.charAt(0).toUpperCase()}
                        </AvatarFallback>
                      </Avatar>
                      {index < pageRows.length - 1 && <span className="mt-1 h-full w-px flex-1 bg-border" />}
                    </div>
                    <div className="flex-1 pb-6">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold">{log.userName}</p>
                        {log.userRole && (
                          <Badge variant="outline" className="text-xs">
                            {log.userRole}
                          </Badge>
                        )}
                        <Badge variant={actionBadgeVariant(log.action)} className="gap-1.5">
                          <ActionIcon action={log.action} />
                          {log.action}
                        </Badge>
                        {isFailureAction(log.action) ? (
                          <Badge variant="destructive" className="gap-1.5">
                            <XCircle className="h-3 w-3" />
                            Failed
                          </Badge>
                        ) : (
                          <Badge variant="success" className="gap-1.5">
                            <CheckCircle2 className="h-3 w-3" />
                            Success
                          </Badge>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {log.entity_type}
                        {log.entity_id && <span className="font-mono text-xs"> · {log.entity_id.slice(0, 8)}</span>}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {formatDate(log.timestamp)}
                        {log.ip_address && <span> · {log.ip_address}</span>}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </CardContent>
      </Card>

      <DataTablePagination table={table} />
    </div>
  );
}
