/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        // All backed by CSS variables (see index.css :root / .dark) so
        // toggling the `dark` class on <html> re-themes the whole app
        // without touching any component. <alpha-value> keeps every
        // existing opacity modifier (bg-accent/10, border-danger/15,
        // ...) working exactly as before.
        canvas: "rgb(var(--color-canvas) / <alpha-value>)",
        surface: "rgb(var(--color-surface) / <alpha-value>)",
        surfaceHover: "rgb(var(--color-surface-hover) / <alpha-value>)",
        border: "rgb(var(--color-border) / <alpha-value>)",
        muted: "rgb(var(--color-muted) / <alpha-value>)",
        accent: {
          DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
          dim: "#E7ECFC",
          50: "rgb(var(--color-accent-50) / <alpha-value>)",
          600: "rgb(var(--color-accent-600) / <alpha-value>)",
          700: "rgb(var(--color-accent-700) / <alpha-value>)",
        },
        // Secondary "healthcare calm" accent — used sparingly for
        // decorative highlights alongside the primary blue.
        teal: "rgb(var(--color-teal) / <alpha-value>)",
        success: "rgb(var(--color-success) / <alpha-value>)",
        warning: "rgb(var(--color-warning) / <alpha-value>)",
        danger: "rgb(var(--color-danger) / <alpha-value>)",
        info: "rgb(var(--color-info) / <alpha-value>)",
        // Redefines Tailwind's neutral scale itself (rather than
        // introducing new token names) so every existing
        // text-slate-*/bg-slate-*/border-slate-* class across the
        // app inverts correctly in dark mode with no JSX changes.
        slate: {
          50: "rgb(var(--slate-50) / <alpha-value>)",
          100: "rgb(var(--slate-100) / <alpha-value>)",
          200: "rgb(var(--slate-200) / <alpha-value>)",
          300: "rgb(var(--slate-300) / <alpha-value>)",
          400: "rgb(var(--slate-400) / <alpha-value>)",
          500: "rgb(var(--slate-500) / <alpha-value>)",
          600: "rgb(var(--slate-600) / <alpha-value>)",
          700: "rgb(var(--slate-700) / <alpha-value>)",
          800: "rgb(var(--slate-800) / <alpha-value>)",
          900: "rgb(var(--slate-900) / <alpha-value>)",
        },
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
      borderRadius: {
        md2: "12px",
        lg2: "16px",
      },
      keyframes: {
        pulseRing: {
          "0%": { boxShadow: "0 0 0 0 rgba(91,141,239,0.45)" },
          "70%": { boxShadow: "0 0 0 8px rgba(91,141,239,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(91,141,239,0)" },
        },
        fadeSlideIn: {
          "0%": { opacity: 0, transform: "translateY(4px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        popIn: {
          "0%": { opacity: 0, transform: "scale(0.97) translateY(6px)" },
          "100%": { opacity: 1, transform: "scale(1) translateY(0)" },
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
  plugins: [],
};
