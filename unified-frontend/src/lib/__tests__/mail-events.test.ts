import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MAIL_EVENT_NAME,
  emitMailEvent,
  emitMailEventFromSse,
  emitMailResync,
  subscribeMailEvents,
  type MailEventDetail,
} from "@/lib/mail-events";

const received: MailEventDetail[] = [];
let unsubscribe: (() => void) | null = null;

function listen() {
  received.length = 0;
  unsubscribe = subscribeMailEvents((detail) => received.push(detail));
}

afterEach(() => {
  unsubscribe?.();
  unsubscribe = null;
});

describe("SSE mail event bridge", () => {
  it("re-broadcasts a valid mail.created event from the stream's raw data", () => {
    listen();
    emitMailEventFromSse(
      JSON.stringify({
        type: "mail.created",
        interaction_id: "i1",
        thread_id: "i1",
        ticket_id: null,
        timestamp: "2026-10-06T10:00:00+00:00",
      })
    );

    expect(received).toHaveLength(1);
    expect(received[0]).toMatchObject({ type: "mail.created", interaction_id: "i1" });
  });

  it("accepts mail.updated too", () => {
    listen();
    emitMailEventFromSse(JSON.stringify({ type: "mail.updated", interaction_id: "i2" }));
    expect(received[0].type).toBe("mail.updated");
  });

  it.each([
    ["malformed JSON", "{not json"],
    ["empty", ""],
    ["a JSON string", '"mail.created"'],
    ["null", "null"],
    ["an unknown type", JSON.stringify({ type: "mail.exploded" })],
    ["no type", JSON.stringify({ interaction_id: "i1" })],
    ["a notification-shaped payload", JSON.stringify({ notification: { id: 1 }, unread_count: 3 })],
  ])("ignores %s without throwing", (_label, data) => {
    listen();
    expect(() => emitMailEventFromSse(data)).not.toThrow();
    expect(received).toHaveLength(0);
  });

  it("emitMailResync tells listeners to resync", () => {
    listen();
    emitMailResync();
    expect(received).toEqual([{ type: "mail.resync" }]);
  });

  it("every subscriber gets each event; unsubscribing stops delivery", () => {
    const a = vi.fn();
    const b = vi.fn();
    const offA = subscribeMailEvents(a);
    const offB = subscribeMailEvents(b);

    emitMailEvent({ type: "mail.created", interaction_id: "i1" });
    offA();
    emitMailEvent({ type: "mail.created", interaction_id: "i2" });
    offB();

    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(2);
  });

  it("uses one window event name (so the navbar and Mail hook agree)", () => {
    const handler = vi.fn();
    window.addEventListener(MAIL_EVENT_NAME, handler);
    emitMailEvent({ type: "mail.created" });
    window.removeEventListener(MAIL_EVENT_NAME, handler);
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
