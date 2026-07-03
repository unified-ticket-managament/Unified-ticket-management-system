import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type {
  AgentSummary,
  InteractionResponse,
  OpenEmailResponse,
  TicketResponse,
} from "@tw/types";
import { listAgents } from "@tw/api/agent";

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

  selectedEmail: OpenEmailResponse | null;
  setSelectedEmail: (email: OpenEmailResponse | null) => void;

  activeTicket: TicketResponse | null;
  setActiveTicket: (ticket: TicketResponse | null) => void;

  timeline: InteractionResponse[];
  setTimeline: (items: InteractionResponse[]) => void;
}

const WorkflowContext = createContext<WorkflowContextValue | undefined>(
  undefined
);

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [selectedEmail, setSelectedEmail] = useState<OpenEmailResponse | null>(
    null
  );
  const [activeTicket, setActiveTicket] = useState<TicketResponse | null>(
    null
  );
  const [timeline, setTimeline] = useState<InteractionResponse[]>([]);

  useEffect(() => {
    let cancelled = false;

    listAgents()
      .then((fetched) => {
        if (!cancelled) setAgents(fetched);
      })
      .catch(() => {
        // Keep the empty list — better than a broken picker.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const value: WorkflowContextValue = {
    agents,
    selectedEmail,
    setSelectedEmail,
    activeTicket,
    setActiveTicket,
    timeline,
    setTimeline,
  };

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
