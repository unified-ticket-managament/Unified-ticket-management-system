# Phase 3 — Manual Live Outlook/Graph Test Checklist

This checklist covers everything the automated test suite (mocked Graph, no
network) cannot verify: real Outlook rendering, real Graph send/receive
behavior, and round-trip fidelity. Run this against the actual deployed app
with a real Graph-connected mailbox and a real Outlook client (desktop or
web). Nothing in this document has been executed — every row starts as
**NOT RUN** until you check it off with a real result.

Record results directly in this file (or a copy) as you go: ✅ Pass / ❌ Fail
(with a note) / ⏭️ Skipped (with why).

## 0. Setup

- [ ] Confirm which mailbox you're testing against (shared inbox / a
      specific client's dedicated inbox / a category inbox) and that it has
      a real, working Graph subscription (check `GET /api/mail/inbound-failures`
      shows no persistent failures for it).
- [ ] Have a second, real external mailbox available (e.g. a personal Gmail
      or Outlook.com account) to send from/to as "the client".
- [ ] Open the browser DevTools Network tab before each test that involves
      a send, so you can see the actual request/response if something looks
      wrong.

## 1. Attachment type matrix (new allow-list expansion)

For each row, attach the file to a Compose email in the app and send it to
your external test mailbox, then open it in real Outlook.

| Type | File to attach | Accepted by picker? | Uploads OK? | Arrives in Outlook? | Opens/renders correctly? |
|---|---|---|---|---|---|
| Presentation | a real `.pptx` | | | | |
| Legacy presentation | a real `.ppt` | | | | |
| OpenDocument text | a real `.odt` | | | | |
| Rich text | a real `.rtf` | | | | |
| Image (new) | a real `.webp` | | | | |
| Image (new) | a real `.heic` (e.g. an iPhone photo) | | | | |
| Image (new, security-sensitive) | a real `.svg` | | | | see note below |
| Video | a small real `.mp4` | | | | |
| Audio | a small real `.mp3` | | | | |
| Archive | a real `.zip` (regression) | | | | |
| Archive (new) | a real `.rar` or `.7z` | | | | |
| Code/text (new) | a real `.json` or `.py` | | | | |
| Macro-enabled (must be rejected) | a real `.docm` | rejected? | n/a | n/a | n/a |
| Outlook binary (must be rejected) | a real `.msg` | rejected? | n/a | n/a | n/a |
| Executable (must be rejected) | a real `.exe` | rejected? | n/a | n/a | n/a |

**SVG-specific check**: after sending the `.svg`, open it from the app's own
Mail message view (not Outlook) — confirm it shows as a download-link/icon,
**never** as an inline `<img>` thumbnail preview. This is the security
carve-out (`NEVER_INLINE_EXTENSIONS`) — a real regression here is a genuine
security issue, not just a cosmetic one.

- [ ] Attach a file just under 30MB — confirm it's accepted.
- [ ] Attach a file just over 30MB — confirm it's rejected client-side with
      a message naming 30MB (not a stale "25MB").
- [ ] Attach 10 files at once — confirm all 10 are accepted.
- [ ] Attempt to attach an 11th file — confirm it's rejected with a clear
      "maximum of 10 files" message.

## 2. Inline images / signatures

- [ ] Send a Compose/Reply with your normal email signature (including any
      logo image) from the app. Open the received email in real Outlook —
      confirm the logo renders inline in the signature area, **not** as a
      separate downloadable attachment.
- [ ] Paste a screenshot directly into the message body composer, send it.
      Confirm it renders inline in Outlook, not as an attachment.
- [ ] Send a message with **two** different pasted/inline images. Confirm
      both render inline, in the correct positions, in Outlook.
- [ ] Send a message with one inline image **and** one normal file
      attachment together. Confirm the inline image renders in the body and
      the file attachment shows separately as a real attachment — not
      conflated.

## 3. HTML / rich content preservation

- [ ] Compose a message using the app's rich text editor with: a table with
      visible borders, a bulleted list, a numbered list, bold/italic text,
      a hyperlink, and at least one colored/highlighted span. Send it and
      open in Outlook — confirm every element renders correctly (table
      borders visible, list formatting intact, link clickable).
- [ ] From real Outlook, send a message *to* the app's mailbox containing:
      a table (with borders), a numbered list, and an inline image — using
      Outlook's own compose window (not plain text). Confirm the message
      appears correctly formatted when opened in the app's Mail view (table
      borders preserved on read even though outbound sanitization
      deliberately doesn't force them on inbound).
- [ ] From Outlook, paste content copied directly from a Word document
      (with its own formatting) into a new email and send it to the app.
      Confirm the app's Mail view shows readable, reasonably-preserved
      formatting (not raw HTML tags, not stripped to plain text).
- [ ] From Outlook, paste a range copied from Excel (a small grid of cells)
      into an email and send it to the app. Confirm it renders as a table,
      not garbled text.
- [ ] Attempt to verify the sanitizer holds: send a test message (from a
      tool you control, or ask someone with API access to craft one) whose
      HTML body contains a `<script>` tag or an `onerror` attribute on an
      `<img>`. Confirm the app's Mail view does **not** execute it and does
      **not** render the raw tag as visible text artifacts.

## 4. Attachment size / count boundaries (Graph-specific)

- [ ] Send an email with one attachment just under 3MB (the inline-embed
      threshold) — confirm it's delivered and opens correctly in Outlook.
- [ ] Send an email with one attachment just over 3MB but under 30MB
      (forces the Graph upload-session/draft path) — confirm delivery and
      that it opens correctly (this exercises real chunked upload, not just
      the mocked path the unit tests cover).
- [ ] Send an email with **two** attachments, one under 3MB and one over —
      confirm both arrive intact in the same email.
