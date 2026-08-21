# Frontend Setup

```bash
cd unified-frontend
npm install
```

Create `.env.local` — see [environment-variables.md](environment-variables.md). **Set `NEXT_PUBLIC_TICKETING_API_URL` explicitly** — its unset fallback (`http://localhost:8001`) is stale and will silently break every ticketing-domain request while RBAC-native requests keep working.

```bash
npm run dev
```

App is now at `http://localhost:3000`. `NEXT_PUBLIC_*` variables are baked in at server start — restart after changing `.env.local`.

## Useful commands

```bash
npm run build     # next build (output: standalone)
npm run start     # serve the production build
npm run lint      # currently BROKEN — Next.js 16 dropped `next lint`, config is old-format
npx tsc --noEmit  # use this instead — the real correctness gate for this project
```

## Known, recurring gotchas (confirmed in this project's own history — check these before assuming a new bug)

- **Turbopack workspace-root inference**: if every route suddenly 404s, verify `next.config.mjs`'s `turbopack.root` pin (set to `__dirname`) is still intact before debugging anything else — Turbopack can otherwise walk up the filesystem and land on an unrelated lockfile several directories up.
- **Stale `.next/` cache after a directory rename/move**: `rm -rf .next` then restart — Turbopack's cache stores absolute paths tied to the old location.
- **Never run `npm run build` while `npm run dev` is active in the same directory** — both write into `.next/` and corrupt each other, making every route 404 (looks identical to the cache issue above, but the trigger is two concurrent processes, not a rename).
- **A `package.json` dependency isn't necessarily installed** — if you see `Module not found: Can't resolve '@some/package'` for a package clearly already used elsewhere in the codebase, run `npm install` (no args) before assuming the import path is wrong.
- **An unhandled backend 500 looks exactly like a CORS error in the browser** — if a request that used to work suddenly reads as "blocked by CORS policy" with no CORS config change, suspect an unhandled backend exception first (confirmed 3 times in this project's history), not a CORS misconfiguration.

## Testing

**No frontend test suite exists** — there is nothing to run beyond `npx tsc --noEmit`. See [11-testing/README.md](../11-testing/README.md).
