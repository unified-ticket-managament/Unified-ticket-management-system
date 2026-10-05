import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as crossTabAuthSync from "@/lib/cross-tab-auth-sync";

import { CrossTabAuthSync } from "./CrossTabAuthSync";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CrossTabAuthSync", () => {
  it("renders nothing", () => {
    const { container } = render(<CrossTabAuthSync />);

    expect(container).toBeEmptyDOMElement();
  });

  it("registers the cross-tab listener on mount and tears it down on unmount", () => {
    const unregister = vi.fn();
    const registerSpy = vi
      .spyOn(crossTabAuthSync, "registerCrossTabAuthSync")
      .mockReturnValue(unregister);

    const { unmount } = render(<CrossTabAuthSync />);

    expect(registerSpy).toHaveBeenCalledTimes(1);
    expect(unregister).not.toHaveBeenCalled();

    unmount();

    expect(unregister).toHaveBeenCalledTimes(1);
  });
});
