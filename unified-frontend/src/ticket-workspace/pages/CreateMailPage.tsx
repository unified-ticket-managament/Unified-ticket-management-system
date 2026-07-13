import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, MailPlus, ShieldAlert } from "lucide-react";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { Card } from "@tw/components/common/Card";
import { Button } from "@tw/components/common/Button";
import { EmptyState } from "@tw/components/common/EmptyState";
import { TextArea, TextInput, SelectInput } from "@tw/components/common/FormField";
import { FileDropzone } from "@tw/components/common/FileDropzone";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { receiveIncomingEmail } from "@tw/api/email";
import { validateFiles } from "@tw/lib/attachmentMeta";
import type { EmailResponse } from "@tw/types";

function randomMessageId() {
  return `<msg-${Date.now()}-${Math.floor(Math.random() * 10000)}@dummy.local>`;
}

// Only Site Lead gets the dummy-mail simulator (see
// ../../lib/role-access.ts's NAV_ITEMS_BY_ROLE
// and the dashboard catch-all page's slug carve-out) — this is the
// defense-in-depth check for anyone who navigates here directly. The
// backend enforces the same rule on POST /emails/dummy (403s for any
// other role), so this is UX, not the real gate.
const ALLOWED_ROLES = ["Site Lead"];

export function CreateMailPage() {
  const { currentUser } = useAuthContext();
  // `clients` used to be fetched independently on every mount of this
  // page — it's now shared, session-wide lookup data fetched once by
  // WorkflowContext instead (see that context's own comment).
  const { clients } = useWorkflowContext();
  const [toEmail, setToEmail] = useState("");
  const [fromEmail, setFromEmail] = useState("mary.j@abcclinic.com");
  const [fromName, setFromName] = useState("Mary Johnson");
  const [subject, setSubject] = useState("Unable to Login");
  const [body, setBody] = useState("Doctor cannot login to the patient portal.");
  const [inReplyTo, setInReplyTo] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [lastResult, setLastResult] = useState<EmailResponse | null>(null);

  useEffect(() => {
    if (clients.length > 0) {
      setToEmail((current) => current || clients[0].inbox_email);
    }
  }, [clients]);

  const { run, isLoading } = useApiAction(receiveIncomingEmail, {
    successMessage: (res) => `Email delivered to ${res.client_name}'s inbox.`,
  });

  const canSend = validateFiles(files).errors.length === 0 && Boolean(toEmail);

  async function handleSend() {
    const result = await run({
      to_email: toEmail,
      from_email: fromEmail,
      from_name: fromName || undefined,
      subject,
      body,
      message_id: randomMessageId(),
      received_at: new Date().toISOString(),
      in_reply_to: inReplyTo || undefined,
      files,
    });

    if (result) {
      setLastResult(result);
      setFiles([]);
      setInReplyTo("");
    }
  }

  if (!ALLOWED_ROLES.includes(currentUser?.role ?? "")) {
    return (
      <AppLayout title="Create Dummy Mail">
        <EmptyState
          icon={<ShieldAlert size={22} />}
          title="Not available for your role"
          description="Only Site Lead can create dummy mail."
        />
      </AppLayout>
    );
  }

  return (
    <AppLayout
      title="Create Dummy Mail"
      description="Simulate an incoming client email to test the inbox workflow — this is the local stand-in for the real transport layer."
    >
      <div className="mx-auto flex max-w-xl flex-col gap-5">
        <Card
          title="New Incoming Email"
          eyebrow="Simulator"
          actions={
            <div className="flex h-8 w-8 items-center justify-center rounded-md2 bg-accent/10 text-accent">
              <MailPlus size={15} />
            </div>
          }
        >
          <div className="flex flex-col gap-4">
            {clients.length === 0 ? (
              <p className="rounded-md2 border border-warning/20 bg-warning/5 px-3.5 py-2.5 text-xs text-slate-700">
                No clients onboarded yet — create one via <code>POST /clients</code> before
                sending a dummy email.
              </p>
            ) : (
              <SelectInput
                label="To (shared inbox address)"
                value={toEmail}
                onChange={(e) => setToEmail(e.target.value)}
                hint="Which client's dedicated inbox this email arrives at — this is what routes it to their Account Manager."
              >
                {clients.map((client) => (
                  <option key={client.client_id} value={client.inbox_email}>
                    {client.name} ({client.inbox_email})
                    {client.account_manager_active ? "" : " — ⚠ AM inactive"}
                  </option>
                ))}
              </SelectInput>
            )}

            <div className="grid grid-cols-2 gap-3">
              <TextInput
                label="From (sender email)"
                value={fromEmail}
                onChange={(e) => setFromEmail(e.target.value)}
              />
              <TextInput
                label="From (sender name)"
                value={fromName}
                onChange={(e) => setFromName(e.target.value)}
              />
            </div>

            <TextInput
              label="Subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />

            <TextArea
              label="Message"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />

            <TextInput
              label="In-Reply-To (optional)"
              placeholder="Paste a previous outbound Message-ID to test threading"
              value={inReplyTo}
              onChange={(e) => setInReplyTo(e.target.value)}
              hint="Leave blank for a brand-new conversation. Set this to an earlier reply's message_id to simulate the client answering it."
            />

            <FileDropzone label="Attachments" files={files} onFilesChange={setFiles} />

            <div className="flex items-center justify-end border-t border-border pt-4">
              <Button
                variant="primary"
                isLoading={isLoading}
                disabled={!canSend}
                onClick={handleSend}
              >
                <MailPlus size={15} /> Receive Email
              </Button>
            </div>
          </div>
        </Card>

        {lastResult && (
          <div className="flex items-center justify-between gap-3 rounded-md2 border border-success/20 bg-success/5 px-5 py-4 shadow-xs animate-fadeSlideIn">
            <div className="flex items-center gap-3">
              <CheckCircle2 size={20} className="flex-none text-success" />
              <div>
                <p className="text-sm font-semibold text-slate-900">
                  Delivered to {lastResult.client_name}'s shared inbox
                </p>
                <p className="mt-0.5 text-xs text-muted">
                  status {lastResult.status}
                  {lastResult.ticket_id ? ` · landed on an existing ticket` : ""}
                  {lastResult.threaded_under ? ` · threaded under an earlier email` : ""}
                  {lastResult.attachments && lastResult.attachments.length > 0
                    ? ` · ${lastResult.attachments.length} file${lastResult.attachments.length === 1 ? "" : "s"} attached`
                    : ""}
                </p>
              </div>
            </div>
            <Link to="/inbox">
              <Button variant="secondary" size="sm">
                View in Inbox <ArrowRight size={13} />
              </Button>
            </Link>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
