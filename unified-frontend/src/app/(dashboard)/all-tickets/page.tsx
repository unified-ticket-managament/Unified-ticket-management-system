"use client";

import {
  ColumnDef,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { AlertTriangle, Download, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { DataTable, DataTablePagination } from "@/components/shared/data-table";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { formatDate } from "@/lib/utils";
import { listTickets } from "@tw/api/ticket";
import { shortId } from "@tw/lib/format";
import type { TicketPriority, TicketResponse, TicketStatus } from "@tw/types";

const UNASSIGNED_LABEL = "Unassigned";
const DAY_MS = 86_400_000;

const DATE_RANGES = [
  { value: "all", label: "All Time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 Days" },
  { value: "30d", label: "Last 30 Days" },
];

const PRIORITY_OPTIONS: TicketPriority[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const PRIORITY_LABEL: Record<TicketPriority, string> = {
  CRITICAL: "Critical",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
};
const PRIORITY_BADGE: Record<TicketPriority, "destructive" | "warning" | "default" | "secondary"> = {
  CRITICAL: "destructive",
  HIGH: "warning",
  MEDIUM: "default",
  LOW: "secondary",
};

const STATUS_OPTIONS: TicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "PENDING",
  "WAITING_FOR_CLIENT",
  "RESOLVED",
  "CLOSED",
];
const STATUS_LABEL: Record<TicketStatus, string> = {
  OPEN: "Open",
  IN_PROGRESS: "In Progress",
  PENDING: "Pending",
  WAITING_FOR_CLIENT: "Waiting for Client",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
};
const STATUS_BADGE: Record<TicketStatus, "default" | "warning" | "success" | "secondary"> = {
  OPEN: "default",
  IN_PROGRESS: "warning",
  PENDING: "secondary",
  WAITING_FOR_CLIENT: "secondary",
  RESOLVED: "success",
  CLOSED: "secondary",
};

interface TicketRow {
  id: string;
  subject: string;
  client: string;
  category: string;
  priority: TicketPriority;
  status: TicketStatus;
  assignedTo: string;
  createdBy: string;
  createdDate: string;
  updatedDate: string;
}

function toTicketRow(ticket: TicketResponse): TicketRow {
  return {
    id: ticket.ticket_id,
    subject: ticket.title,
    client: ticket.client_company_name ?? ticket.client_name ?? "—",
    category: ticket.ticket_type,
    priority: ticket.current_priority,
    status: ticket.current_status,
    assignedTo: ticket.agent_name ?? UNASSIGNED_LABEL,
    createdBy: ticket.created_by_name ?? "—",
    createdDate: ticket.created_at,
    updatedDate: ticket.updated_at,
  };
}

export default function AllTicketsPage() {
  const { toast } = useToast();
  const router = useRouter();

  const [tickets, setTickets] = useState<TicketRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const [search, setSearch] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [assigneeFilter, setAssigneeFilter] = useState("all");
  const [dateRangeFilter, setDateRangeFilter] = useState("all");

  const [sorting, setSorting] = useState<SortingState>([{ id: "createdDate", desc: true }]);

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    listTickets()
      .then((data) => {
        if (!active) return;
        setTickets(data.map(toTicketRow));
        setLoadError(null);
      })
      .catch((error) => {
        if (!active) return;
        setLoadError(error instanceof Error ? error.message : "Failed to load tickets.");
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });

    return () => {
      active = false;
    };
  }, [reloadToken]);

  const categories = useMemo(() => Array.from(new Set(tickets.map((t) => t.category))).sort(), [tickets]);
  const assignees = useMemo(() => Array.from(new Set(tickets.map((t) => t.assignedTo))).sort(), [tickets]);

  const filteredRows = useMemo(() => {
    const now = Date.now();
    return tickets.filter((ticket) => {
      if (priorityFilter !== "all" && ticket.priority !== priorityFilter) return false;
      if (statusFilter !== "all" && ticket.status !== statusFilter) return false;
      if (categoryFilter !== "all" && ticket.category !== categoryFilter) return false;
      if (assigneeFilter !== "all" && ticket.assignedTo !== assigneeFilter) return false;

      if (dateRangeFilter !== "all") {
        const created = new Date(ticket.createdDate).getTime();
        const daysAgo = Math.floor((now - created) / DAY_MS);
        if (dateRangeFilter === "today" && daysAgo > 0) return false;
        if (dateRangeFilter === "7d" && daysAgo > 7) return false;
        if (dateRangeFilter === "30d" && daysAgo > 30) return false;
      }

      if (search.trim()) {
        const query = search.toLowerCase();
        return (
          ticket.id.toLowerCase().includes(query) ||
          shortId(ticket.id).toLowerCase().includes(query) ||
          ticket.subject.toLowerCase().includes(query) ||
          ticket.client.toLowerCase().includes(query)
        );
      }

      return true;
    });
  }, [tickets, search, priorityFilter, statusFilter, categoryFilter, assigneeFilter, dateRangeFilter]);

  const goToTicket = (ticket: TicketRow) => router.push(`/dashboard/tickets/${ticket.id}`);

  const handleExport = () => {
    const header = ["Ticket ID", "Subject", "Client", "Category", "Priority", "Status", "Assigned To", "Created By", "Created Date", "Updated Date"];
    const csvRows = filteredRows.map((t) =>
      [shortId(t.id), t.subject, t.client, t.category, PRIORITY_LABEL[t.priority], STATUS_LABEL[t.status], t.assignedTo, t.createdBy, t.createdDate, t.updatedDate]
        .map((value) => `"${String(value).replace(/"/g, '""')}"`)
        .join(",")
    );
    const csv = [header.join(","), ...csvRows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `all-tickets-export-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);

    toast({ title: "Export ready", description: `${filteredRows.length} ticket(s) exported.` });
  };

  const columns = useMemo<ColumnDef<TicketRow>[]>(
    () => [
      {
        accessorKey: "id",
        header: "Ticket Number",
        cell: ({ row }) => <span className="font-medium text-primary">{shortId(row.original.id)}</span>,
      },
      {
        accessorKey: "subject",
        header: "Subject",
        cell: ({ row }) => <span className="line-clamp-1 max-w-[220px]">{row.original.subject}</span>,
      },
      { accessorKey: "client", header: "Client" },
      {
        accessorKey: "category",
        header: "Category",
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.category}</span>,
      },
      {
        accessorKey: "priority",
        header: "Priority",
        cell: ({ row }) => (
          <Badge variant={PRIORITY_BADGE[row.original.priority]}>{PRIORITY_LABEL[row.original.priority]}</Badge>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <Badge variant={STATUS_BADGE[row.original.status]}>{STATUS_LABEL[row.original.status]}</Badge>,
      },
      {
        accessorKey: "assignedTo",
        header: "Assigned To",
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <Avatar className="h-7 w-7">
              <AvatarFallback className="text-xs">{row.original.assignedTo.charAt(0)}</AvatarFallback>
            </Avatar>
            <span className="text-sm">{row.original.assignedTo}</span>
          </div>
        ),
      },
      {
        accessorKey: "createdBy",
        header: "Created By",
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.createdBy}</span>,
      },
      {
        accessorKey: "createdDate",
        header: "Created Date",
        cell: ({ row }) => <span className="text-muted-foreground">{formatDate(row.original.createdDate)}</span>,
      },
      {
        accessorKey: "updatedDate",
        header: "Updated Date",
        cell: ({ row }) => <span className="text-muted-foreground">{formatDate(row.original.updatedDate)}</span>,
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

  const emptyTitle = loadError ? "Unable to load tickets" : "No tickets found";
  const emptyDescription = loadError ? loadError : "Try adjusting your search or filters.";

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "All Tickets" }]} />

      <PageHeader
        title="All Tickets"
        description={`${filteredRows.length} of ${tickets.length} tickets shown.`}
        action={
          <Button variant="outline" className="gap-2" onClick={handleExport} disabled={filteredRows.length === 0}>
            <Download className="h-4 w-4" />
            Export
          </Button>
        }
      />

      {loadError && (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="flex items-center justify-between gap-3 p-4 text-sm text-destructive">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 flex-none" />
              <span>{loadError}</span>
            </div>
            <Button variant="outline" size="sm" onClick={() => setReloadToken((t) => t + 1)}>
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search by ID, subject, or client..."
              className="pl-9"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <Select value={priorityFilter} onValueChange={setPriorityFilter}>
            <SelectTrigger className="w-full lg:w-36">
              <SelectValue placeholder="Priority" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Priority</SelectItem>
              {PRIORITY_OPTIONS.map((p) => (
                <SelectItem key={p} value={p}>
                  {PRIORITY_LABEL[p]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-full lg:w-36">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              {STATUS_OPTIONS.map((s) => (
                <SelectItem key={s} value={s}>
                  {STATUS_LABEL[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger className="w-full lg:w-40">
              <SelectValue placeholder="Category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Categories</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={assigneeFilter} onValueChange={setAssigneeFilter}>
            <SelectTrigger className="w-full lg:w-40">
              <SelectValue placeholder="Assigned User" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Assignees</SelectItem>
              {assignees.map((a) => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={dateRangeFilter} onValueChange={setDateRangeFilter}>
            <SelectTrigger className="w-full lg:w-36">
              <SelectValue placeholder="Date Range" />
            </SelectTrigger>
            <SelectContent>
              {DATE_RANGES.map((r) => (
                <SelectItem key={r.value} value={r.value}>
                  {r.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <DataTable
        table={table}
        columnCount={columns.length}
        isLoading={isLoading}
        emptyTitle={emptyTitle}
        emptyDescription={emptyDescription}
        onRowClick={goToTicket}
      />

      <DataTablePagination table={table} />
    </div>
  );
}
