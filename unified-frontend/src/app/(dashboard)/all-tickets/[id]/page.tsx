"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  Paperclip,
  Send,
  ShieldAlert,
  Trash2,
  UserCog,
  XCircle,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { EmptyState } from "@/components/shared/stats";
import { BulkAssignDialog } from "@/components/tickets/bulk-assign-dialog";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  getTicketAttachments,
  getTicketComments,
  getTicketInternalNotes,
  getTicketStatusHistory,
  MockAttachment,
  MockComment,
  MockNote,
  PRIORITY_COLOR,
  STATUS_COLOR,
  TicketPriority,
  TicketStatus,
} from "@/lib/mock-tickets";
import { canDeleteRecords } from "@/lib/role-access";
import { formatDate, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";
import { useMockTicketsStore } from "@/store/mock-tickets-store";

const CATEGORY_OPTIONS = ["Billing", "Technical", "Account Access", "Bug Report", "Feature Request", "General Inquiry"];
const PRIORITY_OPTIONS: TicketPriority[] = ["Low", "Medium", "High", "Critical"];

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-right">{value}</span>
    </div>
  );
}

export default function TicketDetailsPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const currentUser = useAuthStore((s) => s.user);
  const actorName = currentUser?.name ?? "Super Admin";
  const canDelete = canDeleteRecords(currentUser?.role);

  const ticket = useMockTicketsStore((s) => s.tickets.find((t) => t.id === params.id));
  const setStatus = useMockTicketsStore((s) => s.setStatus);
  const assign = useMockTicketsStore((s) => s.assign);
  const updateTicket = useMockTicketsStore((s) => s.updateTicket);
  const deleteTicket = useMockTicketsStore((s) => s.deleteTicket);

  const [comments, setComments] = useState<MockComment[] | null>(null);
  const [notes, setNotes] = useState<MockNote[] | null>(null);
  const [attachments, setAttachments] = useState<MockAttachment[] | null>(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [noteDraft, setNoteDraft] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [editPriority, setEditPriority] = useState<TicketPriority | "">("");
  const [editCategory, setEditCategory] = useState("");

  const resolvedComments = comments ?? (ticket ? getTicketComments(ticket) : []);
  const resolvedNotes = notes ?? (ticket ? getTicketInternalNotes(ticket) : []);
  const resolvedAttachments = attachments ?? (ticket ? getTicketAttachments(ticket) : []);
  const statusHistory = useMemo(() => (ticket ? getTicketStatusHistory(ticket) : []), [ticket]);

  if (!ticket) {
    return (
      <div className="space-y-6">
        <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "All Tickets", href: "/all-tickets" }, { label: params.id }]} />
        <EmptyState
          title="Ticket not found"
          description={`No ticket matching "${params.id}" — it may have been deleted.`}
          action={<Button onClick={() => router.push("/all-tickets")}>Back to All Tickets</Button>}
        />
      </div>
    );
  }

  const canResolve = ticket.status === "Open" || ticket.status === "In Progress";
  const canClose = ticket.status !== "Closed";

  const handleAddComment = () => {
    if (!commentDraft.trim()) return;
    const entry: MockComment = {
      id: `${ticket.id}-comment-new-${resolvedComments.length}`,
      author: actorName,
      role: "agent",
      message: commentDraft.trim(),
      timestamp: new Date().toISOString(),
    };
    setComments([...resolvedComments, entry]);
    setCommentDraft("");
    toast({ title: "Comment added" });
  };

  const handleAddNote = () => {
    if (!noteDraft.trim()) return;
    const entry: MockNote = {
      id: `${ticket.id}-note-new-${resolvedNotes.length}`,
      author: actorName,
      message: noteDraft.trim(),
      timestamp: new Date().toISOString(),
    };
    setNotes([...resolvedNotes, entry]);
    setNoteDraft("");
    toast({ title: "Internal note added" });
  };

  const handleMockUpload = () => {
    const entry: MockAttachment = {
      id: `${ticket.id}-file-new-${resolvedAttachments.length}`,
      name: `attachment-${resolvedAttachments.length + 1}.pdf`,
      size: "256 KB",
      uploadedBy: actorName,
      uploadedAt: new Date().toISOString(),
    };
    setAttachments([...resolvedAttachments, entry]);
    toast({ title: "Attachment uploaded", description: entry.name });
  };

  const handleAssign = (agent: string) => {
    assign(ticket.id, agent, actorName);
    toast({ title: "Ticket assigned", description: `${ticket.id} assigned to ${agent}.` });
    setAssignOpen(false);
  };

  const handleQuickStatus = (status: TicketStatus) => {
    setStatus(ticket.id, status, actorName);
    toast({ title: `Ticket ${status.toLowerCase()}`, description: `${ticket.id} marked as ${status}.` });
  };

  const openUpdateDialog = () => {
    setEditPriority(ticket.priority);
    setEditCategory(ticket.category);
    setUpdateOpen(true);
  };

  const handleUpdate = () => {
    updateTicket(ticket.id, {
      priority: (editPriority || ticket.priority) as TicketPriority,
      category: editCategory || ticket.category,
      updatedDate: new Date().toISOString(),
    });
    toast({ title: "Ticket updated" });
    setUpdateOpen(false);
  };

  const handleDelete = () => {
    deleteTicket(ticket.id);
    toast({ title: "Ticket deleted", description: `${ticket.id} has been removed.` });
    router.push("/all-tickets");
  };

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[{ label: "Dashboard", href: "/dashboard" }, { label: "All Tickets", href: "/all-tickets" }, { label: ticket.id }]}
      />

      <PageHeader
        title={`${ticket.id} · ${ticket.subject}`}
        description={`${ticket.client} — ${ticket.category}`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" className="gap-2" onClick={() => setAssignOpen(true)}>
              <UserCog className="h-4 w-4" />
              {ticket.assignedTo ? "Reassign" : "Assign"}
            </Button>
            <Button variant="outline" className="gap-2" onClick={openUpdateDialog}>
              <FileText className="h-4 w-4" />
              Update
            </Button>
            {canResolve && (
              <Button variant="success" className="gap-2" onClick={() => handleQuickStatus("Resolved")}>
                <CheckCircle2 className="h-4 w-4" />
                Resolve
              </Button>
            )}
            {canClose && (
              <Button variant="outline" className="gap-2" onClick={() => handleQuickStatus("Closed")}>
                <XCircle className="h-4 w-4" />
                Close
              </Button>
            )}
            {canDelete && (
              <Button variant="destructive" className="gap-2" onClick={() => setDeleteOpen(true)}>
                <Trash2 className="h-4 w-4" />
                Delete
              </Button>
            )}
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={STATUS_COLOR[ticket.status].badge} className="text-sm">
          {ticket.status}
        </Badge>
        <Badge variant={PRIORITY_COLOR[ticket.priority].badge} className="text-sm">
          {ticket.priority} Priority
        </Badge>
        {ticket.slaBreached && (
          <Badge variant="destructive" className="gap-1.5 text-sm">
            <ShieldAlert className="h-3.5 w-3.5" />
            SLA Breached
          </Badge>
        )}
        {ticket.escalated && (
          <Badge variant="warning" className="gap-1.5 text-sm">
            <AlertTriangle className="h-3.5 w-3.5" />
            Escalated
          </Badge>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Main column */}
        <div className="lg:col-span-2">
          <Tabs defaultValue="conversation">
            <TabsList>
              <TabsTrigger value="conversation">Conversation</TabsTrigger>
              <TabsTrigger value="notes">Internal Notes</TabsTrigger>
              <TabsTrigger value="attachments">Attachments</TabsTrigger>
              <TabsTrigger value="history">Activity Timeline</TabsTrigger>
            </TabsList>

            <TabsContent value="conversation">
              <Card>
                <CardContent className="space-y-4 p-5">
                  {resolvedComments.map((comment) => (
                    <div
                      key={comment.id}
                      className={comment.role === "agent" ? "flex justify-end" : "flex justify-start"}
                    >
                      <div className={comment.role === "agent" ? "flex max-w-[85%] gap-3" : "flex max-w-[85%] gap-3"}>
                        {comment.role !== "agent" && (
                          <Avatar className="h-8 w-8 shrink-0">
                            <AvatarFallback className="text-xs">{comment.author.charAt(0)}</AvatarFallback>
                          </Avatar>
                        )}
                        <div>
                          <div
                            className={
                              comment.role === "agent"
                                ? "rounded-xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground"
                                : "rounded-xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm"
                            }
                          >
                            {comment.message}
                          </div>
                          <p
                            className={
                              comment.role === "agent"
                                ? "mt-1 text-right text-xs text-muted-foreground"
                                : "mt-1 text-xs text-muted-foreground"
                            }
                          >
                            {comment.author} · {formatRelativeTime(comment.timestamp)}
                          </p>
                        </div>
                        {comment.role === "agent" && (
                          <Avatar className="h-8 w-8 shrink-0">
                            <AvatarFallback className="text-xs">{comment.author.charAt(0)}</AvatarFallback>
                          </Avatar>
                        )}
                      </div>
                    </div>
                  ))}

                  <div className="flex gap-2 border-t border-border pt-4">
                    <Textarea
                      placeholder="Write a reply to the client..."
                      value={commentDraft}
                      onChange={(e) => setCommentDraft(e.target.value)}
                      className="min-h-[44px]"
                    />
                    <Button className="gap-2 self-end" onClick={handleAddComment} disabled={!commentDraft.trim()}>
                      <Send className="h-4 w-4" />
                      Send
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="notes">
              <Card>
                <CardContent className="space-y-3 p-5">
                  {resolvedNotes.length === 0 ? (
                    <EmptyState title="No internal notes" description="Notes are only visible to your team." />
                  ) : (
                    resolvedNotes.map((note) => (
                      <div key={note.id} className="rounded-lg border border-warning/30 bg-warning/5 p-3">
                        <p className="text-sm">{note.message}</p>
                        <p className="mt-1.5 text-xs text-muted-foreground">
                          {note.author} · {formatRelativeTime(note.timestamp)}
                        </p>
                      </div>
                    ))
                  )}

                  <div className="flex gap-2 border-t border-border pt-4">
                    <Textarea
                      placeholder="Add an internal note (not visible to client)..."
                      value={noteDraft}
                      onChange={(e) => setNoteDraft(e.target.value)}
                      className="min-h-[44px]"
                    />
                    <Button className="gap-2 self-end" onClick={handleAddNote} disabled={!noteDraft.trim()}>
                      <Send className="h-4 w-4" />
                      Add
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="attachments">
              <Card>
                <CardContent className="space-y-3 p-5">
                  {resolvedAttachments.length === 0 ? (
                    <EmptyState title="No attachments" description="Files shared on this ticket will appear here." />
                  ) : (
                    resolvedAttachments.map((file) => (
                      <div key={file.id} className="flex items-center gap-3 rounded-lg border border-border p-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                          <Paperclip className="h-5 w-5" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{file.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {file.size} · Uploaded by {file.uploadedBy} · {formatRelativeTime(file.uploadedAt)}
                          </p>
                        </div>
                      </div>
                    ))
                  )}

                  <Button variant="outline" className="gap-2" onClick={handleMockUpload}>
                    <Paperclip className="h-4 w-4" />
                    Upload Attachment
                  </Button>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="history">
              <Card>
                <CardContent className="p-5">
                  <ol className="space-y-6">
                    {statusHistory.map((event, index) => (
                      <li key={event.id} className="relative flex gap-4 pl-2">
                        <div className="flex flex-col items-center">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                            <Clock className="h-4 w-4" />
                          </span>
                          {index < statusHistory.length - 1 && (
                            <span className="mt-1 h-full w-px flex-1 bg-border" />
                          )}
                        </div>
                        <div className="pb-6">
                          <p className="text-sm font-semibold">{event.label}</p>
                          <p className="text-sm text-muted-foreground">{event.description}</p>
                          <p className="mt-1 text-xs text-muted-foreground">{formatDate(event.timestamp)}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>

        {/* Info sidebar */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Ticket Information</CardTitle>
            </CardHeader>
            <CardContent className="divide-y divide-border">
              <InfoRow label="Category" value={ticket.category} />
              <InfoRow label="Assigned Staff" value={ticket.assignedTo} />
              <InfoRow label="Assigned By" value={ticket.assignedBy} />
              <InfoRow label="Created By" value={ticket.createdBy} />
              <InfoRow label="Created Date" value={formatDate(ticket.createdDate)} />
              <InfoRow label="Updated Date" value={formatDate(ticket.updatedDate)} />
              <InfoRow label="Waiting Time" value={`${ticket.waitingMinutes} min`} />
              <InfoRow
                label="SLA Status"
                value={
                  ticket.slaBreached ? (
                    <span className="text-destructive">Breached</span>
                  ) : (
                    <span className="text-success">Within SLA</span>
                  )
                }
              />
            </CardContent>
          </Card>
        </div>
      </div>

      <BulkAssignDialog open={assignOpen} count={1} onOpenChange={setAssignOpen} onAssign={handleAssign} />

      <Dialog open={updateOpen} onOpenChange={setUpdateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Update Ticket</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Category</label>
              <Select value={editCategory} onValueChange={setEditCategory}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Priority</label>
              <Select value={editPriority} onValueChange={(v) => setEditPriority(v as TicketPriority)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITY_OPTIONS.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setUpdateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleUpdate}>Save Changes</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Ticket</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete <strong>{ticket.id}</strong>? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
