import { useEffect, useState } from "react";
import { Loader2, ShieldCheck, UserPlus2 } from "lucide-react";
import { Card } from "@/components/common/Card";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { Modal } from "@/components/common/Modal";
import { TextArea } from "@/components/common/FormField";
import { formatDateTime } from "@/lib/format";
import { useApiAction } from "@/hooks/useApiAction";
import {
  approveEditAccess,
  listEditAccessRequests,
  rejectEditAccess,
  requestEditAccess,
} from "@/api/ticket";
import { useAuthContext } from "@/context/AuthContext";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { EditAccessRequestResponse, EditAccessStatus } from "@/types";

const STATUS_TONE: Record<EditAccessStatus, "warning" | "success" | "danger"> = {
  PENDING: "warning",
  APPROVED: "success",
  REJECTED: "danger",
};

export function EditAccessPanel() {
  const { activeTicket } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const [requests, setRequests] = useState<EditAccessRequestResponse[]>([]);
  const [isRequestModalOpen, setIsRequestModalOpen] = useState(false);
  const [reason, setReason] = useState("");

  const { run: runList, isLoading: isLoadingList } = useApiAction(listEditAccessRequests);
  const { run: runRequest, isLoading: isRequesting } = useApiAction(requestEditAccess, {
    successMessage: "Access request sent.",
  });
  const { run: runApprove, isLoading: isApproving } = useApiAction(approveEditAccess, {
    successMessage: "Access approved.",
  });
  const { run: runReject, isLoading: isRejecting } = useApiAction(rejectEditAccess, {
    successMessage: "Request rejected.",
  });

  async function reload() {
    if (!activeTicket) return;
    const result = await runList(activeTicket.ticket_id);
    if (result) setRequests(result);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTicket?.ticket_id]);

  if (!activeTicket || !currentUser) return null;

  const canReview = currentUser.permissions.includes("ticket:edit_ticket");
  const myPendingRequest = requests.find(
    (r) => r.requested_by === currentUser.user_id && r.status === "PENDING"
  );
  const myActiveGrant = requests.find(
    (r) =>
      r.requested_by === currentUser.user_id &&
      r.status === "APPROVED" &&
      (!r.expires_at || new Date(r.expires_at) > new Date())
  );
  const alreadyHasAccess =
    activeTicket.agent_id === currentUser.user_id || canReview || !!myActiveGrant;
  const pendingForReview = requests.filter((r) => r.status === "PENDING");

  async function handleSubmitRequest() {
    if (!activeTicket || !reason.trim()) return;
    const result = await runRequest(activeTicket.ticket_id, { reason: reason.trim() });
    if (result) {
      setReason("");
      setIsRequestModalOpen(false);
      reload();
    }
  }

  async function handleApprove(requestId: string) {
    if (!activeTicket) return;
    const result = await runApprove(activeTicket.ticket_id, requestId);
    if (result) reload();
  }

  async function handleReject(requestId: string) {
    if (!activeTicket) return;
    const result = await runReject(activeTicket.ticket_id, requestId);
    if (result) reload();
  }

  return (
    <Card title="Edit Access" eyebrow="Collaboration">
      {!alreadyHasAccess && !myPendingRequest && (
        <Button
          size="sm"
          variant="secondary"
          className="w-full justify-center"
          onClick={() => setIsRequestModalOpen(true)}
        >
          <UserPlus2 size={14} />
          Request Edit Access
        </Button>
      )}

      {myPendingRequest && (
        <p className="rounded-md2 border border-border bg-canvas px-3 py-2 text-[12px] text-muted">
          Your request is awaiting approval.
        </p>
      )}

      {canReview && pendingForReview.length > 0 && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            Pending Requests
          </p>
          {pendingForReview.map((request) => (
            <div
              key={request.request_id}
              className="rounded-md2 border border-border bg-surface p-2.5"
            >
              <p className="text-[12px] font-medium text-slate-800">
                {request.requested_by_name ?? "Someone"}
              </p>
              <p className="mt-0.5 text-[12px] text-muted">{request.reason}</p>
              <div className="mt-2 flex gap-1.5">
                <Button
                  size="sm"
                  variant="primary"
                  isLoading={isApproving}
                  onClick={() => handleApprove(request.request_id)}
                >
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  isLoading={isRejecting}
                  onClick={() => handleReject(request.request_id)}
                >
                  Reject
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {isLoadingList ? (
        <div className="mt-3 flex justify-center py-2">
          <Loader2 size={16} className="animate-spin text-muted" />
        </div>
      ) : (
        requests.length > 0 && (
          <div className="mt-3 flex flex-col gap-1.5 border-t border-border pt-3">
            {requests.map((request) => (
              <div
                key={request.request_id}
                className="flex items-center justify-between gap-2 text-[12px]"
              >
                <span className="flex min-w-0 items-center gap-1.5 truncate text-slate-700">
                  {request.status === "APPROVED" && (
                    <ShieldCheck size={12} className="shrink-0 text-success" />
                  )}
                  <span className="truncate">{request.requested_by_name ?? "Someone"}</span>
                </span>
                <div className="flex shrink-0 items-center gap-1.5">
                  <span className="text-[11px] text-muted">
                    {formatDateTime(request.created_at)}
                  </span>
                  <Badge tone={STATUS_TONE[request.status]}>{request.status}</Badge>
                </div>
              </div>
            ))}
          </div>
        )
      )}

      <Modal
        open={isRequestModalOpen}
        title="Request Edit Access"
        onClose={() => setIsRequestModalOpen(false)}
        footer={
          <Button
            variant="primary"
            size="sm"
            isLoading={isRequesting}
            disabled={!reason.trim()}
            onClick={handleSubmitRequest}
          >
            Send Request
          </Button>
        }
      >
        <TextArea
          label="Reason"
          hint="Why do you need to work on this ticket?"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Covering for the assigned agent while they're out."
        />
      </Modal>
    </Card>
  );
}
