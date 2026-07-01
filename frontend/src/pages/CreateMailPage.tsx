import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, MailPlus } from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { TextArea, TextInput } from "@/components/common/FormField";
import { useApiAction } from "@/hooks/useApiAction";
import { receiveIncomingEmail } from "@/api/email";
import type { EmailResponse } from "@/types";

// Active Viewer (client) users in the RBAC `users` table — the
// backend now looks senders up for real, so only emails that
// exist there with the Viewer role are accepted.
const DUMMY_SENDERS = [
  { email: "sophia.turner@probeps.com", label: "Sophia Turner (sophia.turner@probeps.com)" },
  { email: "viewer@probeps.com", label: "Viewer (viewer@probeps.com)" },
];

function randomMessageId() {
  return `msg-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

export function CreateMailPage() {
  const [fromEmail, setFromEmail] = useState(DUMMY_SENDERS[0].email);
  const [subject, setSubject] = useState("Unable to Login");
  const [body, setBody] = useState("Doctor cannot login to the patient portal.");
  const [lastResult, setLastResult] = useState<EmailResponse | null>(null);

  const { run, isLoading } = useApiAction(receiveIncomingEmail, {
    successMessage: (res) => `Email received. Routed to ${res.agent_name}'s inbox.`,
  });

  async function handleSend() {
    const result = await run({
      from_email: fromEmail,
      subject,
      body,
      message_id: randomMessageId(),
    });

    if (result) {
      setLastResult(result);
    }
  }

  return (
    <AppLayout
      title="Create Dummy Mail"
      description="Simulate an incoming client email to test the inbox workflow."
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
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-slate-600">
                Sender
              </span>
              <select
                value={fromEmail}
                onChange={(e) => setFromEmail(e.target.value)}
                className="w-full cursor-pointer rounded-md2 border border-border bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-xs transition-all focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10"
              >
                {DUMMY_SENDERS.map((sender) => (
                  <option key={sender.email} value={sender.email}>
                    {sender.label}
                  </option>
                ))}
              </select>
            </label>

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

            <div className="flex items-center justify-end border-t border-border pt-4">
              <Button variant="primary" isLoading={isLoading} onClick={handleSend}>
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
                  Email delivered to {lastResult.agent_name}
                </p>
                <p className="mt-0.5 text-xs text-muted">
                  From {lastResult.client_name} · status {lastResult.status}
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
