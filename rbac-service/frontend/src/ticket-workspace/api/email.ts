import { apiClient } from "./client";
import type { EmailRequest, EmailResponse } from "@tw/types";

// POST /emails/incoming
export async function receiveIncomingEmail(
  payload: EmailRequest & { files?: File[] }
): Promise<EmailResponse> {
  const formData = new FormData();
  formData.append("from_email", payload.from_email);
  formData.append("subject", payload.subject);
  formData.append("body", payload.body);
  formData.append("message_id", payload.message_id);
  (payload.files ?? []).forEach((file) => formData.append("files", file));

  const { data } = await apiClient.post<EmailResponse>("/emails/incoming", formData);
  return data;
}
