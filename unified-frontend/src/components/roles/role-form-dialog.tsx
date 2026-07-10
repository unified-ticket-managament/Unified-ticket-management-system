"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { roleService } from "@/services";
import { Role } from "@/types";

const roleSchema = z.object({
  name: z.string().min(2, "Role name must be at least 2 characters"),
});

type RoleFormValues = z.infer<typeof roleSchema>;

interface RoleFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  role?: Role | null;
}

export function RoleFormDialog({ open, onOpenChange, role }: RoleFormDialogProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const mode: "create" | "edit" = role ? "edit" : "create";

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<RoleFormValues>({
    resolver: zodResolver(roleSchema),
    defaultValues: { name: "" },
  });

  useEffect(() => {
    if (open) {
      reset({ name: role?.name ?? "" });
    }
  }, [open, role, reset]);

  const mutation = useMutation({
    mutationFn: (values: RoleFormValues) =>
      mode === "edit" && role
        ? roleService.update(role.role_id, values)
        : roleService.create(values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roles-cards"] });
      queryClient.invalidateQueries({ queryKey: ["roles-options"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-roles"] });
      toast({
        title: mode === "create" ? "Role created" : "Role updated",
        description:
          mode === "create"
            ? "The new role has been added successfully."
            : "The role has been saved.",
      });
      onOpenChange(false);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: mode === "create" ? "Failed to create role" : "Failed to update role",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{mode === "create" ? "Create Role" : "Edit Role"}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit((values) => mutation.mutate(values))} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="role-name">Role Name</Label>
            <Input id="role-name" placeholder="e.g. Regional Manager" {...register("name")} />
            {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {mode === "create" ? "Create Role" : "Save Changes"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