- [ ] Send an email with multiple attachments whose combined size is large
      (e.g. three ~8MB files) — confirm none are silently dropped (this is
      exactly the "no silent attachment loss" fix — watch for a clean error
      if something *should* fail, never a "successful" send missing a file).

## 5. Inbound mail scenarios

- [ ] Send a plain-text email from Outlook to the app's mailbox — confirm
      it appears correctly in Mail with no formatting artifacts.
- [ ] Send an HTML email with a signature block (including a logo image)
      from Outlook — confirm the signature image renders inline in the
      app's Mail view.
- [ ] Send an email with a normal file attachment, then with multiple
      attachments — confirm both are listed and downloadable from the app.
- [ ] Send an email with a OneDrive/SharePoint "Share as link" attachment
      (not a real file attachment) — confirm the app shows it as a distinct
      "linked attachment" (opens in a new tab to OneDrive), not a broken
      download.
- [ ] Forward an existing email as a nested/attached message from Outlook
      ("Attach as email" / forward as attachment) to the app — confirm the
      app receives a downloadable `.eml` file for it.
- [ ] If you have access to a client that still sends winmail.dat/TNEF
      (e.g. certain older Exchange configurations), send one — confirm the
      app stores it as an opaque downloadable file (expected: it will
      **not** render its rich content — this is a known, documented
      limitation, not a bug to chase).
- [ ] Send an email to multiple To recipients (including the app's mailbox)
      plus a Cc — confirm both are visible/correct in the app's message
      details.
- [ ] Send from an external (non-company) domain — confirm normal routing.
- [ ] If a shared/category mailbox is configured, send directly to it and
      confirm correct routing/visibility.
- [ ] Reply to an existing app-originated email from within Outlook —
      confirm the reply threads correctly onto the same conversation/ticket
      in the app (not a duplicate/orphaned thread).
- [ ] Forward an app-originated email (inline, not as attachment) from
      Outlook to a third party, then have that third party reply — confirm
      it's handled sensibly (the app's own threading is scoped to its own
      mailbox's conversation, so verify this doesn't silently misroute).

## 6. Outbound mail scenarios

For each of Compose, Reply, Reply All, and Forward, from the app:

- [ ] Send plain text — verify received cleanly in Outlook.
- [ ] Send with a table (bordered) — verify table renders with borders.
- [ ] Send with your signature (incl. image) — verify inline, not attached.
- [ ] Send with a pasted screenshot — verify inline.
- [ ] Send with one normal attachment — verify received correctly.
- [ ] Send with mixed inline + normal attachments — verify both correct.
- [ ] Send with a large (>3MB) attachment — verify received correctly.
- [ ] Send to an external To address — verify delivery.
- [ ] Send with an external Cc — verify the Cc recipient actually receives
      a copy (not just displayed in the app).
- [ ] Send with a Bcc — verify the Bcc recipient receives it and that
      neither the To nor Cc recipients can see the Bcc address.
- [ ] **Reply All** specifically: verify the original message's other
      recipients (beyond the sender) are actually included, matching what
      the app's Cc field showed you before sending.

## 7. Recipient-validation error display (the fix from this pass)

- [ ] In Compose, enter a recipient with a clearly bad/non-existent domain
      (e.g. `someone@thisdomaindoesnotexist12345.com`) in **To**. Click
      Send. Confirm a clear, visible error toast appears within a few
      seconds (not 15+ seconds, not silently nothing) reading something
      like "Enter a valid email address or check the domain: ...".
- [ ] Repeat the same check with the bad domain in **Cc**.
- [ ] Repeat the same check with the bad domain in **Bcc**.
- [ ] Repeat in the **Forward** dialog's recipient field.
- [ ] Enter **three or more** bad-domain-but-real-looking addresses across
      To/Cc/Bcc at once and confirm the error still appears promptly (not
      stacking to a long multi-address delay).
- [ ] As a control, confirm a normal, valid recipient still sends
      successfully with no error and no unusual delay.

## 8. Round-trip fidelity

- [ ] **Outlook → App → Reply → Outlook**: send an HTML email with a table
      and an inline image from Outlook to the app, reply from the app, and
      confirm the reply arrives in Outlook correctly threaded (same
      conversation), with correct subject (Re: prefix), sender, and any
      reply content/attachments intact.
- [ ] **Outlook → App → Forward → Outlook**: same setup, but Forward from
      the app to a third address — confirm the forwarded email in Outlook
      shows the quoted original content, correct attachments carried over,
      and correct new recipient.
- [ ] **App → Outlook → Reply → App**: Compose from the app to your test
      Outlook mailbox, reply from Outlook, confirm the reply threads onto
      the same conversation/ticket in the app (not a new, disconnected
      thread).
- [ ] **App → Outlook → Forward → App**: Compose from the app, forward from
      Outlook to the app's own mailbox, confirm it's received and — if
      relevant — check whether/how it threads.
- [ ] For each round-trip above, spot-check: subject preserved, sender
      correct, CC preserved where applicable, attachment filenames and
      count unchanged, inline-vs-normal attachment classification
      unchanged.

## 9. Final sign-off

- [ ] No unexpected console errors in the browser during any of the above.
- [ ] No attachment silently went missing from any sent email (cross-check
      what you attached vs. what arrived).
- [ ] No dangerous file type (macro-enabled Office, `.msg`, executable) was
      ever accepted anywhere in this pass.

---

**When you're done**: report back which rows passed, which failed (with
what you actually saw), and which you skipped and why. Only checked, real
results here can upgrade any claim in the Phase 3 final report from
`NOT VERIFIED` to a verified status — an unchecked box stays `NOT VERIFIED`
regardless of how the code looks.
