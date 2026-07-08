// Mock ticket data for the Super Admin dashboard, All Tickets, Queue, and
// Reports pages. The ticketing backend has no endpoints for these views yet
// (KPI aggregation, queue ordering, report exports) — this is a fully
// static, deterministic dataset (no Math.random/Date.now, so server and
// client render identically) standing in until those APIs exist.

export type TicketPriority = "Critical" | "High" | "Medium" | "Low";
export type TicketStatus = "Open" | "In Progress" | "Resolved" | "Closed";

export interface MockTicket {
  id: string;
  subject: string;
  client: string;
  category: string;
  priority: TicketPriority;
  status: TicketStatus;
  assignedTo: string;
  assignedBy: string;
  createdBy: string;
  createdDate: string;
  updatedDate: string;
  slaBreached: boolean;
  escalated: boolean;
  waitingMinutes: number;
}

// Name used for Super Admin-owned records across the mock dataset so the
// My Tickets page (created-by-me OR assigned-to-me) has realistic rows to
// show without depending on the real logged-in user's display name.
export const SUPER_ADMIN_NAME = "Super Admin";

const CLIENTS = [
  "Acme Corp",
  "Globex Industries",
  "Initech",
  "Umbrella Group",
  "Stark Enterprises",
  "Wayne Logistics",
  "Hooli",
  "Soylent Retail",
  "Massive Dynamic",
  "Aperture Labs",
];

const CATEGORIES = [
  "Billing",
  "Technical",
  "Account Access",
  "Bug Report",
  "Feature Request",
  "General Inquiry",
];

const AGENTS = [
  "Priya Sharma",
  "Daniel Cho",
  "Maria Gomez",
  "James Walker",
  "Fatima Noor",
  "Liam O'Connor",
  "Aiko Tanaka",
  "Noah Bennett",
];

const REQUESTERS = [
  "Alex Turner",
  "Sofia Rossi",
  "Ethan Wright",
  "Chloe Martin",
  "Ravi Kapoor",
  "Emma Dubois",
  "Lucas Silva",
  "Grace Kim",
  "Omar Haddad",
  "Isla Fraser",
  "Tom Becker",
  "Nadia Petrov",
];

const SUBJECTS = [
  "Unable to log in to account",
  "Invoice amount does not match quote",
  "Feature request: bulk export to CSV",
  "Application crashes on file upload",
  "Password reset link not arriving",
  "API returns 500 on ticket creation",
  "Request to upgrade subscription plan",
  "Dashboard charts not loading",
  "Need clarification on billing cycle",
  "Two-factor authentication not working",
  "Data missing after sync",
  "Slow performance on reports page",
  "Access denied for team member",
  "Duplicate charge on last invoice",
  "Integration with Slack failing",
  "Cannot reset workspace settings",
  "Mobile app notifications delayed",
  "Request for enterprise SSO support",
  "Export button unresponsive",
  "Onboarding checklist stuck at step 3",
];

const PRIORITIES: TicketPriority[] = ["Critical", "High", "Medium", "Low"];
const STATUSES: TicketStatus[] = ["Open", "In Progress", "Resolved", "Closed"];

// Fixed 2026 dates so the dataset reads as "recent" without touching
// Date.now() — created/updated pairs are 1-6 days apart, most recent
// ticket first.
const CREATED_DATES = [
  "2026-07-06T09:15:00Z",
  "2026-07-05T14:30:00Z",
  "2026-07-05T08:00:00Z",
  "2026-07-04T11:45:00Z",
  "2026-07-03T16:20:00Z",
  "2026-07-03T10:05:00Z",
  "2026-07-02T13:50:00Z",
  "2026-07-01T09:30:00Z",
  "2026-06-30T15:10:00Z",
  "2026-06-29T12:00:00Z",
  "2026-06-28T17:25:00Z",
  "2026-06-27T08:40:00Z",
];

const UPDATED_OFFSETS_HOURS = [1, 3, 6, 12, 24, 30, 48, 72];

