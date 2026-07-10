import { Activity, Pencil, PlusCircle, Trash2 } from "lucide-react";

export function actionBadgeVariant(
  action: string
): "success" | "destructive" | "secondary" | "default" {
  const value = action.toLowerCase();
  if (value.includes("delete")) return "destructive";
  if (value.includes("create")) return "success";
  if (value.includes("update")) return "secondary";
  return "default";
}

export function ActionIcon({ action }: { action: string }) {
  const value = action.toLowerCase();
  if (value.includes("delete")) return <Trash2 className="h-4 w-4" />;
  if (value.includes("create")) return <PlusCircle className="h-4 w-4" />;
  if (value.includes("update")) return <Pencil className="h-4 w-4" />;
  return <Activity className="h-4 w-4" />;
}
