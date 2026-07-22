# Button & Action Guide — Unified Ticket Management System (UTMS)

This is a plain-English walkthrough of every button, toggle, and clickable action in the application — what it does, why it's there, and who is allowed to use it. It covers the app most people actually use day to day: the **unified-frontend** shell (login, navigation, admin pages) plus the **embedded Ticket Workspace** (Tickets, Mail, SLA/Escalation) that Staff, Team Leads, and Account Managers land on after signing in.

## Who's who (the roles mentioned throughout)

From most to least access: **Super Admin** → **Site Lead** → **Account Manager** → **Team Lead** → **Staff**, plus **Viewer**, a separate, restricted role for people who only need to see their own profile. Most buttons are visible to everyone who reaches a given page; where a button is restricted, this guide says exactly who can see or use it.

A few conventions used throughout:
- **"Doesn't render at all"** means the button is completely invisible to someone without the right role/permission — not greyed out, just not there.
- **"Disabled"** means the button is visible but greyed out, usually with a tooltip explaining why.
- Several settings described below are cosmetic only (they don't yet connect to a real backend feature) — each one is flagged clearly where that's the case, so nobody is surprised that toggling it doesn't do more than it appears to.

---

## 1. Signing In

**Login page** (the very first screen, before you're signed in):

| Button/Control | What happens | Why it's there |
|---|---|---|
| Eye icon in the password field | Shows or hides the password you've typed | Lets you double-check you typed your password correctly before submitting |
| "Remember me" checkbox | Saves your email address in this browser for next time | Saves you from retyping your email every time you visit |
| **Login** | Checks your email/password and, if correct, takes you into the app | The actual sign-in action |
| "Forgot Password?" | Shows a message telling you to contact your system administrator | There is no self-service password reset yet — this button only displays that message, it does not start a reset process |

---

## 2. Getting Around the App

### Sidebar (left-hand menu)

The sidebar shows a different set of links depending on your role. Possible items include: Dashboard, Users, Reports, Mail (Inbox), Interactions, Tickets, Ticket Audit Log, SLA Timing Matrix (Super Admin only), Reporting Managers (Super Admin/Site Lead only), and Permission Requests (shown here only for Viewers — everyone else reaches it via a button on the Users page instead).

| Button/Control | What happens | Who sees it | Why it's there |
|---|---|---|---|
| Any sidebar link | Takes you straight to that section of the app | Varies by role — see above | Quick navigation between the major parts of the product |
| Collapse/expand arrow (small circular button on the sidebar's edge) | Shrinks the sidebar down to icons-only, or expands it back to full labels | Everyone, desktop only | Frees up screen space for the main content when you don't need the full labels |
| **Logout** (bottom of sidebar) | Signs you out and returns you to the login page | Everyone | Ends your session on this device |
| Hamburger/menu icon (phone/tablet screens only) | Opens the sidebar as a slide-in panel | Everyone, mobile only | The sidebar is hidden by default on small screens to save space — this opens it |

### Top bar

| Button/Control | What happens | Why it's there |
|---|---|---|
| Bell icon (notifications) | Opens a list of your recent notifications (real, backend-driven — refreshes automatically every 30 seconds) | Lets you check for new alerts (ticket assignments, SLA warnings, permission decisions) without leaving your current page |
| "Mark all read" (inside the bell dropdown, only shown if you have unread notifications) | Clears the "unread" indicator on every notification at once | For when you've seen everything and don't need the reminder badge anymore |
| "Clear all" (inside the bell dropdown) | Empties the visible notification list | A "clean slate" button — note this only hides them on your screen; there's no server-side delete, so it's a personal view-cleanup, not a permanent deletion |
| Clicking a notification row | Marks it read and takes you straight to whatever it's about (a ticket, a message, etc.) | Fastest way to act on an alert |
| "X" on a notification row | Dismisses just that one notification | Lets you clear one item without affecting the others |
| Avatar (top-right) | Opens a small "My Account" menu | Quick access to your profile and logout from any page |
| "Profile" (in the avatar menu) | Takes you to your Profile page | Reach your own details/preferences |
| "Logout" (in the avatar menu) | Same as the sidebar's Logout | A second, always-visible way to sign out |

### Breadcrumbs

Wherever a breadcrumb trail appears (e.g. "Dashboard > Users > Jane Doe"), clicking any earlier part of the trail jumps back to that page — a shortcut instead of using your browser's Back button.

---

## 3. Home Dashboard

There is one dashboard design shared by Super Admin, Site Lead, Account Manager, Team Lead, and Staff (each just sees numbers scoped to their own clients/team/tickets); Viewer sees a much simpler version.

| Button/Control | What happens | Why it's there |
|---|---|---|
| KPI tiles at the top (Open Tickets, Resolved Today, In Progress, Closed, and the SLA Overview tiles: Running/Paused/At Risk/Breached/Escalated/Completed) | **Not clickable** — display only | At-a-glance counts, nothing to click through |
| "Needs Attention" list rows | Opens that specific ticket | Jump straight to a ticket flagged as urgent |
| "Tickets by Priority" chart | Not clickable — hover shows the exact number | Visual breakdown of current workload |
| "Recent Activity" feed | Not clickable, despite looking hoverable | Situational awareness of who did what recently |
| "View all" link (Recent Assigned Tickets card) | Opens the ticket list | Escape hatch to see the full list beyond the dashboard summary |
| "Recent Assigned Tickets" rows | Opens the ticket list | *Known quirk: every row currently links to the same generic ticket list page rather than deep-linking to that specific ticket — worth knowing if it doesn't behave like a per-ticket shortcut.* |
| **View Profile** card (Viewer's dashboard only) | Opens your Profile page | This is the only clickable control a Viewer has on their dashboard |

---

## 4. Tickets — the core of the product

This is the Ticket Workspace's own ticket list and detail pages (reached via the sidebar's "Tickets" link) — the real, backend-connected product that Staff/Team Leads/Account Managers work in all day.

### 4.1 Ticket List

**Tabs** at the top of the list:

| Tab | Who sees it | What it shows |
|---|---|---|
| **Open Pool** | Everyone | Unclaimed, open tickets available to pick up. (A ticket that's both unclaimed *and* escalated is deliberately excluded from here — it only appears on the Escalated tab instead.) |
| **My Tickets** | Everyone | Tickets you personally own |
| **All** | Everyone | Every ticket your role is allowed to see |
| **Escalated** | Team Lead, Account Manager, Site Lead, Super Admin (or anyone individually granted the matching permission) | Tickets currently going through the escalation process |

**Filters and sorting:**

| Control | What it does |
|---|---|
| Search box | Finds tickets by ID, subject, or client name |
| Status / Priority / Category / Date-range filters | Narrow the list (Category is hidden for Team Lead/Staff since they only ever see their own category anyway) |
| **Reset** | Clears every filter back to default |
| Column headers (Subject, Last Updated) | Click to sort by that column |

**Actions on each ticket row:**

| Button | Shown when | What happens | Why it's there |
|---|---|---|---|
| **Claim** | The ticket has no owner yet | Assigns the ticket to you | Take ownership of an unclaimed ticket |
| **Acknowledge** | The ticket is actively escalated **and the escalation chain has reached you specifically** (not just "this ticket is escalated") | Opens the two-step Acknowledge & Assign window (see section 4.6) | Formally accept an escalated ticket and decide who takes it from here |
| **View** | Always | Opens the ticket's full detail page | — |
| **Interactions** (message icon) | Always | Opens this ticket's full conversation history as its own page | For reviewing a long back-and-forth without the smaller tab view |
| Clicking anywhere else on the row | Always | Same as View | Faster way to open a ticket |

### 4.2 Ticket Detail — top action bar

| Button | What happens | Why it's there | Who can use it / when it's hidden |
|---|---|---|---|
| **Back** | Returns to whatever page you came from | Simple navigation | Everyone |
| **Change Status** | Opens a small picker for Open / In Progress / Pending / Waiting for Client / Resolved (Closed is deliberately excluded — see Close Ticket below) | Moves the ticket through its normal workflow | Disabled if the ticket is closed, or if you're currently frozen out (see "frozen ticket" note below) |
| **Change Priority** | Opens a picker for Low / Medium / High (**Critical is never a manual option** — it's set automatically only when a ticket escalates) | Re-rank how urgent the ticket is | Requires the "change priority" permission; disabled if closed or frozen |
| **Claim Ticket** | Assigns the ticket to you directly | Take ownership | Only shown if the ticket is unclaimed |
| **More ▼** | Opens a menu of secondary actions (below) | Keeps the toolbar uncluttered | Everyone |
| ↳ **Upload Attachment** | Opens a file picker/drag-and-drop panel | Attach a file to the ticket | Disabled if closed or frozen |
| ↳ **Assign to Staff / Transfer Ticket** | Opens a form: pick a new owner, write a required reason, confirm | Hand the ticket to someone else, with the reason logged for the record | Staff need the "transfer" permission; everyone else can use it; disabled if closed/frozen |
| ↳ **Edit Access** | Opens the Edit Access panel (section 4.5) | Manage or request temporary permission to work on someone else's ticket | Disabled if closed |
| ↳ **Close Ticket** | Confirms, then marks the ticket fully done and read-only | Finish and lock a ticket | Site Lead/Super Admin always allowed; Account Manager/Team Lead/Staff need the "close ticket" permission |
| ↳ **Reopen Ticket** | Confirms, then brings a closed ticket back to an active state | Undo a close if more work is needed | Same permission pattern as Close, only shown on already-closed tickets |

**"Frozen ticket" explained**: once a ticket is escalated but not yet acknowledged by a supervisor, its previous owner (if not a supervisor themselves) is temporarily locked out of most actions until a Team Lead/Account Manager/Site Lead/Super Admin acknowledges it. This prevents someone from continuing to work a ticket that's already been kicked upstairs.

### 4.3 Ticket Detail — the five tabs

| Tab | What's in it | Buttons |
|---|---|---|
| **Timeline** | The ticket's conversation history | Click any entry to see full details; a **Hide** (eye-with-slash icon) button lets you soft-remove one message from the visible timeline; an "Interactions" link jumps to the full-page conversation view |
| **Audit Log** | Every status/priority change, transfer, claim, and escalation event, with before/after values | Read-only — no buttons, auto-refreshes every 10 seconds |
| **Reply** | Write a reply to the client | "To" contact picker, CC/BCC fields, attach files, **Send Reply**. If the ticket is closed, this whole panel is replaced with a locked message instead. |
| **Internal Note** | Leave a team-only note (never seen by the client) | Subject + note text, an optional To/CC/BCC picker (this recipient info is for your team's own reference only — it isn't actually sent anywhere), attach files, **Add Note** |
| **Attachments** | Every file attached to the ticket | **Download** on each file; **Delete** only for people holding the specific "archive attachment" permission — note this is a stricter check than most other actions, with no ownership-based fallback |

### 4.4 Related Tickets

*(This panel exists in the code but has been removed from the visible sidebar in the current layout — flagging in case it resurfaces.)* When present, it lets you **Link** another ticket that covers the same underlying issue, and **Unlink** it later; clicking a linked ticket's title opens it.

### 4.5 Edit Access panel

Lets someone temporarily get permission to work on a ticket they don't already have access to.

| Button | Shown to | What happens |
|---|---|---|
| **Request Edit Access** | Anyone without access and no pending request already (disabled if ticket closed) | Opens a form for a required reason, then submits the request |
| **Approve** | Reviewers (people holding the "edit other ticket" permission) | Grants the requester access |
| **Reject** | Same reviewers | Denies the request |

### 4.6 SLA & Escalation panel (right-hand sidebar of the ticket page)

| Button | Shown when | What happens | Why it's there |
|---|---|---|---|
| **Resume** | The Resolution SLA clock is currently paused | Un-pauses the clock | Undo a supervisor's manual pause. Requires Site Lead/Super Admin, or the "change SLA" permission for others |
| **Escalate** | You hold the "escalate" permission, no escalation is already active, and the SLA clock isn't already completed | Manually starts the escalation process and permanently bumps the ticket's priority to Critical | For raising a ticket to a supervisor's attention even before an automatic SLA breach |
| **Acknowledge & Assign** | An escalation is active **and you are specifically listed as its current owner** (strictly — there is no "Site Lead/Super Admin can act on anything" bypass here) | Opens a two-step window: **Step 1 — Acknowledge** (confirms you've seen it and stops it from auto-advancing further up the chain, but does not yet restart any clocks), then **Step 2 — pick who owns it going forward** ("Myself" or a role-grouped list of eligible people) and **Confirm** (this is the step that actually restarts the ticket's real SLA timers) | Ensures an escalated ticket is genuinely picked up by someone specific, not just silently acknowledged with no one clearly responsible |

Everything else in this panel (SLA progress bars, countdown timers, escalation details) is informational display only.

### 4.7 Interactions & Ticket Audit Log pages (full-page views)

| Page | Buttons |
|---|---|
| **Interactions** (all conversations across every ticket) | Search and filter controls; **Retry** if a load fails; clicking a row opens its details; a **Hide** icon soft-removes a row; **Expand** opens the same interaction as its own full page; Previous/Next pagination |
| **Full Interaction page** | **Back** (returns to the Interactions list), **Minimize** (collapses back into the small side panel without losing your place), **Close** (closes out entirely) |
| **Ticket Audit Log** (company-wide page, `/dashboard/audit-logs`) | **View Centralized Audit Log** / **Back to My Scoped Audit Log** toggle — lets someone who normally only sees their own scope temporarily see the unrestricted, company-wide trail, but only if they hold the specific permission for it (otherwise the button is disabled with an explanatory tooltip); search/filter controls; **Refresh**; clicking a row opens full detail; pagination |

---

## 5. Mail (Inbox)

The redesigned two-panel Mail experience — a folder list on the left, messages in the middle/right.

### 5.1 Sidebar & message list

| Button/Control | What happens | Why it's there |
|---|---|---|
| **Compose** (pencil icon) | Opens a blank new-message form | Start a brand-new email |
| Folder buttons (Inbox, Unassigned, My Claims, Sent, Drafts, Replied, Ticketed, Archived, System) | Switches which set of messages you're viewing | Organize mail by its status. "My Claims" is hidden for Staff, since their assigned tickets already serve that purpose. |
| **All Inboxes** | Site Lead/Super Admin only | Shows every client's mail company-wide, for oversight |
| **Refresh** | Reloads the current folder | Pull the latest mail immediately instead of waiting |
| Search box | Filters by sender/subject/body | Find a specific message |
| **Sort** dropdown | Newest / Oldest / Sender A–Z | Reorder the visible list |
| **Client** dropdown | Narrows to one client's mail | — |
| **Filters** panel | Priority, Category, SLA risk, date received, unread-only, has-attachments | Narrow by multiple criteria at once |
| **Clear all filters** | Resets every active filter at once | One-click reset |
| Clicking a message row | Opens it | Read/reply to that message |
| Previous / Next | Pages through the list | — |

### 5.2 Reading a message

| Button | What happens | Who can use it |
|---|---|---|
| Add/remove a tag | Labels the message for later filtering | Everyone |
| Folder picker | Files the message into a personal folder | Everyone |
| **Reply** | Opens a reply addressed to the original sender only | Requires the "reply externally" permission; disabled if the linked ticket is closed |
| **Reply All** | Same, but keeps everyone originally CC'd in the loop | Same as Reply |
| **Forward** | Opens a new message pre-filled with this one's content, quoted | Everyone |
| **Create Ticket** | Opens a dialog to turn this email into a formal ticket, or attach it to one that already exists | Requires the "convert to ticket" or "attach to ticket" permission |
| **View Ticket** | Jumps to the ticket this email is already attached to | Shown instead of "Create Ticket" once it's ticketed |
| **Archive** | Moves an untouched message out of the active inbox | Requires the "archive" permission; disabled once ticketed |
| **Back to Message List** | Returns to the folder view | — |

**Create Ticket dialog:** pick a Title, Category, Priority, and who it's assigned to (Unassigned/Team is the default — the ticket stays in the pool rather than auto-claiming to you); **Existing Ticket** switches to attaching this email to a ticket that already exists instead (with a one-click "Use this ticket" if the system suggests a likely match); **Cancel** / **Create Ticket** / **Attach** confirm or back out.

### 5.3 Writing a message

**New message (Compose):** **Discard** (abandons it), **Save Draft** (saved only in your browser, not the server — it won't follow you to another device), **Send**.

**Replying to an existing thread (before it's a ticket):** every keystroke auto-saves a real, server-side draft after you pause typing for about a second — this one *does* follow you across devices. **Save Draft** forces an immediate save; **Attach Files** uploads immediately, even before the ticket exists; **Discard Draft** deletes the saved draft entirely; **Send** delivers the reply (and is also the moment a plain email thread officially becomes "answered").

**Replying on an already-ticketed thread:** **Attach Files**, **Send Reply**, **Cancel** (just closes the panel, no server call since there's no draft to lose here).

### 5.4 Formatting toolbar (while composing or replying)

Bold, Italic, Strikethrough, Bullet list, Numbered list, Quote, Link, Undo, Redo — standard text formatting, available to anyone who can compose or reply at all.

### 5.5 System Mail

A separate folder for automatic SLA/escalation notices. **Refresh**, search, and an "unread only" checkbox control the list; clicking a notice opens it (and automatically marks it read); **View Mail** / **View Ticket** jumps straight to whatever triggered the notice; **Back to Message List** returns to the list.

### 5.6 "Create Dummy Mail" (Site Lead only)

A testing tool that simulates an incoming client email. **Receive Email** submits the simulated message; **View in Inbox** (shown after a successful send) jumps straight to it in the real inbox.

---

## 6. People & Access (Admin pages)

Reachable by Super Admin, Site Lead, Account Manager, Team Lead, and Staff (Viewer cannot open this page at all). Each person only sees a slice of the user list appropriate to their own place in the hierarchy.

### 6.1 Users page

| Button | Who can use it | What it does |
|---|---|---|
| **Permission Requests** | Everyone who can reach this page | Opens the Permission Requests page |
| **Roles** | Super Admin, Site Lead, Account Manager | Opens the Roles page |
| **+ Create User** | Requires the "create user" permission | Opens a blank user form |
| Search / Role filter / Category filter / Status filter | Everyone | Narrow the list |
| **Export** | Everyone | Downloads the currently-filtered (or just-selected) list as a spreadsheet file |
| **View** (eye icon) or clicking a row | Everyone | Opens a read-only detail panel |
| **Edit** (pencil icon) | Requires "update user" permission | Opens the same form, editable |
| **Deactivate / Activate** | Requires "update user" permission | Instantly blocks or restores that person's ability to log in, without deleting their account |
| **Delete** (trash icon) | Super Admin only, and requires "delete user" permission | Permanently removes the account, after a confirmation step |
| Row checkboxes | Everyone | Selects rows so Export can act on just those |

### 6.2 User Detail Drawer

A read-only panel (Role, Status, Category, Created Date, reporting structure). **Close** dismisses it. Below the main details is a separate section:

**Personal Permission Grants** *(only visible to people holding the "grant permission override" permission — typically Super Admin/Site Lead, or an Account Manager acting on their own direct reports)*:

| Button | What it does | Why it's separate from Roles |
|---|---|---|
| **Grant Permission** | Gives this one specific person an extra capability their role doesn't normally include | This edits only this one person — it never touches the role itself or anyone else who holds it |
| **X (Revoke)** on an existing grant | Removes that one personal grant | Same — affects only this person |

*(This is easy to confuse with the "Manage Permissions" editor below, which edits an entire role instead of one person — the app's own on-screen text calls this distinction out explicitly, and this guide does too.)*

### 6.3 Create/Edit User form

Role, Work Category, Account Manager, and Team Lead pickers (which options appear depends on the role you're assigning), an **Active** switch (whether the account can log in right away), a show/hide password toggle, and **Cancel** / **Create User (or Save Changes)** to finish.

### 6.4 Roles page

| Button | Who can use it | What it does |
|---|---|---|
| **+ Create Role** | Super Admin only | Adds a brand-new custom role |
| Clicking a role card | Everyone | Shows that role's details/permissions/assigned users |
| **⋯ menu → Edit** | Requires "update role" permission | Renames the role |
| **⋯ menu → Delete** | Requires "delete role" permission | Permanently removes the role (blocked if still in use) |
| **Manage Permissions** | Requires the "update permission" permission | Opens the full permission checklist for that role |

**Manage Permissions dialog** — this changes what *everyone* holding that role can do, not just one person:

| Control | What it does |
|---|---|
| A module's "select all" checkbox | Grants or removes every permission in that group at once |
| Individual checkboxes | Toggle one specific capability |
| **Save Permissions** | Applies the change immediately to every current holder of the role |

Note: an Account Manager editing this can only toggle permissions they personally already hold — every other checkbox appears disabled with a tooltip explaining why. Super Admin has no such restriction.

### 6.5 Permission Requests page

Lets anyone ask for a permission they don't currently have, addressed to one specific person (not a whole role) who reviews it.

| Button | What it does |
|---|---|
| **+ New Request** | Opens a form: pick the permission you want, pick exactly one person to review it, write a reason, and (only for one specific permission, and only for Staff) optionally scope the request to one teammate's one specific ticket rather than a blanket grant |
| **Approve** / **Reject** (on "Pending My Review", only shown to the exact person the request was addressed to) | Grants or denies the request |
| **Revoke** (on the History tab, only for an already-approved request) | Removes a previously-granted permission — only the original approver or a Super Admin can do this |

---

## 7. Organization Chart

Opened from the Profile page. Shows the full company hierarchy from the top down through whoever's viewing it, then their own team below them.

| Button/Control | What it does |
|---|---|
| Clicking a person's box | Opens a details panel for them (Role, Status, Department, direct-report count) |
| Expand/collapse arrow on a box | Opens or closes that branch of the chart |
| **+ / – (zoom in/out)** | Makes the chart bigger or smaller |
| Reset-zoom icon | Returns to the default zoom level |
| **Maximize / Restore** | Expands the whole chart to near-full-screen, or shrinks it back |
| **X** on the details panel | Closes just that side panel |
| The dialog's own close button | Exits the chart entirely |

This is purely a viewing tool — you can't assign or change anyone's position from here (that happens on the separate Reporting Managers admin page, section 9.2 below).

---

## 8. Your Profile & Settings

### 8.1 Profile page

| Button | What it does |
|---|---|
| **Org Chart** | Opens the Organization Chart (section 7) |
| **Settings** | Opens the Settings panel (below) |
| **Edit Profile** | Opens the form to edit your own details — this is the single entry point for editing your profile |

### 8.2 Edit Profile dialog

Edit your Full Name, Date of Birth, Department, Email, Alternate Email, Phone, and Office Location. **Cancel** discards changes; **Save Changes** actually updates your record.

### 8.3 Settings panel

Opened as a popup from the Profile page.

| Section | Buttons/Controls | Note |
|---|---|---|
| **Preferences** | Language, Time Zone, Date Format, Time Format, Default Dashboard, then **Save Changes** | This is real — it saves to your account, and changing Language instantly re-renders the whole app in that language |
| **Notifications** | Toggle switches for Email/Push/Product Updates/Security Alerts | Cosmetic only right now — these don't yet connect to a real notification-suppression system |
| **Security** | Two-Factor Authentication toggle, Login Alerts toggle, **Change Password** button | The two toggles are cosmetic only; **Change Password** is real (see below) |
| **Session Management** | **Sign Out All Other Sessions**, per-session **Revoke** | Cosmetic only — the "sessions" shown here are a mock list, not a real active-session tracker |

### 8.4 Change Password dialog

Eye icons on each field let you peek at what you've typed. **Cancel** backs out; **Update Password** actually changes your password (requires your current password plus a new one, twice, matching).

---

## 9. Reports

| Button | What it does |
|---|---|
| **Export PDF** | Opens your browser's print dialog so you can save the report as a PDF |
| **Export Excel** | Downloads the report data as an Excel-openable file |
| **Export CSV** | Downloads the same data as a plain CSV file |

Everything else on this page (KPI tiles, trend chart, priority/category/staff bar lists) is display-only — hovering shows exact numbers, but nothing is clickable beyond that. Report data is already limited to what your role is allowed to see, so exports never leak anything you couldn't already view.

---

## 10. Company-wide Audit Logs (RBAC-native page)

*(Distinct from the Ticket Audit Log described in section 4.7 — this one covers account/role/permission changes rather than ticket activity.)* Requires the "view audit log" permission just to open the page.

| Button | What it does |
|---|---|
| **Export** | Downloads the currently filtered list as a CSV (only shown if you hold the "export audit log" permission) |
| Search / date-range filters | Narrow the list |
| Pagination bar at the bottom | Page through the results |

---

## 11. Admin-only Configuration

### 11.1 SLA Timing Matrix (Super Admin / Site Lead only)

Lets you edit exactly how many minutes/percent are allowed for First Response, Resolution, Escalation Acknowledgment, and the two early-warning thresholds, per priority tier (Low/Medium/High/Critical).

| Button | What it does |
|---|---|
| Editing any number field | Just updates your unsaved draft — nothing is live yet |
| **Reset** | Discards your unsaved edits |
| **Save Changes** | Publishes the new timing rules — they apply going forward, not retroactively to SLA clocks already running |

### 11.2 Reporting Managers (Super Admin / Site Lead only)

Assigns an Account Manager an extra HR-style oversight responsibility over a whole category — separate from, and does not change, their real client ownership or ticket-assignment ability.

| Button | What it does |
|---|---|
| **Assign** | Makes the selected Account Manager the Reporting Manager for the selected category |
| **Revoke** (per row, behind a confirmation) | Removes that specific assignment |

---

## 12. Worth knowing: a few quirks and cosmetic-only controls

- **Several Settings toggles don't do anything real yet**: Notifications (Email/Push/Product Updates/Security Alerts), Two-Factor Authentication, Login Alerts, and the whole Session Management list are all cosmetic placeholders. Only **Preferences → Save Changes** and **Change Password** actually reach the backend.
- **The dashboard's "View all" and "Recent Assigned Tickets" links currently point to a generic ticket list page rather than deep-linking to the specific ticket shown** — if you click expecting to land directly on one ticket, you'll land on the list instead.
- **Every popup in this app only closes via its own Cancel/Close/X button** — clicking outside the popup or pressing Escape is deliberately disabled everywhere, so don't assume either will dismiss a dialog.
- **The "Forgot Password?" button on the login page doesn't reset your password** — it only shows a message telling you to contact an administrator.
- **Internal Note's To/CC/BCC fields are for your own team's reference only** — nothing you enter there is actually sent anywhere; there's no real recipient concept for internal notes.

---

## Appendix: an older, separate "All Tickets" / "My Tickets" area

There is a second, older set of ticket pages living in the shell app itself (separate from the real Ticket Workspace described in section 4) that currently runs on sample/demo data rather than the live database — "creating," "resolving," or "deleting" a ticket there only changes what's shown in your browser and resets the next time the page reloads. It's generally not linked from the sidebar today, but is included here for completeness in case it's ever reached directly:

- **Bulk Assign** / **Bulk Delete** (toolbar, after selecting rows), **Export**, **Create Ticket**
- Per-row menu: **View**, **Assign/Reassign**, **Resolve**, **Close**, **Delete**
- On a ticket's own page: **Assign/Reassign**, **Update** (category/priority), **Resolve**, **Close**, **Delete**, plus tabs for Conversation/Internal Notes/Attachments/Activity Timeline (all of which only store sample data, not real messages or files)

If you ever land here and something doesn't seem to "save" the way the real Ticket Workspace does, this is why.
