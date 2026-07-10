"use client";

import {
  ColumnDef,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { Archive, CheckCircle2, Clock, Eye, MoreHorizontal, Ticket as TicketIcon, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { DataTable, DataTablePagination } from "@/components/shared/data-table";
import { StatCard } from "@/components/shared/stats";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/hooks/use-toast";
import { MockTicket, PRIORITY_COLOR, STATUS_COLOR } from "@/lib/mock-tickets";
import { formatDate } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";
import { useMockTicketsStore } from "@/store/mock-tickets-store";

export default function MyTicketsPage() {
  const router = useRouter();
  const { toast } = useToast();
  const currentUser = useAuthStore((s) => s.user);
  const actorName = currentUser?.name ?? "Super Admin";

  const allTickets = useMockTicketsStore((s) => s.tickets);
  const setStatus = useMockTicketsStore((s) => s.setStatus);

  const [sorting, setSorting] = useState<SortingState>([{ id: "updatedDate", desc: true }]);

  const myTickets = useMemo(
    () => allTickets.filter((t) => t.createdBy === actorName || t.assignedTo === actorName),
    [allTickets, actorName]
  );

  const kpis = useMemo(
    () => ({
      open: myTickets.filter((t) => t.status === "Open").length,
      inProgress: myTickets.filter((t) => t.status === "In Progress").length,
      resolved: myTickets.filter((t) => t.status === "Resolved").length,
      closed: myTickets.filter((t) => t.status === "Closed").length,
    }),
    [myTickets]
  );

  const goToTicket = (ticket: MockTicket) => router.push(`/all-tickets/${ticket.id}`);

  const handleQuickStatus = (ticket: MockTicket, status: MockTicket["status"]) => {
    setStatus(ticket.id, status, actorName);
    toast({ title: `Ticket ${status.toLowerCase()}`, description: `${ticket.id} marked as ${status}.` });
  };

  const columns = useMemo<ColumnDef<MockTicket>[]>(
    () => [
      {
        accessorKey: "id",
        header: "Ticket ID",
        cell: ({ row }) => <span className="font-medium text-primary">{row.original.id}</span>,
      },
      {
        accessorKey: "subject",
        header: "Subject",
        cell: ({ row }) => <span className="line-clamp-1 max-w-[280px]">{row.original.subject}</span>,
      },
      {
        accessorKey: "priority",
        header: "Priority",
        cell: ({ row }) => (
          <Badge variant={PRIORITY_COLOR[row.original.priority].badge}>{row.original.priority}</Badge>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <Badge variant={STATUS_COLOR[row.original.status].badge}>{row.original.status}</Badge>,
      },
      {
        accessorKey: "assignedTo",
        header: "Assigned To",
        cell: ({ row }) => <span className="text-sm">{row.original.assignedTo}</span>,
      },
      {
        accessorKey: "updatedDate",
        header: "Last Updated",
        cell: ({ row }) => <span className="text-muted-foreground">{formatDate(row.original.updatedDate)}</span>,
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        enableSorting: false,
        cell: ({ row }) => {
          const ticket = row.original;
          const canResolve = ticket.status === "Open" || ticket.status === "In Progress";
          const canClose = ticket.status !== "Closed";

          return (
            <div onClick={(e) => e.stopPropagation()}>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Ticket actions">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => goToTicket(ticket)}>
                    <Eye className="mr-2 h-4 w-4" />
                    View / Update
                  </DropdownMenuItem>
                  {canResolve && (
                    <DropdownMenuItem onClick={() => handleQuickStatus(ticket, "Resolved")}>
                      <CheckCircle2 className="mr-2 h-4 w-4" />
                      Resolve
                    </DropdownMenuItem>
                  )}
                  {canClose && (
                    <DropdownMenuItem onClick={() => handleQuickStatus(ticket, "Closed")}>
                      <XCircle className="mr-2 h-4 w-4" />
                      Close
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const table = useReactTable({
    data: myTickets,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 10 } },
  });

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "My Tickets" }]} />

      <PageHeader title="My Tickets" description="Tickets you created or that are assigned to you." />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="My Open" value={kpis.open} subtitle="Awaiting first response" icon={TicketIcon} />
        <StatCard title="My In Progress" value={kpis.inProgress} subtitle="Actively being worked" icon={Clock} tone="warning" />
        <StatCard title="My Resolved" value={kpis.resolved} subtitle="Closed within SLA" icon={CheckCircle2} tone="success" />
        <StatCard title="My Closed" value={kpis.closed} subtitle="All-time closed" icon={Archive} />
      </div>

      <DataTable
        table={table}
        columnCount={columns.length}
        emptyTitle="No tickets yet"
        emptyDescription="Tickets you create or that get assigned to you will show up here."
        onRowClick={goToTicket}
      />

      <DataTablePagination table={table} />
    </div>
  );
}
