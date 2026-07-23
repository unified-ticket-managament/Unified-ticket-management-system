# Outbound Email Delivery Issue — `ticketing@probeps.com`

**For**: Microsoft 365 tenant administrator
**Issue**: Emails sent via Microsoft Graph from `ticketing@probeps.com` are accepted by Exchange Online and appear in **Sent Items**, but never arrive at external Gmail recipients.

## Summary

Our application sends outbound email through Microsoft Graph's `sendMail` API using the app-registered mailbox `ticketing@probeps.com`. Every send returns a successful `202 Accepted` from Graph, and we've independently confirmed each message is placed in that mailbox's real **Sent Items** folder (checked directly via the Graph API, not just our own application logs). Despite this, the external Gmail recipients report never receiving these emails — not in Inbox, not in Spam.

This means the message is getting **past our application and past Graph's initial acceptance**, but something between Exchange Online's outbound transport and the recipient's mailbox is dropping, blocking, or quarantining it. We have no visibility into that layer — it requires Exchange admin tooling we don't have access to.

## What we've confirmed (evidence)

| Sent (UTC) | Subject | To | Present in Sent Items? |
|---|---|---|---|
| 2026-07-22 10:42:53 | Re: Check the reply email | devaharshavardhan007@gmail.com | ✅ Yes |
| 2026-07-22 10:26:24 | Re: Higher level working | devaharshavardhan007@gmail.com | ✅ Yes |
| 2026-07-22 10:25:03 | Re: Discrepancy in July Invoice | vijayalakshmigogineni2005@gmail.com | ✅ Yes |
| 2026-07-22 10:21:36 | Re: Higher level working | devaharshavardhan007@gmail.com | ✅ Yes |
| 2026-07-22 09:55:09 | Re: Working on email intergation.. | devaharshavardhan007@gmail.com | ✅ Yes |

All confirmed present in Sent Items with real Exchange-assigned Message-IDs (e.g. `<BM1PR01MB4900...@BM1PR01MB4900.INDPRD01.PROD.OUTLOOK.COM>`). **None of these were received by the external recipient.**

## What we cannot check ourselves

Our application only has Graph API `Mail.Send`/`Mail.Read` application permissions on this mailbox. We have **no access** to:
- Exchange admin center (Mail flow → Message Trace)
- Microsoft 365 Defender (Restricted entities, anti-spam policies)
- Exchange Online PowerShell (`Get-MessageTrace`)

These all require an Exchange Administrator (or Global Administrator) login.

## What we're asking you to check

1. **Message Trace** (Exchange admin center → Mail flow → Message trace) for sender `ticketing@probeps.com`, last 24 hours — this will show the actual delivery status (Delivered / Pending / Failed / **Quarantined**) for each message above.
2. **Restricted entities** (Defender → Email & collaboration → Review → Restricted entities) — a very common cause: M365 auto-restricts a mailbox from sending externally after unusual outbound activity, which our testing (several rapid sends to external Gmail addresses) may have triggered.
3. **Outbound spam filter policy** (Defender → Policies & rules → Anti-spam → Outbound) — check recipient/rate limits and whether external recipients are restricted for this mailbox.
4. **SPF / DKIM / DMARC** configuration for the domain backing `ticketing@probeps.com` — if not properly set up, Gmail may silently drop or junk the message rather than bounce it, which would look exactly like this from our side.

Message Trace (#1) is the fastest way to get a definitive answer — it will state in plain terms what happened to each message after Exchange Online accepted it.

## Update — 2026-07-22

We confirmed **item #2 (Restricted entities)**: the mailbox is *not* being blocked from sending externally. However, replies sent to a personal test mailbox are still not arriving, so the root cause is still open.

**Still needed — please check specifically:**

1. **Message Trace status** (not just "is the mailbox restricted") for the exact messages in the table above — Exchange admin center → Mail flow → Message trace, or `Get-MessageTrace -SenderAddress ticketing@probeps.com -StartDate ... -EndDate ...` in Exchange Online PowerShell. We need the per-message **status** column specifically: `Delivered`, `Pending`, `Failed`, or `Quarantined` — and if `Quarantined`, the reason code shown in the trace detail.
2. **SPF / DKIM / DMARC** for the domain backing `ticketing@probeps.com` — if DKIM isn't signing outbound mail or SPF doesn't authorize Exchange Online as a sender for this domain, Gmail can silently drop or junk the message with no bounce back to us, which matches this symptom exactly. A quick check: `dig TXT probeps.com` (SPF) and the DKIM signing status in Exchange admin center → Mail flow → DKIM.

Restricted entities being clear is good news, but it doesn't explain the missing mail on its own — one of these other two almost certainly does.
