"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import {
  ClipboardList,
  LayoutDashboard,
  LogOut,
  Moon,
  Shield,
  Sun,
  UserCircle,
  Users,
} from "lucide-react";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { authService } from "@/services";
import { useAuthStore, useThemeStore } from "@/store/auth-store";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/users", label: "Users", icon: Users, permission: "user:view" },
  { href: "/roles", label: "Roles", icon: Shield, permission: "role:view" },
  { href: "/permissions", label: "Permissions", icon: Shield, permission: "permission:view" },
  { href: "/audit", label: "Audit Logs", icon: ClipboardList, permission: "audit:view" },
  { href: "/profile", label: "Profile", icon: UserCircle },
];

export function Sidebar() {
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const { theme, toggleTheme } = useThemeStore();

  const handleLogout = async () => {
    const refresh = localStorage.getItem("refresh_token") || undefined;
    await authService.logout(refresh);
    logout();
    window.location.href = "/login";
  };

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-border bg-card/50 backdrop-blur-xl">
      <div className="border-b border-border p-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Shield className="h-5 w-5" />
          </div>
          <div>
            <p className="text-sm font-semibold">RBAC Platform</p>
            <p className="text-xs text-muted-foreground">Enterprise Access</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 space-y-1 p-4">
        {navItems.map((item) => {
          const link = (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                pathname === item.href
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );

          if (item.permission) {
            return (
              <PermissionGuard key={item.href} permission={item.permission}>
                {link}
              </PermissionGuard>
            );
          }
          return link;
        })}
      </nav>

      <div className="border-t border-border p-4">
        <div className="mb-4 rounded-lg bg-muted/50 p-3">
          <p className="text-sm font-medium">{user?.name}</p>
          <p className="text-xs text-muted-foreground">{user?.role}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={toggleTheme}>
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <Button variant="outline" className="flex-1" onClick={handleLogout}>
            <LogOut className="h-4 w-4" />
            Logout
          </Button>
        </div>
      </div>
    </aside>
  );
}

export function DashboardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <motion.main
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex-1 overflow-auto"
      >
        <div className="mx-auto max-w-7xl p-8">{children}</div>
      </motion.main>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}
