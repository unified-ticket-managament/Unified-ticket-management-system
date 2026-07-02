"use client";

import { ReactNode, useEffect } from "react";

import { getResolvedTheme, useThemeStore } from "@/store/auth-store";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useThemeStore((s) => s.theme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", getResolvedTheme(theme) === "dark");

    if (theme !== "system") return;

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      document.documentElement.classList.toggle("dark", media.matches);
    };

    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, [theme]);

  return <>{children}</>;
}
