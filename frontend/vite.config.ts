import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    // Bind to all interfaces (both IPv4 and IPv6) — on this machine
    // Node resolves "localhost" to the IPv6 loopback first, so the
    // default host-less config only listened on [::1], and anything
    // hitting 127.0.0.1:5173 directly got a connection error.
    host: true,
  },
});
