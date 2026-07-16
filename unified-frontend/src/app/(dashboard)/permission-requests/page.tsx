"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Loader2, Plus } from "lucide-react";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { EmptyState } from "@/components/shared/stats";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { formatDate } from "@/lib/utils";
import { permissionRequestService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { PermissionRequest, PermissionRequestStatus } from "@/types";

const STATUS_VARIANT: Record<PermissionRequestStatus, "warning" | "success" | "destructive" | "secondary"> = {
  PENDING: "warning",
  APPROVED: "success",
  REJECTED: "destructive",
  REVOKED: "secondary",
};

function RequestCard({ request, footer }: { request: PermissionRequest; footer?: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate font-mono text-sm font-medium">{request.permission_name}</p>
            <p className="text-xs text-muted-foreground">
              {request.requester_name ?? "Someone"} → requested from{" "}
              <span className="font-medium">
                {request.selected_approver_name
                  ? `${request.selected_approver_name} (${request.requested_role})`
                  : request.requested_role}
              </span>
            </p>
          </div>
          <Badge variant={STATUS_VARIANT[request.status]}>{request.status}</Badge>
        </div>

        <p className="text-sm text-muted-foreground">{request.reason}</p>

        {request.scope_ticket_id && (
          <p className="text-xs text-muted-foreground">
            Scoped to one specific ticket only — not this person's other tickets.
          </p>
        )}

        <div className="rounded-lg border border-border bg-muted/40 p-2.5 text-xs text-muted-foreground space-y-1">
          <p>Requested on {formatDate(request.created_at)}</p>

          {request.status === "APPROVED" && (
            <>
              <p>
                Approved by {request.reviewed_by_name ?? "—"}
                {request.reviewed_at && ` on ${formatDate(request.reviewed_at)}`}
              </p>
              <p>
                {request.expires_at
                  ? `Expires ${formatDate(request.expires_at)}`
                  : "Permanent until manually removed"}
              </p>
            </>
          )}

          {request.status === "REJECTED" && (
            <>
              <p>
                Rejected by {request.reviewed_by_name ?? "—"}
                {request.reviewed_at && ` on ${formatDate(request.reviewed_at)}`}
              </p>
              {request.review_comment && (
                <p>Rejection reason: "{request.review_comment}"</p>
              )}
            </>
          )}

          {request.status === "REVOKED" && (
            <>
              <p>
                Approved{request.reviewed_at && ` on ${formatDate(request.reviewed_at)}`}
              </p>
              <p>
                Revoked by {request.revoked_by_name ?? "—"}
                {request.revoked_at && ` on ${formatDate(request.revoked_at)}`}
              </p>
              {request.revoke_reason && <p>Revoke reason: "{request.revoke_reason}"</p>}
            </>
          )}
        </div>

        {footer}
      </CardContent>
    </Card>
  );
}

const TICKET_SCOPED_PERMISSION = "ticket:editother_ticket";

function NewRequestDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [permissionId, setPermissionId] = useState("");
  const [approverId, setApproverId] = useState("");
  const [reason, setReason] = useState("");
  const [staffId, setStaffId] = useState("");
  const [ticketId, setTicketId] = useState("");

  const permissionsQuery = useQuery({
    queryKey: ["permission-requests-eligible-permissions"],
    queryFn: () => permissionRequestService.eligiblePermissions(),
    enabled: open,
  });

  const eligiblePermissions = permissionsQuery.data ?? [];
  const selectedPermissionName = eligiblePermissions.find(
    (p) => p.permission_id === permissionId
  )?.permission_name;
  const needsTicketScope = selectedPermissionName === TICKET_SCOPED_PERMISSION;

  const approversQuery = useQuery({
    queryKey: ["permission-requests-eligible-approver-users", permissionId],
    queryFn: () => permissionRequestService.eligibleApproverUsers(permissionId),
    enabled: open && !!permissionId,
  });

  const staffOptionsQuery = useQuery({
    queryKey: ["permission-requests-staff-options"],
    queryFn: () => permissionRequestService.staffOptions(),
    enabled: open && needsTicketScope,
  });

  const ticketOptionsQuery = useQuery({
    queryKey: ["permission-requests-ticket-options", staffId],
    queryFn: () => permissionRequestService.ticketOptions(staffId),
    enabled: open && needsTicketScope && !!staffId,
  });

  useEffect(() => {
    if (!open) {
      setPermissionId("");
      setApproverId("");
      setReason("");
      setStaffId("");
      setTicketId("");
    }
  }, [open]);

  useEffect(() => {
    setApproverId("");
    setStaffId("");
    setTicketId("");
  }, [permissionId]);

  useEffect(() => {
    setTicketId("");
  }, [staffId]);

  const createMutation = useMutation({
    mutationFn: () =>
      permissionRequestService.create({
        permission_id: permissionId,
        selected_approver_id: approverId,
        reason: reason.trim(),
        scope_ticket_id: needsTicketScope ? ticketId : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["permission-requests-mine"] });
      toast({ title: "Request sent", description: "You'll be notified once it's reviewed." });
      onOpenChange(false);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to send request",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

  const eligibleApprovers = approversQuery.data ?? [];
  const staffOptions = staffOptionsQuery.data ?? [];
  const ticketOptions = ticketOptionsQuery.data ?? [];
  const canSubmit =
    !!permissionId &&
    !!approverId &&
    reason.trim().length > 0 &&
    (!needsTicketScope || (!!staffId && !!ticketId));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request a Permission</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Permission</Label>
            <Select value={permissionId} onValueChange={setPermissionId}>
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    permissionsQuery.isLoading
                      ? "Loading permissions..."
                      : permissionsQuery.isError
                        ? "Failed to load permissions — try again"
                        : eligiblePermissions.length === 0
                          ? "You already have every permission"
                          : "Select a permission"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {eligiblePermissions.map((permission) => (
                  <SelectItem key={permission.permission_id} value={permission.permission_id}>
                    {permission.permission_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {permissionsQuery.isError && (
              <p className="text-xs text-destructive">
                Couldn't reach the server. Confirm the backend is running the latest code and
                try again.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Request To</Label>
            <Select value={approverId} onValueChange={setApproverId} disabled={!permissionId}>
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    !permissionId
                      ? "Select a permission first"
                      : approversQuery.isLoading
                        ? "Loading approvers..."
                        : approversQuery.isError
                          ? "Failed to load approvers — try again"
                          : eligibleApprovers.length === 0
                            ? "No one can currently grant this"
                            : "Select a specific approver"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {eligibleApprovers.map((approver) => (
                  <SelectItem key={approver.user_id} value={approver.user_id}>
                    {approver.name} — {approver.role_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Only this exact person is notified and can review the request.
            </p>
            {approversQuery.isError && (
              <p className="text-xs text-destructive">
                Couldn't reach the server. Confirm the backend is running the latest code and
                try again.
              </p>
            )}
          </div>

          {needsTicketScope && (
            <>
              <div className="space-y-2">
                <Label>Select Staff</Label>
                <Select value={staffId} onValueChange={setStaffId}>
                  <SelectTrigger>
                    <SelectValue
                      placeholder={
                        staffOptionsQuery.isLoading
                          ? "Loading teammates..."
                          : staffOptionsQuery.isError
                            ? "Failed to load teammates — try again"
                            : staffOptions.length === 0
                              ? "No teammates found"
                              : "Select a teammate"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {staffOptions.map((s) => (
                      <SelectItem key={s.user_id} value={s.user_id}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Only teammates who share your Team Lead are listed.
                </p>
              </div>

              <div className="space-y-2">
                <Label>Select Ticket</Label>
                <Select value={ticketId} onValueChange={setTicketId} disabled={!staffId}>
                  <SelectTrigger>
                    <SelectValue
                      placeholder={
                        !staffId
                          ? "Select a teammate first"
                          : ticketOptionsQuery.isLoading
                            ? "Loading tickets..."
                            : ticketOptionsQuery.isError
                              ? "Failed to load tickets — try again"
                              : ticketOptions.length === 0
                                ? "This teammate has no assigned tickets"
                                : "Select a ticket"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {ticketOptions.map((t) => (
                      <SelectItem key={t.ticket_id} value={t.ticket_id}>
                        {t.title} — {t.current_status}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Access is granted for this one ticket only, not this teammate's other tickets.
                </p>
              </div>
            </>
          )}

          <div className="space-y-2">
            <Label>Reason</Label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why do you need this permission?"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!canSubmit || createMutation.isPending} onClick={() => createMutation.mutate()}>
            {createMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Send Request
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReviewDialog({
  request,
  mode,
  onClose,
}: {
  request: PermissionRequest | null;
  mode: "approve" | "reject" | null;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [expiresAt, setExpiresAt] = useState("");
  const [comment, setComment] = useState("");

  useEffect(() => {
    setExpiresAt("");
    setComment("");
  }, [request, mode]);

  const invalidateAfterDecision = () => {
    queryClient.invalidateQueries({ queryKey: ["permission-requests-pending-for-review"] });
    queryClient.invalidateQueries({ queryKey: ["permission-requests-history"] });
  };

  const approveMutation = useMutation({
    mutationFn: () =>
      permissionRequestService.approve(request!.request_id, {
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        review_comment: comment.trim() || undefined,
      }),
    onSuccess: () => {
      invalidateAfterDecision();
      toast({ title: "Request approved" });
      onClose();
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to approve",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () =>
      permissionRequestService.reject(request!.request_id, {
        review_comment: comment.trim() || undefined,
      }),
    onSuccess: () => {
      invalidateAfterDecision();
      toast({ title: "Request rejected" });
      onClose();
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to reject",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

  const isApprove = mode === "approve";
  const isPending = approveMutation.isPending || rejectMutation.isPending;

  return (
    <Dialog open={!!request && !!mode} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isApprove ? "Approve" : "Reject"} Permission Request</DialogTitle>
        </DialogHeader>

        {request && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              <span className="font-mono">{request.permission_name}</span> for{" "}
              {request.requester_name ?? "this user"}
            </p>

            {isApprove && (
              <div className="space-y-2">
                <Label>Expires (optional)</Label>
                <Input
                  type="datetime-local"
                  value={expiresAt}
                  onChange={(e) => setExpiresAt(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Leave blank to grant permanently, until manually removed.
                </p>
              </div>
            )}

            <div className="space-y-2">
              <Label>Comment (optional)</Label>
              <Textarea value={comment} onChange={(e) => setComment(e.target.value)} />
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={isApprove ? "default" : "destructive"}
            disabled={isPending}
            onClick={() => (isApprove ? approveMutation.mutate() : rejectMutation.mutate())}
          >
            {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {isApprove ? "Approve" : "Reject"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevokeDialog({
  request,
  onClose,
}: {
  request: PermissionRequest | null;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");

  useEffect(() => {
    setReason("");
  }, [request]);

  const revokeMutation = useMutation({
    mutationFn: () =>
      permissionRequestService.revoke(request!.request_id, {
        reason: reason.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["permission-requests-history"] });
      queryClient.invalidateQueries({ queryKey: ["permission-requests-mine"] });
      toast({ title: "Permission revoked", description: "The user's effective permissions have been updated." });
      onClose();
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to revoke",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

  return (
    <Dialog open={!!request} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Revoke Permission</DialogTitle>
        </DialogHeader>

        {request && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              This removes <span className="font-mono">{request.permission_name}</span> from{" "}
              {request.requester_name ?? "this user"} immediately. This action can't be undone —
              they would need to request it again.
            </p>

            <div className="space-y-2">
              <Label>Reason (optional)</Label>
              <Textarea value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={revokeMutation.isPending}
            onClick={() => revokeMutation.mutate()}
          >
            {revokeMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Revoke
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const SUPER_ADMIN_ROLE = "Super Admin";

export default function PermissionRequestsPage() {
  const currentUser = useAuthStore((s) => s.user);
  const [isNewRequestOpen, setIsNewRequestOpen] = useState(false);
  const [reviewTarget, setReviewTarget] = useState<{
    request: PermissionRequest;
    mode: "approve" | "reject";
  } | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<PermissionRequest | null>(null);

  const mineQuery = useQuery({
    queryKey: ["permission-requests-mine"],
    queryFn: () => permissionRequestService.mine(),
  });

  const canReview = (currentUser?.permissions ?? []).includes("permission:override_grant");
  // Super Admin already holds every permission by default — there's
  // nothing left to request, so the button (and the "My Requests" tab
  // entirely) is hidden rather than opening a dialog with an empty list.
  const isSuperAdmin = currentUser?.role === SUPER_ADMIN_ROLE;

  const pendingQuery = useQuery({
    queryKey: ["permission-requests-pending-for-review"],
    queryFn: () => permissionRequestService.pendingForReview(),
    enabled: canReview,
  });

  const historyQuery = useQuery({
    queryKey: ["permission-requests-history"],
    queryFn: () => permissionRequestService.history(),
    enabled: canReview,
  });

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Users", href: "/users" },
          { label: "Permission Requests" },
        ]}
      />

      <PageHeader
        title="Permission Requests"
        description="Ask for a permission you don't currently have, or review requests addressed to you."
        action={
          isSuperAdmin ? undefined : (
            <Button className="gap-2" onClick={() => setIsNewRequestOpen(true)}>
              <Plus className="h-4 w-4" />
              New Request
            </Button>
          )
        }
      />

      <Tabs defaultValue={isSuperAdmin ? "review" : "mine"}>
        <TabsList>
          {!isSuperAdmin && <TabsTrigger value="mine">My Requests</TabsTrigger>}
          <PermissionGuard permission="permission:override_grant">
            <TabsTrigger value="review">Pending My Review</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </PermissionGuard>
        </TabsList>

        {!isSuperAdmin && (
          <TabsContent value="mine" className="space-y-3">
            {mineQuery.isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-28 w-full rounded-xl" />
                ))}
              </div>
            ) : (mineQuery.data ?? []).length === 0 ? (
              <EmptyState
                title="No permission requests yet"
                description="Use New Request to ask for a permission you don't currently have."
              />
            ) : (
              (mineQuery.data ?? []).map((request) => (
                <RequestCard key={request.request_id} request={request} />
              ))
            )}
          </TabsContent>
        )}

        <PermissionGuard permission="permission:override_grant">
          <TabsContent value="review" className="space-y-3">
            {pendingQuery.isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-28 w-full rounded-xl" />
                ))}
              </div>
            ) : (pendingQuery.data ?? []).length === 0 ? (
              <EmptyState
                title="Nothing to review"
                description="Requests addressed specifically to you will show up here."
              />
            ) : (
              (pendingQuery.data ?? []).map((request) => (
                <RequestCard
                  key={request.request_id}
                  request={request}
                  footer={
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <Button
                        size="sm"
                        onClick={() => setReviewTarget({ request, mode: "approve" })}
                      >
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setReviewTarget({ request, mode: "reject" })}
                      >
                        Reject
                      </Button>
                    </div>
                  }
                />
              ))
            )}
          </TabsContent>
        </PermissionGuard>

        <PermissionGuard permission="permission:override_grant">
          <TabsContent value="history" className="space-y-3">
            {historyQuery.isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-28 w-full rounded-xl" />
                ))}
              </div>
            ) : (historyQuery.data ?? []).length === 0 ? (
              <EmptyState
                title="No decided requests yet"
                description="Approved, rejected, and revoked requests will show up here, permanently."
              />
            ) : (
              (historyQuery.data ?? []).map((request) => (
                <RequestCard
                  key={request.request_id}
                  request={request}
                  footer={
                    request.status === "APPROVED" && request.can_revoke ? (
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => setRevokeTarget(request)}
                        >
                          Revoke
                        </Button>
                      </div>
                    ) : undefined
                  }
                />
              ))
            )}
          </TabsContent>
        </PermissionGuard>
      </Tabs>

      <NewRequestDialog open={isNewRequestOpen} onOpenChange={setIsNewRequestOpen} />

      <ReviewDialog
        request={reviewTarget?.request ?? null}
        mode={reviewTarget?.mode ?? null}
        onClose={() => setReviewTarget(null)}
      />

      <RevokeDialog request={revokeTarget} onClose={() => setRevokeTarget(null)} />
    </div>
  );
}
