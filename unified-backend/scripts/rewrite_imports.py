"""
One-off migration helper for the rbac+ticketing backend merge.

Rewrites absolute `from app.<X>...` / `import app.<X>...` lines inside one
moved subtree so `<X>` is namespaced under `rbac`/`ticketing`, while leaving
imports of the four shared modules (core/database/auth/dependencies) and any
`shared_models.*` import untouched. Run once per side; safe to re-run (it's
a no-op the second time since the pattern won't match already-rewritten
lines).
"""

import re
import sys
import pathlib

RBAC_TOP = {
    "api", "models", "repositories", "services", "schemas",
    "audit", "permissions", "roles", "users",
}
TICKETING_TOP = {
    "api", "models", "repositories", "services", "storage",
    "enums", "utils", "schemas",
}

PATTERN = re.compile(
    r"^(?P<indent>\s*)(?P<kw>from|import)\s+app\.(?P<rest>[\w.]+)",
    re.MULTILINE,
)


def rewrite(root: pathlib.Path, namespace: str, top_level: set[str]) -> list[str]:
    changed = []
    for f in root.rglob("*.py"):
        text = f.read_text(encoding="utf-8")

        def repl(m: re.Match) -> str:
            first_seg = m.group("rest").split(".", 1)[0]
            if first_seg not in top_level:
                return m.group(0)
            return f'{m.group("indent")}{m.group("kw")} app.{namespace}.{m.group("rest")}'

        new = PATTERN.sub(repl, text)
        if new != text:
            f.write_text(new, encoding="utf-8")
            changed.append(str(f))
    return changed


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    base = pathlib.Path(__file__).resolve().parent.parent / "app"

    if target in ("rbac", "both"):
        for f in rewrite(base / "rbac", "rbac", RBAC_TOP):
            print("rewrote", f)

    if target in ("ticketing", "both"):
        for f in rewrite(base / "ticketing", "ticketing", TICKETING_TOP):
            print("rewrote", f)
