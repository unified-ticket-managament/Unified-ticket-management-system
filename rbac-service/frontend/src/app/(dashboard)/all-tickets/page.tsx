"use client";

import {
  ColumnDef,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  RowSelectionState,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import {
  CheckCircle2,
  Download,
  Eye,
  MoreHorizontal,
  Plus,
  Search,
  Trash2,
  UserCog,
  UsersRound,
  XCircle,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { DataTable, DataTablePagination } from "@/components/shared/data-table";
import { BulkAssignDialog } from "@/components/tickets/bulk-assign-dialog";
import { TicketFormDialog } from "@/components/tickets/ticket-form-dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { canDeleteRecords } from "@/lib/role-access";
import { MockTicket, PRIORITY_COLOR, STATUS_COLOR } from "@/lib/mock-tickets";
import { formatDate } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";
import { useMockTicketsStore } from "@/store/mock-tickets-store";

const NOW = "2026-07-06T15:00:00.000Z";
const TODAY = new Date("2026-07-06T00:00:00.000Z").getTime();
const DAY_MS = 86_400_000;

const DATE_RANGES = [
  { value: "all", label: "All Time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 Days" },
  { value: "30d", label: "Last 30 Days" },
];

export default function AllTicketsPage() {
  const { toast } = useToast();
  const router = useRouter();
  const currentUser = useAuthStore((s) => s.user);
  const canDelete = canDeleteRecords(currentUser?.role);

  const tickets = useMockTicketsStore((s) => s.tickets);
  const createTicket = useMockTicketsStore((s) => s.createTicket);
  const setStatus = useMockTicketsStore((s) => s.setStatus);
  const assign = useMockTicketsStore((s) => s.assign);
  const bulkAssign = useMockTicketsStore((s) => s.bulkAssign);
  const deleteTicket = useMockTicketsStore((s) => s.deleteTicket);
  const bulkDelete = useMockTicketsStore((s) => s.bulkDelete);

  const [search, setSearch] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [assigneeFilter, setAssigneeFilter] = useState("all");
  const [dateRangeFilter, setDateRangeFilter] = useState("all");

  const [sorting, setSorting] = useState<SortingState>([{ id: "createdDate", desc: true }]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const [createOpen, setCreateOpen] = useState(false);
  const [deletingTicket, setDeletingTicket] = useState<MockTicket | null>(null);
  const [assigningTicket, setAssigningTicket] = useState<MockTicket | null>(null);
  const [bulkAssignOpen, setBulkAssignOpen] = useState(false);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);

  const categories = useMemo(() => Array.from(new Set(tickets.map((t) => t.category))).sort(), [tickets]);
  const assignees = useMemo(() => Array.from(new Set(tickets.map((t) => t.assignedTo))).sort(), [tickets]);

  const filteredRows = useMemo(() => {
    return tickets.filter((ticket) => {
      if (priorityFilter !== "all" && ticket.priority !== priorityFilter) return false;
      if (statusFilter !== "all" && ticket.status !== statusFilter) return false;
      if (categoryFilter !== "all" && ticket.category !== categoryFilter) return false;
      if (assigneeFilter !== "all" && ticket.assignedTo !== assigneeFilter) return false;

      if (dateRangeFilter !== "all") {
        const created = new Date(ticket.createdDate).getTime();
        const daysAgo = Math.floor((TODAY - created) / DAY_MS);
        if (dateRangeFilter === "today" && daysAgo > 0) return false;
        if (dateRangeFilter === "7d" && daysAgo > 7) return false;
        if (dateRangeFilter === "30d" && daysAgo > 30) return false;
      }

      if (search.trim()) {
        const query = search.toLowerCase();
        return (
          ticket.id.toLowerCase().includes(query) ||
          ticket.subject.toLowerCase().includes(query) ||
          ticket.client.toLowerCase().includes(query)
        );
      }

      return true;
    });
  }, [tickets, search, priorityFilter, statusFilter, categoryFilter, assigneeFilter, dateRangeFilter]);

  const selectedIds = useMemo(
    () => Object.keys(rowSelection).filter((id) => rowSelection[id]),
    [rowSelection]
  );

  // rowSelection keys are indices into `filteredRows` (the table's data
  // source), not into `tickets` — resolve to actual ticket IDs before
  // mutating the full `tickets` array so bulk actions stay correct while
  // filters are active.
  const selectedTicketIds = useMemo(
    () => selectedIds.map((id) => filteredRows[Number(id)]?.id).filter((id): id is string => !!id),
    [selectedIds, filteredRows]
  );

  const goToTicket = (ticket: MockTicket) => router.push(`/all-tickets/${ticket.id}`);

  const handleExport = () => {
    const source = selectedIds.length > 0 ? filteredRows.filter((_, i) => selectedIds.includes(String(i))) : filteredRows;
    const header = ["Ticket ID", "Subject", "Client", "Category", "Priority", "Status", "Assigned To", "Created By", "Created Date", "Updated Date"];
    const csvRows = source.map((t) =>
      [t.id, t.subject, t.client, t.category, t.priority, t.status, t.assignedTo, t.createdBy, t.createdDate, t.updatedDate]
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

    toast({ title: "Export ready", description: `${source.length} ticket(s) exported.` });
  };

  const handleCreate = (
    values: Omit<MockTicket, "id" | "assignedBy" | "createdBy" | "createdDate" | "updatedDate" | "slaBreached" | "escalated" | "waitingMinutes">
  ) => {
    const nextId = `TKT-${1001 + tickets.length}`;
    createTicket({
      ...values,
      id: nextId,
      assignedBy: currentUser?.name ?? "Super Admin",
      createdBy: currentUser?.name ?? "Super Admin",
      createdDate: NOW,
      updatedDate: NOW,
      slaBreached: false,
      escalated: false,
      waitingMinutes: 0,
    });
    toast({ title: "Ticket created", description: `${nextId} has been added.` });
  };

  const handleBulkAssign = (agent: string) => {
    bulkAssign(selectedTicketIds, agent, currentUser?.name ?? "Super Admin");
    toast({ title: "Tickets assigned", description: `${selectedTicketIds.length} ticket(s) assigned to ${agent}.` });
    setRowSelection({});
    setBulkAssignOpen(false);
  };

  const handleSingleAssign = (agent: string) => {
    if (!assigningTicket) return;
    assign(assigningTicket.id, agent, currentUser?.name ?? "Super Admin");
    toast({ title: "Ticket assigned", description: `${assigningTicket.id} assigned to ${agent}.` });
    setAssigningTicket(null);
  };

  const handleBulkDelete = () => {
    bulkDelete(selectedTicketIds);
    toast({ title: "Tickets deleted", description: `${selectedTicketIds.length} ticket(s) removed.` });
    setRowSelection({});
    setBulkDeleteOpen(false);
  };

  const handleDeleteOne = () => {
    if (!deletingTicket) return;
    deleteTicket(deletingTicket.id);
    toast({ title: "Ticket deleted", description: `${deletingTicket.id} has been removed.` });
    setDeletingTicket(null);
  };

  const handleQuickStatus = (ticket: MockTicket, status: MockTicket["status"]) => {
    setStatus(ticket.id, status, currentUser?.name ?? "Super Admin");
    toast({ title: `Ticket ${status.toLowerCase()}`, description: `${ticket.id} marked as ${status}.` });
  };

  const columns = useMemo<ColumnDef<MockTicket>[]>(
    () => [
      {
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={table.getIsAllPageRowsSelected() || (table.getIsSomePageRowsSelected() && "indeterminate")}
            onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
            aria-label="Select all"
          />
        ),
        cell: ({ row }) => (
          <div onClick={(e) => e.stopPropagation()}>
            <Checkbox
              checked={row.getIsSelected()}
              onCheckedChange={(value) => row.toggleSelected(!!value)}
              aria-label="Select row"
            />
          </div>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "id",
        header: "Ticket Number",
        cell: ({ row }) => <span className="font-medium text-primary">{row.original.id}</span>,
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
                    View
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setAssigningTicket(ticket)}>
                    <UserCog className="mr-2 h-4 w-4" />
                    {ticket.assignedTo ? "Reassign" : "Assign"}
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
                  {canDelete && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onClick={() => setDeletingTicket(ticket)}
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Delete
                      </DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canDelete]
  );

  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 10 } },
  });

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "All Tickets" }]} />

      <PageHeader
        title="All Tickets"
        description={`${filteredRows.length} of ${tickets.length} tickets shown.`}
        action={
          <div className="flex items-center gap-2">
            {selectedIds.length > 0 && (
              <>
                <Button variant="outline" className="gap-2" onClick={() => setBulkAssignOpen(true)}>
                  <UsersRound className="h-4 w-4" />
                  Bulk Assign
                </Button>
                {canDelete && (
                  <Button variant="destructive" className="gap-2" onClick={() => setBulkDeleteOpen(true)}>
                    <Trash2 className="h-4 w-4" />
                    Bulk Delete
                  </Button>
                )}
              </>
            )}
            <Button variant="outline" className="gap-2" onClick={handleExport}>
              <Download className="h-4 w-4" />
              Export
            </Button>
            <Button className="gap-2" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              Create Ticket
            </Button>
          </div>
        }
      />

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
              {(["Critical", "High", "Medium", "Low"] as const).map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
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
              {(["Open", "In Progress", "Resolved", "Closed"] as const).map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
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
        emptyTitle="No tickets found"
        emptyDescription="Try adjusting your search or filters, or create a new ticket."
        onRowClick={goToTicket}
      />

      <DataTablePagination table={table} showSelectionCount />

      <TicketFormDialog open={createOpen} onOpenChange={setCreateOpen} onCreate={handleCreate} />

      <BulkAssignDialog
        open={!!assigningTicket}
        count={1}
        onOpenChange={(open) => !open && setAssigningTicket(null)}
        onAssign={handleSingleAssign}
      />

      <BulkAssignDialog
        open={bulkAssignOpen}
        count={selectedTicketIds.length}
        onOpenChange={setBulkAssignOpen}
        onAssign={handleBulkAssign}
      />

      <AlertDialog open={!!deletingTicket} onOpenChange={(open) => !open && setDeletingTicket(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Ticket</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete <strong>{deletingTicket?.id}</strong>? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteOne}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={bulkDeleteOpen} onOpenChange={setBulkDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {selectedTicketIds.length} Tickets</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently remove the selected tickets. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleBulkDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
