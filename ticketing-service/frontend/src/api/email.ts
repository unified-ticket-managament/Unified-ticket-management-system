import { apiClient } from "./client";
import type { EmailRequest, EmailResponse } from "@/types";

// POST /emails/dummy — the internal "Create Dummy Mail" simulator,
// Site Lead only (backend-enforced). Runs through the exact same
// EmailService.receive_email as the real transport route
// (POST /emails/incoming), which stays unauthenticated for the
// future Graph/n8n webhook and is never called from this UI.
export async function receiveIncomingEmail(
  payload: EmailRequest & { files?: File[] }
): Promise<EmailResponse> {
  const formData = new FormData();
  formData.append("to_email", payload.to_email);
  formData.append("from_email", payload.from_email);
  if (payload.from_name) formData.append("from_name", payload.from_name);
  formData.append("subject", payload.subject);
  formData.append("body", payload.body);
  if (payload.html_body) formData.append("html_body", payload.html_body);
  formData.append("message_id", payload.message_id);
  if (payload.received_at) formData.append("received_at", payload.received_at);
  if (payload.in_reply_to) formData.append("in_reply_to", payload.in_reply_to);
  if (payload.references) formData.append("references", payload.references);
  (payload.files ?? []).forEach((file) => formData.append("files", file));

  const { data } = await apiClient.post<EmailResponse>("/emails/dummy", formData);
  return data;
}
