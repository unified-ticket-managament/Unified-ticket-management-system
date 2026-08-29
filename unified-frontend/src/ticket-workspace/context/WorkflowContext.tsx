import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type {
  AgentSummary,
  CategoryResponse,
  ClientResponse,
  InteractionResponse,
  OpenEmailResponse,
  ThreadResponse,
  TicketResponse,
} from "@tw/types";
import { listAgents } from "@tw/api/agent";
import { listClients } from "@tw/api/clients";
import { listCategories } from "@tw/api/categories";
import type {
  InteractionDrawerEmail,
  InteractionDrawerRow,
} from "@tw/components/common/InteractionDetailsDrawer";

// ==========================================================
// WorkflowContext
//
// Frontend-only construct that remembers which email/ticket/timeline
// the user last touched, so pages can hand off to each other without
// re-fetching everything on every navigation. The acting identity
// itself now lives in AuthContext (the real logged-in RBAC user),
// not here.
// ==========================================================

interface WorkflowContextValue {
  // Real active Staff users from the backend (the same pool the
  // auto-assignment routing picks from) — used to populate agent
  // pickers (e.g. Transfer Agent) with real users. Empty until the
  // initial fetch resolves.
  agents: AgentSummary[];

  // Stable lookup data — clients and categories rarely change within
  // a session, but used to be fetched independently by every consumer
  // that needed them (useMailInbox on every clientFilter change before
  // this session's earlier fix, MessageDetailsView on every single
  // message opened, CreateMailPage on every mount). Fetched once here,
  // alongside `agents`, and shared by every consumer instead.
  clients: ClientResponse[];
  categories: CategoryResponse[];

  // Compose (see ComposeView.tsx) needs to tell "still loading" apart
  // from "loaded, and genuinely empty" apart from "failed to load" —
  // `clients` alone (an empty array in all three cases) can't do that.
  clientsLoading: boolean;
  clientsError: boolean;

  // Same reasoning, for the Create Ticket dialog's Category dropdown —
  // it used to render an empty <Select> identically whether categories
  // were still loading, genuinely empty, or the fetch had failed.
  categoriesLoading: boolean;
  categoriesError: boolean;

  // Every category, completely unscoped — deliberately separate from
  // `categories` above. `categories` is intentionally narrowed for an
  // Account Manager (Reporting-Manager mapping, via `mine: true`) for
  // the "All Clients" filter / Change-Category pickers, where that
  // scoping exists to prevent leaking another Account Manager's
  // category-owned shared inbox (see root CLAUDE.md's Organization
  // Structure section). Ticket creation is a different concern with a
  // different rule: anyone holding `ticket:create` may create a ticket
  // in any category, regardless of role/ownership/reporting-manager
  // scoping — the Create Ticket dialog reads from this field instead.
  allCategories: CategoryResponse[];
  allCategoriesLoading: boolean;
  allCategoriesError: boolean;

  selectedEmail: OpenEmailResponse | null;
  setSelectedEmail: (email: OpenEmailResponse | null) => void;

  activeTicket: TicketResponse | null;
  setActiveTicket: (ticket: TicketResponse | null) => void;

  timeline: InteractionResponse[];
  setTimeline: (items: InteractionResponse[]) => void;

  // The Interactions list's row-details drawer state, lifted up here
  // (rather than InteractionsPage's own local useState) so it survives
  // the Expand -> FullInteractionPage -> Minimize round trip. That
  // round trip is a real route change (/interactions -> /interactions/
  // :id -> back), which remounts InteractionsPage itself and would
  // otherwise reset its local state — but WorkflowProvider sits above
  // <BrowserRouter> in TicketWorkspaceApp.tsx and TicketWorkspaceApp
  // itself no longer remounts on ticket-workspace-internal navigation
  // (see the request-duplication audit note in this repo's CLAUDE.md),
  // so this context genuinely persists across that round trip. Grouped
  // into one object (unlike this context's other, independent fields)
  // since these five always change together.
  interactionDrawer: {
    open: boolean;
    row: InteractionDrawerRow | null;
    email: InteractionDrawerEmail | null;
    thread: ThreadResponse | null;
    scrollY: number;
  };
  setInteractionDrawer: (
    value: WorkflowContextValue["interactionDrawer"]
  ) => void;
}

