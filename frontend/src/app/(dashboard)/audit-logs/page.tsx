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
import { CheckCircle2, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { actionBadgeVariant, ActionIcon } from "@/components/shared/audit";
import { DataTable, DataTablePagination } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/stats";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDate } from "@/lib/utils";
import { auditService, userService } from "@/services";
import { AuditLog, User } from "@/types";

type AuditRow = AuditLog & { userName: string; userEmail: string | null };

export default function AuditLogsPage() {
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "timestamp", desc: true }]);

  const auditQuery = useQuery({
    queryKey: ["audit-logs-table"],
    queryFn: () => auditService.list({ page: 1, page_size: 100 }),
  });

  const usersQuery = useQuery({
    queryKey: ["users-for-audit"],
    queryFn: () => userService.list({ page: 1, page_size: 100 }),
  });

  const userMap = useMemo(() => {
    const map = new Map<string, User>();
    (usersQuery.data?.users ?? []).forEach((user: User) => map.set(user.user_id, user));
    return map;
  }, [usersQuery.data]);

  const rows: AuditRow[] = useMemo(() => {
    const logs: AuditLog[] = auditQuery.data?.logs ?? [];
    return logs.map((log) => {
      const user = log.user_id ? userMap.get(log.user_id) : undefined;
      return {
        ...log,
        userName: user?.name ?? (log.user_id ? "Unknown User" : "System"),
        userEmail: user?.email ?? null,
      };
    });
  }, [auditQuery.data, userMap]);

  const filteredRows = useMemo(() => {
    return rows.filter((log) => {
      if (search.trim()) {
        const query = search.toLowerCase();
        const matches =
          log.action.toLowerCase().includes(query) ||
          log.entity_type.toLowerCase().includes(query) ||
          log.userName.toLowerCase().includes(query) ||
          (log.userEmail ?? "").toLowerCase().includes(query);
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
        cell: () => (
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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit Logs"
        description={`A detailed record of activity across your organization${auditQuery.data ? ` — ${auditQuery.data.total} total` : ""}.`}
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

      <DataTable
        table={table}
        columnCount={columns.length}
        isLoading={auditQuery.isLoading || usersQuery.isLoading}
        emptyTitle="No audit logs found"
        emptyDescription="Try adjusting your search or date range."
      />

      <DataTablePagination table={table} />
    </div>
  );
}
