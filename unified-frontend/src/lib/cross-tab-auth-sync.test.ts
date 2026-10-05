import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearTokens } from "@/lib/api";

import { registerCrossTabAuthSync } from "./cross-tab-auth-sync";

vi.mock("@/lib/api", () => ({
  clearTokens: vi.fn(),
}));

function dispatchStorageEvent(init: Partial<StorageEventInit>) {
  window.dispatchEvent(
    new StorageEvent("storage", {
      storageArea: window.localStorage,
      ...init,
    }),
  );
}

function setPath(pathname: string) {
  window.history.pushState({}, "", pathname);
}

describe("registerCrossTabAuthSync", () => {
  let unregister: () => void;
  let reloadSpy: ReturnType<typeof vi.fn>;
  const originalLocation = window.location;

  beforeEach(() => {
    vi.clearAllMocks();
    setPath("/dashboard");

    // jsdom's window.location.href setter actually attempts navigation
    // (and errors with "Not implemented"); replace it with a spy so the
    // redirect branch can be asserted without jsdom's navigation stub
    // throwing.
    reloadSpy = vi.fn();
    // @ts-expect-error -- narrowing window.location to a test double
    delete window.location;
    window.location = {
      ...originalLocation,
      pathname: "/dashboard",
      href: "",
      reload: reloadSpy,
    } as unknown as Location;

    unregister = registerCrossTabAuthSync();
  });

  afterEach(() => {
    unregister();
    window.location = originalLocation;
  });

  it("ignores events from a storage area other than localStorage", () => {
    dispatchStorageEvent({
      key: "access_token",
      newValue: null,
      storageArea: window.sessionStorage,
    });

    expect(clearTokens).not.toHaveBeenCalled();
  });

  it("ignores unrelated keys", () => {
    dispatchStorageEvent({ key: "settings-storage", newValue: "{}" });

    expect(clearTokens).not.toHaveBeenCalled();
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("ignores access_token changes that are not a removal", () => {
    dispatchStorageEvent({ key: "access_token", newValue: "new-token" });

    expect(clearTokens).not.toHaveBeenCalled();
  });

  it("clears tokens and redirects to /login when access_token is removed", () => {
    dispatchStorageEvent({ key: "access_token", newValue: null });

    expect(clearTokens).toHaveBeenCalledTimes(1);
    expect(window.location.href).toBe("/login");
  });

  it("clears tokens but does not redirect when access_token is removed on the login page", () => {
    window.location.pathname = "/login";

    dispatchStorageEvent({ key: "access_token", newValue: null });

    expect(clearTokens).toHaveBeenCalledTimes(1);
    expect(window.location.href).toBe("");
  });

  it("reloads the tab when impersonation-storage changes", () => {
    dispatchStorageEvent({ key: "impersonation-storage", newValue: "{}" });

    expect(reloadSpy).toHaveBeenCalledTimes(1);
    expect(clearTokens).not.toHaveBeenCalled();
  });

  it("does not reload when impersonation-storage changes on the login page", () => {
    window.location.pathname = "/login";

    dispatchStorageEvent({ key: "impersonation-storage", newValue: "{}" });

    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("stops reacting to storage events once unregistered", () => {
    unregister();

    dispatchStorageEvent({ key: "access_token", newValue: null });

    expect(clearTokens).not.toHaveBeenCalled();
  });
});