const WorkflowContext = createContext<WorkflowContextValue | undefined>(
  undefined
);

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [clients, setClients] = useState<ClientResponse[]>([]);
  const [clientsLoading, setClientsLoading] = useState(true);
  const [clientsError, setClientsError] = useState(false);
  const [categories, setCategories] = useState<CategoryResponse[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(true);
  const [categoriesError, setCategoriesError] = useState(false);
  const [allCategories, setAllCategories] = useState<CategoryResponse[]>([]);
  const [allCategoriesLoading, setAllCategoriesLoading] = useState(true);
  const [allCategoriesError, setAllCategoriesError] = useState(false);
  const [selectedEmail, setSelectedEmail] = useState<OpenEmailResponse | null>(
    null
  );
  const [activeTicket, setActiveTicket] = useState<TicketResponse | null>(
    null
  );
  const [timeline, setTimeline] = useState<InteractionResponse[]>([]);
  const [interactionDrawer, setInteractionDrawer] = useState<
    WorkflowContextValue["interactionDrawer"]
  >({ open: false, row: null, email: null, thread: null, scrollY: 0 });

  useEffect(() => {
    let cancelled = false;

    // One fetch each, once per session — every previous independent
    // fetch site (useMailInbox, MessageDetailsView, CreateMailPage)
    // now reads from here instead.
    listAgents()
      .then((fetched) => {
        if (!cancelled) setAgents(fetched);
      })
      .catch(() => {
        // Keep the empty list — better than a broken picker.
      });

    listClients({ mine: true })
      .then((fetched) => {
        if (!cancelled) {
          setClients(fetched);
          setClientsLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setClientsError(true);
          setClientsLoading(false);
        }
      });

    listCategories({ mine: true })
      .then((fetched) => {
        if (!cancelled) {
          setCategories(fetched);
          setCategoriesLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCategoriesError(true);
          setCategoriesLoading(false);
        }
      });

    listCategories()
      .then((fetched) => {
        if (!cancelled) {
          setAllCategories(fetched);
          setAllCategoriesLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAllCategoriesError(true);
          setAllCategoriesLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // useState setters are already referentially stable across renders,
  // so this only needs to change identity when the actual data does —
  // without it, every consumer of this context (TicketComposer,
  // TicketTimeline, TicketDetailPage, ...) re-rendered on every
  // WorkflowProvider render, regardless of whether the specific field
  // a given consumer reads had actually changed.
  const value: WorkflowContextValue = useMemo(
    () => ({
      agents,
      clients,
      clientsLoading,
      clientsError,
      categories,
      categoriesLoading,
      categoriesError,
      allCategories,
      allCategoriesLoading,
      allCategoriesError,
      selectedEmail,
      setSelectedEmail,
      activeTicket,
      setActiveTicket,
      timeline,
      setTimeline,
      interactionDrawer,
      setInteractionDrawer,
    }),
    [
      agents,
      clients,
      clientsLoading,
      clientsError,
      categories,
      categoriesLoading,
      categoriesError,
      allCategories,
      allCategoriesLoading,
      allCategoriesError,
      selectedEmail,
      activeTicket,
      timeline,
      interactionDrawer,
    ]
  );

  return (
    <WorkflowContext.Provider value={value}>
      {children}
    </WorkflowContext.Provider>
  );
}

export function useWorkflowContext(): WorkflowContextValue {
  const ctx = useContext(WorkflowContext);
  if (!ctx) {
    throw new Error(
      "useWorkflowContext must be used inside a <WorkflowProvider>."
    );
  }
  return ctx;
}
