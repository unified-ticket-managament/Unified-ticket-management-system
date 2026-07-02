import { useEffect, useState } from "react";

// ==========================================================
// useDebouncedValue
//
// Returns a version of `value` that only updates after it's
// been stable for `delayMs` — used on search inputs so every
// keystroke doesn't immediately re-run an expensive filter
// (or, for server-side search, fire a request per keystroke).
// ==========================================================

export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timeout);
  }, [value, delayMs]);

  return debounced;
}
