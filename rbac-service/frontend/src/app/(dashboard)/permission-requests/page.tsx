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

const STATUS_VARIANT: Record<PermissionRequestStatus, "warning" | "success" | "destructive"> = {
  PENDING: "warning",
  APPROVED: "success",
  REJECTED: "destructive",
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
              <span className="font-medium">{request.requested_role}</span>
            </p>
          </div>
          <Badge variant={STATUS_VARIANT[request.status]}>{request.status}</Badge>
        </div>

        <p className="text-sm text-muted-foreground">{request.reason}</p>

        {request.status !== "PENDING" && (
          <div className="rounded-lg border border-border bg-muted/40 p-2.5 text-xs text-muted-foreground">
            {request.reviewed_by_name && (
              <p>
                {request.status === "APPROVED" ? "Approved" : "Rejected"} by{" "}
                {request.reviewed_by_name}
                {request.reviewed_at && ` on ${formatDate(request.reviewed_at)}`}
              </p>
            )}
            {request.review_comment && <p className="mt-1">"{request.review_comment}"</p>}
            {request.status === "APPROVED" && (
              <p className="mt-1">
                {request.expires_at
                  ? `Expires ${formatDate(request.expires_at)}`
                  : "Permanent until manually removed"}
                {request.revoked_at && ` — revoked ${formatDate(request.revoked_at)}`}
              </p>
            )}
          </div>
        )}

        {footer}
      </CardContent>
    </Card>
  );
}

function NewRequestDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [permissionId, setPermissionId] = useState("");
  const [requestedRole, setRequestedRole] = useState("");
  const [reason, setReason] = useState("");

  const permissionsQuery = useQuery({
    queryKey: ["permission-requests-eligible-permissions"],
    queryFn: () => permissionRequestService.eligiblePermissions(),
    enabled: open,
  });

  const rolesQuery = useQuery({
    queryKey: ["permission-requests-eligible-roles", permissionId],
    queryFn: () => permissionRequestService.eligibleApproverRoles(permissionId),
    enabled: open && !!permissionId,
  });

  useEffect(() => {
    if (!open) {
      setPermissionId("");
      setRequestedRole("");
      setReason("");
    }
  }, [open]);

  useEffect(() => {
    setRequestedRole("");
  }, [permissionId]);

  const createMutation = useMutation({
    mutationFn: () =>
      permissionRequestService.create({
        permission_id: permissionId,
        requested_role: requestedRole,
        reason: reason.trim(),
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

  const eligiblePermissions = permissionsQuery.data ?? [];
  const eligibleRoles = rolesQuery.data ?? [];
  const canSubmit = !!permissionId && !!requestedRole && reason.trim().length > 0;

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
            <Select value={requestedRole} onValueChange={setRequestedRole} disabled={!permissionId}>
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    !permissionId
                      ? "Select a permission first"
                      : rolesQuery.isLoading
                        ? "Loading approvers..."
                        : rolesQuery.isError
                          ? "Failed to load approvers — try again"
                          : eligibleRoles.length === 0
                            ? "No role can currently grant this"
                            : "Select an approver role"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {eligibleRoles.map((role) => (
                  <SelectItem key={role} value={role}>
                    {role}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {rolesQuery.isError && (
              <p className="text-xs text-destructive">
                Couldn't reach the server. Confirm the backend is running the latest code and
                try again.
              </p>
            )}
          </div>

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

  const approveMutation = useMutation({
    mutationFn: () =>
      permissionRequestService.approve(request!.request_id, {
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        review_comment: comment.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["permission-requests-pending-for-review"] });
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
      queryClient.invalidateQueries({ queryKey: ["permission-requests-pending-for-review"] });
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

export default function PermissionRequestsPage() {
  const currentUser = useAuthStore((s) => s.user);
  const [isNewRequestOpen, setIsNewRequestOpen] = useState(false);
  const [reviewTarget, setReviewTarget] = useState<{
    request: PermissionRequest;
    mode: "approve" | "reject";
  } | null>(null);

  const mineQuery = useQuery({
    queryKey: ["permission-requests-mine"],
    queryFn: () => permissionRequestService.mine(),
  });

  const canReview = (currentUser?.permissions ?? []).includes("permission:override_grant");

  const pendingQuery = useQuery({
    queryKey: ["permission-requests-pending-for-review"],
    queryFn: () => permissionRequestService.pendingForReview(),
    enabled: canReview,
  });

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Permission Requests" }]} />

      <PageHeader
        title="Permission Requests"
        description="Ask for a permission you don't currently have, or review requests addressed to your role."
        action={
          <Button className="gap-2" onClick={() => setIsNewRequestOpen(true)}>
            <Plus className="h-4 w-4" />
            New Request
          </Button>
        }
      />

      <Tabs defaultValue="mine">
        <TabsList>
          <TabsTrigger value="mine">My Requests</TabsTrigger>
          <PermissionGuard permission="permission:override_grant">
            <TabsTrigger value="review">Pending My Review</TabsTrigger>
          </PermissionGuard>
        </TabsList>

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
                title="Nothing pending"
                description="Requests addressed to your role will show up here."
              />
            ) : (
              (pendingQuery.data ?? []).map((request) => (
                <RequestCard
                  key={request.request_id}
                  request={request}
                  footer={
                    <div className="flex gap-2 pt-1">
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
      </Tabs>

      <NewRequestDialog open={isNewRequestOpen} onOpenChange={setIsNewRequestOpen} />

      <ReviewDialog
        request={reviewTarget?.request ?? null}
        mode={reviewTarget?.mode ?? null}
        onClose={() => setReviewTarget(null)}
      />
    </div>
  );
}