function buildTicket(index: number): MockTicket {
  const subject = SUBJECTS[index % SUBJECTS.length];
  const client = CLIENTS[index % CLIENTS.length];
  // CREATED_DATES cycles every 12 — CATEGORIES.length (6) and
  // PRIORITIES.length (4) both divide 12 evenly, so any `f(index) % 6`
  // or `% 4` repeats identically for index and index+12 (multiplying
  // index by a constant doesn't help: 7*12 and 5*12 are still
  // multiples of 6 and 4). Mixing in the 12-cycle count itself
  // (`cycle`) shifts the result on every wrap, breaking the tie.
  const cycle = Math.floor(index / CREATED_DATES.length);
  const slot = index % CREATED_DATES.length;
  const category = CATEGORIES[(slot * 7 + cycle * 11) % CATEGORIES.length];
  const priority = PRIORITIES[(slot * 5 + cycle * 7) % PRIORITIES.length];
  const status = STATUSES[(index + Math.floor(index / 4)) % STATUSES.length];
  // A handful of tickets are deliberately owned by Super Admin (every 7th
  // as assignee, every 8th-offset-by-3 as requester) so /my-tickets has
  // realistic, evenly-spread-across-status rows to show.
  const assignedTo = index % 7 === 0 ? SUPER_ADMIN_NAME : AGENTS[index % AGENTS.length];
  const assignedBy = AGENTS[(index + 3) % AGENTS.length];
  const createdBy = index % 8 === 3 ? SUPER_ADMIN_NAME : REQUESTERS[index % REQUESTERS.length];
  const createdDate = CREATED_DATES[index % CREATED_DATES.length];

  const created = new Date(createdDate);
  const updated = new Date(created.getTime() + UPDATED_OFFSETS_HOURS[index % UPDATED_OFFSETS_HOURS.length] * 3_600_000);

  const waitingMinutes = 15 + ((index * 37) % 480);
  const slaBreached = priority !== "Low" && waitingMinutes > 240 && status !== "Closed" && status !== "Resolved";
  const escalated = priority === "Critical" && (index % 3 === 0);

  return {
    id: `TKT-${1001 + index}`,
    subject,
    client,
    category,
    priority,
    status,
    assignedTo,
    assignedBy,
    createdBy,
    createdDate: created.toISOString(),
    updatedDate: updated.toISOString(),
    slaBreached,
    escalated,
    waitingMinutes,
  };
}

export const MOCK_TICKETS: MockTicket[] = Array.from({ length: 54 }, (_, i) => buildTicket(i));

export const PRIORITY_COLOR: Record<TicketPriority, { bar: string; badge: "destructive" | "warning" | "default" | "secondary" }> = {
  Critical: { bar: "bg-destructive", badge: "destructive" },
  High: { bar: "bg-warning", badge: "warning" },
  Medium: { bar: "bg-primary", badge: "default" },
  Low: { bar: "bg-slate-400", badge: "secondary" },
};

export const STATUS_COLOR: Record<TicketStatus, { bar: string; badge: "default" | "warning" | "success" | "secondary" }> = {
  Open: { bar: "bg-primary", badge: "default" },
  "In Progress": { bar: "bg-warning", badge: "warning" },
  Resolved: { bar: "bg-success", badge: "success" },
  Closed: { bar: "bg-slate-400", badge: "secondary" },
};

export function getDashboardKpis(tickets: MockTicket[] = MOCK_TICKETS) {
  const today = "2026-07-06";
  return {
    open: tickets.filter((t) => t.status === "Open").length,
    resolvedToday: tickets.filter((t) => t.status === "Resolved" && t.updatedDate.startsWith(today)).length,
    inProgress: tickets.filter((t) => t.status === "In Progress").length,
    closed: tickets.filter((t) => t.status === "Closed").length,
    slaBreaches: tickets.filter((t) => t.slaBreached).length,
    escalated: tickets.filter((t) => t.escalated).length,
  };
}

export function getCountsByPriority(tickets: MockTicket[] = MOCK_TICKETS) {
  return PRIORITIES.map((priority) => ({
    label: priority,
    value: tickets.filter((t) => t.priority === priority).length,
    color: PRIORITY_COLOR[priority].bar,
  }));
}

export function getCountsByStatus(tickets: MockTicket[] = MOCK_TICKETS) {
  return STATUSES.map((status) => ({
    label: status,
    value: tickets.filter((t) => t.status === status).length,
    color: STATUS_COLOR[status].bar,
  }));
}

