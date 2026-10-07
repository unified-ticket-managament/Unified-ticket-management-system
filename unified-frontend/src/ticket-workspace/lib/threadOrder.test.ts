import { describe, expect, it } from "vitest";

import { newestFirst } from "./threadOrder";

const r = (id: string, created_at: string) => ({ id, created_at });

describe("newestFirst", () => {
  it("returns an empty list unchanged", () => {
    expect(newestFirst([])).toEqual([]);
  });

  it("leaves a single reply unchanged", () => {
    expect(newestFirst([r("a", "2026-01-01T10:00:00Z")]).map((x) => x.id)).toEqual(["a"]);
  });

  it("puts the latest reply first, oldest last", () => {
    const out = newestFirst([
      r("a", "2026-01-01T10:00:00Z"),
      r("b", "2026-01-01T11:00:00Z"),
      r("c", "2026-01-01T12:00:00Z"),
    ]);
    expect(out.map((x) => x.id)).toEqual(["c", "b", "a"]);
  });

  it("orders by real time even if the input is not sorted or mixes offsets", () => {
    const out = newestFirst([
      r("late", "2026-01-01T12:00:00Z"),
      r("early", "2026-01-01T10:00:00Z"),
      r("mid", "2026-01-01T13:30:00+02:00"), // 11:30Z
    ]);
    expect(out.map((x) => x.id)).toEqual(["late", "mid", "early"]);
  });

  it("breaks timestamp ties by reversing the API order", () => {
    const t = "2026-01-01T10:00:00Z";
    expect(newestFirst([r("a", t), r("b", t)]).map((x) => x.id)).toEqual(["b", "a"]);
  });

  it("does not mutate the input", () => {
    const input = [r("a", "2026-01-01T10:00:00Z"), r("b", "2026-01-01T11:00:00Z")];
    const snapshot = [...input];
    newestFirst(input);
    expect(input).toEqual(snapshot);
  });
});
