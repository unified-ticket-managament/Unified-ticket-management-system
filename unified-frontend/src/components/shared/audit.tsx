import { Activity, LogIn, LogOut, Pencil, PlusCircle, ShieldAlert, Trash2 } from "lucide-react";

export function actionBadgeVariant(
  action: string
): "success" | "destructive" | "secondary" | "default" {
  const value = action.toLowerCase();
  if (value.includes("failed") || value.includes("reject") || value.includes("deactivate")) {
    return "destructive";
  }
  if (value.includes("delete") || value.includes("removed")) return "destructive";
  if (value.includes("create") || value.includes("activate") || value.includes("added")) {
    return "success";
  }
  if (value.includes("update") || value.includes("changed")) return "secondary";
  return "default";
}

export function ActionIcon({ action }: { action: string }) {
  const value = action.toLowerCase();
  if (value.includes("failed")) return <ShieldAlert className="h-4 w-4" />;
  if (value.includes("delete") || value.includes("removed")) return <Trash2 className="h-4 w-4" />;
  if (value.includes("create") || value.includes("added")) return <PlusCircle className="h-4 w-4" />;
  if (value.includes("update") || value.includes("changed")) return <Pencil className="h-4 w-4" />;
  if (value.includes("login")) return <LogIn className="h-4 w-4" />;
  if (value.includes("logout")) return <LogOut className="h-4 w-4" />;
  return <Activity className="h-4 w-4" />;
}
