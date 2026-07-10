import { create } from "zustand";

import { MockTicket, MOCK_TICKETS, TicketStatus } from "@/lib/mock-tickets";

// In-memory (not persisted) store for the mock ticket dataset, shared by
// All Tickets / My Tickets / Ticket Details / Dashboard so an action taken
// on one page (assign, resolve, delete...) is reflected everywhere else
// without a real backend. Resets to the deterministic MOCK_TICKETS
// baseline on full reload — acceptable for a mock-data demo surface.
interface MockTicketsState {
  tickets: MockTicket[];
  getTicket: (id: string) => MockTicket | undefined;
  createTicket: (ticket: MockTicket) => void;
  updateTicket: (id: string, patch: Partial<MockTicket>) => void;
  setStatus: (id: string, status: TicketStatus, actor: string) => void;
  assign: (id: string, agent: string, actor: string) => void;
  bulkAssign: (ids: string[], agent: string, actor: string) => void;
  deleteTicket: (id: string) => void;
  bulkDelete: (ids: string[]) => void;
}

export const useMockTicketsStore = create<MockTicketsState>()((set, get) => ({
  tickets: MOCK_TICKETS,

  getTicket: (id) => get().tickets.find((t) => t.id === id),

  createTicket: (ticket) => set((state) => ({ tickets: [ticket, ...state.tickets] })),

  updateTicket: (id, patch) =>
    set((state) => ({
      tickets: state.tickets.map((t) => (t.id === id ? { ...t, ...patch } : t)),
    })),

  setStatus: (id, status, actor) =>
    set((state) => ({
      tickets: state.tickets.map((t) =>
        t.id === id
          ? { ...t, status, updatedDate: new Date().toISOString(), assignedBy: t.assignedBy || actor }
          : t
      ),
    })),

  assign: (id, agent, actor) =>
    set((state) => ({
      tickets: state.tickets.map((t) =>
        t.id === id ? { ...t, assignedTo: agent, assignedBy: actor, updatedDate: new Date().toISOString() } : t
      ),
    })),

  bulkAssign: (ids, agent, actor) =>
    set((state) => ({
      tickets: state.tickets.map((t) =>
        ids.includes(t.id)
          ? { ...t, assignedTo: agent, assignedBy: actor, updatedDate: new Date().toISOString() }
          : t
      ),
    })),

  deleteTicket: (id) => set((state) => ({ tickets: state.tickets.filter((t) => t.id !== id) })),

  bulkDelete: (ids) => set((state) => ({ tickets: state.tickets.filter((t) => !ids.includes(t.id)) })),
}));
