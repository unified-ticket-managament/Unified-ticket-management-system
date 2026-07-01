import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";
import type {
  InteractionResponse,
  OpenEmailResponse,
  TicketResponse,
} from "@/types";
import { DEFAULT_AGENT } from "@/lib/agents";

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
  const [selectedEmail, setSelectedEmail] = useState<OpenEmailResponse | null>(
    null
  );
  const [activeTicket, setActiveTicket] = useState<TicketResponse | null>(
    null
  );
  const [timeline, setTimeline] = useState<InteractionResponse[]>([]);

  const value: WorkflowContextValue = {
    agentName,
    setAgentName,
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
