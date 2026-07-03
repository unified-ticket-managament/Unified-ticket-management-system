import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/modules/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/ticket-workspace/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",

        // ---- Ticket Workspace tokens ----
        // Ported from the standalone Ticketing frontend's Tailwind config.
        // Only additive, non-colliding keys live here — `border`/`muted`/
        // `slate` (Ticketing's own versions of those) collide with the
        // shadcn tokens above and are handled instead via scoped CSS
        // overrides under `.tm-scope` in globals.css, so they never affect
        // RBAC's own pages. `accent.DEFAULT` is intentionally shared: RBAC
        // only uses it for minor hover tints, so adopting the ticket
        // workspace's brand blue here unifies the two products' primary
        // action color instead of colliding with anything load-bearing.
        canvas: "rgb(var(--color-canvas) / <alpha-value>)",
        surface: "rgb(var(--color-surface) / <alpha-value>)",
        surfaceHover: "rgb(var(--color-surface-hover) / <alpha-value>)",
        accent: {
          DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
          foreground: "hsl(var(--accent-foreground))",
          dim: "#E7ECFC",
          50: "rgb(var(--color-accent-50) / <alpha-value>)",
          600: "rgb(var(--color-accent-600) / <alpha-value>)",
          700: "rgb(var(--color-accent-700) / <alpha-value>)",
        },
        teal: "rgb(var(--color-teal) / <alpha-value>)",
        success: "rgb(var(--color-success) / <alpha-value>)",
        warning: "rgb(var(--color-warning) / <alpha-value>)",
        danger: "rgb(var(--color-danger) / <alpha-value>)",
        info: "rgb(var(--color-info) / <alpha-value>)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        md2: "12px",
        lg2: "16px",
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgba(16,24,40,0.04)",
        card: "0 1px 2px 0 rgba(16,24,40,0.04), 0 1px 3px 0 rgba(16,24,40,0.06)",
        cardHover:
          "0 2px 4px 0 rgba(16,24,40,0.05), 0 4px 12px 0 rgba(16,24,40,0.08)",
        popover:
          "0 4px 6px -2px rgba(16,24,40,0.05), 0 12px 24px -4px rgba(16,24,40,0.12)",
        focusRing: "0 0 0 3px rgba(79,107,238,0.16)",
      },
      keyframes: {
        pulseRing: {
          "0%": { boxShadow: "0 0 0 0 rgba(91,141,239,0.45)" },
          "70%": { boxShadow: "0 0 0 8px rgba(91,141,239,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(91,141,239,0)" },
        },
        fadeSlideIn: {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        popIn: {
          "0%": { opacity: "0", transform: "scale(0.97) translateY(6px)" },
          "100%": { opacity: "1", transform: "scale(1) translateY(0)" },
        },
      },
      animation: {
        pulseRing: "pulseRing 1.6s ease-out infinite",
        fadeSlideIn: "fadeSlideIn 0.2s ease-out",
        shimmer: "shimmer 1.6s ease-in-out infinite",
        popIn: "popIn 0.18s cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
export default config;
