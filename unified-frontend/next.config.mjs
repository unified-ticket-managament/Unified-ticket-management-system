import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Pins the workspace root to this project directory. Without this,
  // Turbopack walks up looking for a lockfile to infer the root and
  // can land on an unrelated one several directories up (e.g. a stray
  // package-lock.json in the user's home directory) — that has
  // previously 404'd every route in this app (see CLAUDE.md).
  turbopack: {
    root: __dirname,
  },
};

export default nextConfig;