const CATEGORY_CHART_COLORS = [
  "bg-primary",
  "bg-success",
  "bg-warning",
  "bg-destructive",
  "bg-teal",
  "bg-slate-400",
];

export function getCountsByCategory(tickets: MockTicket[] = MOCK_TICKETS) {
  return CATEGORIES.map((category, i) => ({
    label: category,
    value: tickets.filter((t) => t.category === category).length,
    color: CATEGORY_CHART_COLORS[i % CATEGORY_CHART_COLORS.length],
  }));
}

// Independent 6-month mock series (not derived from MOCK_TICKETS, whose
// created dates only span ~10 days) so "Monthly Ticket Trend" has a
// realistic longer-range shape — same pattern as the dashboard's own
// WEEKLY_LOGIN_ACTIVITY-style mock series elsewhere in this codebase.
export const MONTHLY_TICKET_TREND = [
  { label: "Feb", value: 142 },
  { label: "Mar", value: 168 },
  { label: "Apr", value: 155 },
  { label: "May", value: 189 },
  { label: "Jun", value: 204 },
  { label: "Jul", value: 176 },
];

// Groups agents into teams for the "Team Performance" report chart —
// there's no team concept elsewhere in this mock dataset, so this map is
// the single source of truth for it.
export const AGENT_TEAM: Record<string, string> = {
  "Priya Sharma": "Team Alpha",
  "Daniel Cho": "Team Alpha",
  "Maria Gomez": "Team Alpha",
  "James Walker": "Team Bravo",
  "Fatima Noor": "Team Bravo",
  "Liam O'Connor": "Team Bravo",
  "Aiko Tanaka": "Team Charlie",
  "Noah Bennett": "Team Charlie",
};

