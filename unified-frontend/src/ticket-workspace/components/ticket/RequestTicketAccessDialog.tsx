import { useEffect, useState } from "react";
import { Button } from "@tw/components/common/Button";
import { SelectInput, TextArea } from "@tw/components/common/FormField";
import { useToast } from "@tw/context/ToastContext";
import { permissionRequestService } from "@/services";
import type { EligibleApproverUser } from "@/types";

// ==========================================================
// RequestTicketAccessDialog
//
// Replaces the old ticket-workspace-native Edit Access request panel
// (EditAccessPanel, deleted) — access to work someone else's ticket
// is now requested through the RBAC "Permission Requests" system
// (see @/services's permissionRequestService and this repo's own
// CLAUDE.md "Permission requests" section), scoped to this one
// ticket via `scope_ticket_id` exactly like the RBAC-native
// NewRequestDialog's own ticket-scope fields already do.
//
// Rendered as plain content INSIDE the shared <Modal> in
// TicketActions.tsx (same convention as that file's Status/Priority/
// Transfer modal bodies) — this component owns its own bottom action
// row rather than using Modal's `footer` prop, since it needs local
// state (loading/validity) the outer Modal has no way to see.
//
// Note this calls the SHELL app's `@/services` (backed by `@/lib/api`)
// rather than the ticket-workspace's own `@tw/api` layer — that axios
// instance has no interceptor that rewraps a backend error's `detail`
// field onto `Error.message` the way `@tw/api/client.ts` does, so
// errors here are unwrapped manually (see `extractErrorMessage`
// below) rather than relying on `useApiAction`'s generic
// `error.message` extraction, which would otherwise show a generic
// axios message instead of the real backend explanation.
// ==========================================================

const TICKET_ACCESS_PERMISSION_NAME = "ticket:editother_ticket";

interface RequestTicketAccessDialogProps {
  ticketId: string;
  ticketOwnerName: string | null | undefined;
  onClose: () => void;
  onSubmitted: () => void;
}

function extractErrorMessage(error: unknown, fallback: string): string {
  if (
    error &&
    typeof error === "object" &&
    "response" in error &&
    error.response &&
    typeof error.response === "object" &&
    "data" in error.response
  ) {
    const data = (error.response as { data?: unknown }).data;
    if (data && typeof data === "object" && "detail" in data) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export function RequestTicketAccessDialog({
  ticketId,
  ticketOwnerName,
  onClose,
  onSubmitted,
}: RequestTicketAccessDialogProps) {
  const { pushToast } = useToast();
  const [isResolvingPermission, setIsResolvingPermission] = useState(true);
  const [permissionId, setPermissionId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Only needed when the ticket has no current owner for the backend
  // to auto-route to — see the manual-picker fallback below.
  const [approvers, setApprovers] = useState<EligibleApproverUser[]>([]);
  const [selectedApproverId, setSelectedApproverId] = useState("");
  const [isLoadingApprovers, setIsLoadingApprovers] = useState(false);

  const needsManualApprover = !ticketOwnerName;

  useEffect(() => {
    let cancelled = false;
    setIsResolvingPermission(true);
    permissionRequestService
      .eligiblePermissions()
      .then((permissions) => {
        if (cancelled) return;
        const match = permissions.find(
          (permission) => permission.permission_name === TICKET_ACCESS_PERMISSION_NAME
        );
        setPermissionId(match ? match.permission_id : null);
      })
      .catch((error) => {
        if (!cancelled) {
          pushToast(
            extractErrorMessage(error, "Couldn't check your current access — try again."),
            "error"
          );
        }
      })
      .finally(() => {
        if (!cancelled) setIsResolvingPermission(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!permissionId || !needsManualApprover) return;
    let cancelled = false;
    setIsLoadingApprovers(true);
    permissionRequestService
      .eligibleApproverUsers(permissionId)
      .then((users) => {
        if (cancelled) return;
        setApprovers(users);
        setSelectedApproverId((current) => current || users[0]?.user_id || "");
      })
      .catch((error) => {
        if (!cancelled) {
          pushToast(
            extractErrorMessage(error, "Couldn't load eligible reviewers — try again."),
            "error"
          );
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoadingApprovers(false);
      });
    return () => {
      cancelled = true;
    };
  }, [permissionId, needsManualApprover, pushToast]);

  const canSubmit =
    !!permissionId &&
    !!reason.trim() &&
    (!needsManualApprover || !!selectedApproverId) &&
    !isSubmitting;

  async function handleSubmit() {
    if (!permissionId || !canSubmit) return;
    setIsSubmitting(true);
    try {
      await permissionRequestService.create({
        permission_id: permissionId,
        reason: reason.trim(),
        scope_ticket_id: ticketId,
        ...(needsManualApprover ? { selected_approver_id: selectedApproverId } : {}),
      });
      pushToast("Access request sent.", "success");
      onSubmitted();
    } catch (error) {
      pushToast(extractErrorMessage(error, "Couldn't send the request — try again."), "error");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isResolvingPermission) {
    return <p className="text-sm text-muted">Checking your current access…</p>;
  }

  if (!permissionId) {
    return (
      <p className="rounded-md2 border border-border bg-canvas px-3 py-2 text-[12px] text-muted">
        You already have access to this ticket.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {needsManualApprover ? (
        isLoadingApprovers ? (
          <p className="text-sm text-muted">Loading eligible reviewers…</p>
        ) : approvers.length === 0 ? (
          <p className="text-sm text-danger">
            No one is currently eligible to review this request.
          </p>
        ) : (
          <SelectInput
            label="Reviewer"
            hint="This ticket has no current owner, so pick who should review your request."
            value={selectedApproverId}
            onChange={(e) => setSelectedApproverId(e.target.value)}
          >
            {approvers.map((approver) => (
              <option key={approver.user_id} value={approver.user_id}>
                {approver.name} — {approver.role_name}
              </option>
            ))}
          </SelectInput>
        )
      ) : (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">
            Reviewer
          </p>
          <p className="mt-1 text-[13px] font-medium text-slate-800">
            {ticketOwnerName} (ticket owner)
          </p>
        </div>
      )}

      <TextArea
        label="Reason"
        hint="Why do you need to work on this ticket?"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="e.g. Covering for the assigned agent while they're out."
      />

      <div className="flex items-center justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          isLoading={isSubmitting}
          disabled={!canSubmit}
          onClick={handleSubmit}
        >
          Submit Request
        </Button>
      </div>
    </div>
  );
}
