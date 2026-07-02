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
} from "@/types";
import { DEFAULT_AGENT } from "@/lib/agents";
import { listAgents } from "@/api/agent";

// ==========================================================
// WorkflowContext
//
// Frontend-only construct that remembers which agent identity
// is currently acting, and which email/ticket/timeline the
// user last touched, so pages can hand off to each other
// without re-fetching everything on every navigation.
// ==========================================================

interface WorkflowContextValue {
  agentName: string;
  setAgentName: (name: string) => void;

  // Real active Staff users from the backend (the same pool the
  // auto-assignment routing picks from) — the agent switcher must
  // list every name routing can actually land on, or newly created
  // emails can end up assigned to an agent the UI has no way to
  // act as. Empty until the initial fetch resolves.
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
  const [agentName, setAgentName] = useState<string>(DEFAULT_AGENT);
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
        if (cancelled || fetched.length === 0) return;
        setAgents(fetched);
        // The hardcoded default may not even be a real Staff member
        // (or may not be the one routing currently favors) — once
        // the real directory is in, snap to a name that's actually
        // in it so the UI is never "acting as" someone who can't
        // receive anything.
        setAgentName((current) =>
          fetched.some((a) => a.name === current) ? current : fetched[0].name
        );
      })
      .catch(() => {
        // Keep the hardcoded fallback — better than a broken switcher.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const value: WorkflowContextValue = {
    agentName,
    setAgentName,
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