export function getStaffPerformance(tickets: MockTicket[] = MOCK_TICKETS) {
  return AGENTS.map((agent) => ({
    label: agent,
    value: tickets.filter((t) => t.assignedTo === agent && (t.status === "Resolved" || t.status === "Closed")).length,
  }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6);
}

export function getTeamPerformance(tickets: MockTicket[] = MOCK_TICKETS) {
  const teams = Array.from(new Set(Object.values(AGENT_TEAM)));
  return teams
    .map((team) => ({
      label: team,
      value: tickets.filter((t) => {
        const agentTeam = AGENT_TEAM[t.assignedTo];
        return agentTeam === team && (t.status === "Resolved" || t.status === "Closed");
      }).length,
    }))
    .sort((a, b) => b.value - a.value);
}

export function getReportMetrics(tickets: MockTicket[] = MOCK_TICKETS) {
  const total = tickets.length;
  const resolved = tickets.filter((t) => t.status === "Resolved").length;
  const closed = tickets.filter((t) => t.status === "Closed").length;
  const pending = tickets.filter((t) => t.status === "Open" || t.status === "In Progress").length;

  const finished = tickets.filter((t) => t.status === "Resolved" || t.status === "Closed");
  const avgResolutionHours =
    finished.length === 0
      ? 0
      : finished.reduce((sum, t) => sum + (new Date(t.updatedDate).getTime() - new Date(t.createdDate).getTime()), 0) /
        finished.length /
        3_600_000;

  const avgResponseMinutes = tickets.length === 0 ? 0 : tickets.reduce((sum, t) => sum + t.waitingMinutes, 0) / tickets.length;

  const slaCompliance = total === 0 ? 100 : Math.round(((total - tickets.filter((t) => t.slaBreached).length) / total) * 100);

  return {
    total,
    resolved,
    pending,
    closed,
    avgResolutionHours: Math.round(avgResolutionHours * 10) / 10,
    avgResponseMinutes: Math.round(avgResponseMinutes),
    slaCompliance,
  };
}

export interface MockActivity {
  id: string;
  actor: string;
  action: string;
  ticketId: string;
  timestamp: string;
}

export const MOCK_RECENT_ACTIVITIES: MockActivity[] = [
  { id: "act-1", actor: "Priya Sharma", action: "resolved", ticketId: "TKT-1002", timestamp: "2026-07-06T13:40:00Z" },
  { id: "act-2", actor: "Daniel Cho", action: "escalated", ticketId: "TKT-1005", timestamp: "2026-07-06T11:05:00Z" },
  { id: "act-3", actor: "Maria Gomez", action: "assigned", ticketId: "TKT-1009", timestamp: "2026-07-06T09:50:00Z" },
  { id: "act-4", actor: "James Walker", action: "commented on", ticketId: "TKT-1011", timestamp: "2026-07-05T18:20:00Z" },
  { id: "act-5", actor: "Fatima Noor", action: "reassigned", ticketId: "TKT-1014", timestamp: "2026-07-05T15:35:00Z" },
  { id: "act-6", actor: "Liam O'Connor", action: "closed", ticketId: "TKT-1017", timestamp: "2026-07-05T10:15:00Z" },
];

export const CATEGORY_ICONS_ORDER = CATEGORIES;

export interface MockNotification {
  id: string;
  title: string;
  description: string;
  time: string;
}

export const MOCK_DASHBOARD_NOTIFICATIONS: MockNotification[] = [
  { id: "notif-1", title: "SLA breach warning", description: "TKT-1005 has exceeded its response SLA.", time: "12m ago" },
  { id: "notif-2", title: "Ticket escalated", description: "TKT-1013 was escalated to Tier 2 support.", time: "1h ago" },
  { id: "notif-3", title: "New ticket assigned", description: "TKT-1021 was assigned to Priya Sharma.", time: "3h ago" },
  { id: "notif-4", title: "Report ready", description: "Weekly SLA compliance report has been generated.", time: "5h ago" },
];

/* ===========================================================
   Ticket Details page data — comments, internal notes,
   attachments, and status history. Generated on demand from a
   ticket's own fields (not baked into MOCK_TICKETS) so the list
   pages stay lightweight; every function is a pure deterministic
   function of the ticket, so re-rendering never reshuffles it.
   =========================================================== */

export function ticketIndex(ticket: MockTicket): number {
  return Number(ticket.id.replace("TKT-", "")) - 1001;
}

export interface MockComment {
  id: string;
  author: string;
  role: "agent" | "client";
  message: string;
  timestamp: string;
}

const CLIENT_MESSAGES = [
  "Could you provide an update on this? It's affecting our team.",
  "Thanks for looking into this — let me know if you need anything else.",
  "This is still happening on our end, can we get a status update?",
  "Appreciate the quick response, will test and confirm shortly.",
];

const AGENT_MESSAGES = [
  "Thanks for reaching out — I'm looking into this now.",
  "I've reproduced the issue on our end and I'm escalating to engineering.",
  "This should be resolved now — could you confirm on your end?",
  "Following up: we applied a fix, please let us know if the issue persists.",
];

export function getTicketComments(ticket: MockTicket): MockComment[] {
  const idx = ticketIndex(ticket);
  const created = new Date(ticket.createdDate).getTime();
  const updated = new Date(ticket.updatedDate).getTime();
  const span = Math.max(updated - created, 3_600_000);
  const count = 2 + (idx % 3);

  return Array.from({ length: count }, (_, i) => {
    const isClient = i % 2 === 0;
    const timestamp = new Date(created + Math.round((span * (i + 1)) / (count + 1))).toISOString();
    return {
      id: `${ticket.id}-comment-${i}`,
      author: isClient ? ticket.createdBy : ticket.assignedTo,
      role: isClient ? "client" : "agent",
      message: isClient
        ? CLIENT_MESSAGES[(idx + i) % CLIENT_MESSAGES.length]
        : AGENT_MESSAGES[(idx + i) % AGENT_MESSAGES.length],
      timestamp,
    };
  });
}

export interface MockNote {
  id: string;
  author: string;
  message: string;
  timestamp: string;
}

const INTERNAL_NOTE_TEMPLATES = [
  "Checked account settings — nothing unusual on our side, waiting on client to confirm steps to reproduce.",
  "Escalated to Tier 2 for further investigation — flagged as {priority} priority.",
  "Client's subscription is in good standing; likely a client-side configuration issue.",
  "Verified against the known issues list — this matches a recently reported bug in {category}.",
];

export function getTicketInternalNotes(ticket: MockTicket): MockNote[] {
  const idx = ticketIndex(ticket);
  const created = new Date(ticket.createdDate).getTime();
  const count = 1 + (idx % 2);

  return Array.from({ length: count }, (_, i) => ({
    id: `${ticket.id}-note-${i}`,
    author: ticket.assignedTo,
    message: INTERNAL_NOTE_TEMPLATES[(idx + i) % INTERNAL_NOTE_TEMPLATES.length]
      .replace("{priority}", ticket.priority.toLowerCase())
      .replace("{category}", ticket.category),
    timestamp: new Date(created + (i + 1) * 5_400_000).toISOString(),
  }));
}

export interface MockAttachment {
  id: string;
  name: string;
  size: string;
  uploadedBy: string;
  uploadedAt: string;
}

const ATTACHMENT_SIZES = ["128 KB", "512 KB", "1.2 MB", "3.4 MB", "845 KB"];
const ATTACHMENT_NAMES_BY_CATEGORY: Record<string, string[]> = {
  Billing: ["invoice-copy.pdf", "payment-receipt.pdf"],
  Technical: ["error-log.txt", "stack-trace.log"],
  "Account Access": ["screenshot-login-error.png"],
  "Bug Report": ["screenshot-bug.png", "console-output.log"],
  "Feature Request": ["mockup.png"],
  "General Inquiry": ["reference-doc.pdf"],
};

export function getTicketAttachments(ticket: MockTicket): MockAttachment[] {
  const idx = ticketIndex(ticket);
  const pool = ATTACHMENT_NAMES_BY_CATEGORY[ticket.category] ?? ["attachment.pdf"];
  const count = idx % 3 === 0 ? 0 : 1 + (idx % pool.length);
  const created = new Date(ticket.createdDate).getTime();

  return Array.from({ length: count }, (_, i) => ({
    id: `${ticket.id}-file-${i}`,
    name: pool[i % pool.length],
    size: ATTACHMENT_SIZES[(idx + i) % ATTACHMENT_SIZES.length],
    uploadedBy: ticket.createdBy,
    uploadedAt: new Date(created + (i + 1) * 1_800_000).toISOString(),
  }));
}

export interface MockStatusEvent {
  id: string;
  label: string;
  description: string;
  actor: string;
  timestamp: string;
}

export function getTicketStatusHistory(ticket: MockTicket): MockStatusEvent[] {
  const created = new Date(ticket.createdDate).getTime();
  const updated = new Date(ticket.updatedDate).getTime();
  const span = Math.max(updated - created, 3_600_000);

  const events: MockStatusEvent[] = [
    {
      id: `${ticket.id}-hist-created`,
      label: "Created",
      description: `Ticket opened by ${ticket.createdBy}`,
      actor: ticket.createdBy,
      timestamp: ticket.createdDate,
    },
    {
      id: `${ticket.id}-hist-assigned`,
      label: "Assigned",
      description: `Assigned to ${ticket.assignedTo} by ${ticket.assignedBy}`,
      actor: ticket.assignedBy,
      timestamp: new Date(created + span * 0.2).toISOString(),
    },
  ];

  if (ticket.status === "In Progress" || ticket.status === "Resolved" || ticket.status === "Closed") {
    events.push({
      id: `${ticket.id}-hist-progress`,
      label: "In Progress",
      description: `${ticket.assignedTo} started working on this ticket`,
      actor: ticket.assignedTo,
      timestamp: new Date(created + span * 0.5).toISOString(),
    });
  }

  if (ticket.status === "Resolved" || ticket.status === "Closed") {
    events.push({
      id: `${ticket.id}-hist-resolved`,
      label: "Resolved",
      description: `${ticket.assignedTo} marked this ticket as resolved`,
      actor: ticket.assignedTo,
      timestamp: new Date(created + span * 0.85).toISOString(),
    });
  }

  if (ticket.status === "Closed") {
    events.push({
      id: `${ticket.id}-hist-closed`,
      label: "Closed",
      description: `${ticket.assignedTo} closed this ticket`,
      actor: ticket.assignedTo,
      timestamp: ticket.updatedDate,
    });
  }

  return events;
}
