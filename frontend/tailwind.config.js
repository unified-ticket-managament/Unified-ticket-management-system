/** @type {import('tailwindcss').Config} */
export default {
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
        canvas: "#F5F7FB",
        surface: "#FFFFFF",
        surfaceHover: "#F1F4F9",
        border: "#E5E9F2",
        muted: "#69708A",
        accent: {
          DEFAULT: "#4F6BEE",
          dim: "#E7ECFC",
          50: "#EEF1FE",
          600: "#3D57D6",
          700: "#3247B3",
        },
        success: "#0F9D62",
        warning: "#D6900F",
        danger: "#DC3D34",
        info: "#7C5CE0",
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
