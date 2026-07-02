"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/use-toast";
import { roleService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { Role, User } from "@/types";

function buildSchema(mode: "create" | "edit", currentUserRole: string | undefined, roleMap: Map<string, string>) {
  return z
    .object({
      name: z.string().min(2, "Name must be at least 2 characters"),
      email: z.string().email("Enter a valid email"),
      role_id: z.string().min(1, "Select a role"),
      is_active: z.boolean(),
      manager_id: z.string().optional(),
      teamlead_id: z.string().optional(),
      password:
        mode === "create"
          ? z.string().min(8, "Password must be at least 8 characters")
          : z
              .union([z.string().min(8, "Password must be at least 8 characters"), z.literal("")])
              .optional(),
    })
    .superRefine((data, ctx) => {
      if (roleMap.get(data.role_id) !== "Staff") return;

      if (currentUserRole === "Super Admin") {
        if (!data.manager_id) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["manager_id"], message: "Select a manager" });
        }
        if (!data.teamlead_id) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["teamlead_id"], message: "Select a team lead" });
        }
      } else if (currentUserRole === "Manager") {
        if (!data.teamlead_id) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["teamlead_id"], message: "Select a team lead" });
        }
      }
    });
}

type UserFormValues = z.infer<ReturnType<typeof buildSchema>>;

interface UserFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user?: User | null;
}

export function UserFormDialog({ open, onOpenChange, user }: UserFormDialogProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);
  const mode: "create" | "edit" = user ? "edit" : "create";
  const [showPassword, setShowPassword] = useState(false);

  const rolesQuery = useQuery({
    queryKey: ["roles-options"],
    queryFn: () => roleService.list(),
    enabled: open,
  });

  const roles: Role[] = rolesQuery.data?.roles ?? [];
  const roleMap = useMemo(() => {
    const map = new Map<string, string>();
    roles.forEach((role) => map.set(role.role_id, role.name));
    return map;
  }, [roles]);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<UserFormValues>({
    resolver: zodResolver(buildSchema(mode, currentUser?.role, roleMap)),
    defaultValues: {
      name: "",
      email: "",
      password: "",
      role_id: "",
      is_active: true,
      manager_id: "",
      teamlead_id: "",
    },
  });

  useEffect(() => {
    if (open) {
      reset({
        name: user?.name ?? "",
        email: user?.email ?? "",
        password: "",
        role_id: user?.role_id ?? "",
        is_active: user?.is_active ?? true,
        manager_id: user?.manager_id ?? "",
        teamlead_id: user?.teamlead_id ?? "",
      });
      setShowPassword(false);
    }
  }, [open, user, reset]);

  const roleId = watch("role_id");
  const isActive = watch("is_active");
  const managerId = watch("manager_id");
  const teamleadId = watch("teamlead_id");

  const roleName = roleMap.get(roleId);
  const showHierarchyFields = roleName === "Staff";

  const hierarchyUsersQuery = useQuery({
    queryKey: ["users-hierarchy-options"],
    queryFn: () => userService.list({ page_size: 100 }),
    enabled: open && showHierarchyFields,
  });

  const allUsers: User[] = hierarchyUsersQuery.data?.users ?? [];
  const managerOptions = allUsers.filter((u) => roleMap.get(u.role_id) === "Manager");
  const teamLeadOptionsRaw = allUsers.filter((u) => roleMap.get(u.role_id) === "Team Lead");
  const teamLeadOptions =
    currentUser?.role === "Manager"
      ? teamLeadOptionsRaw.filter((u) => u.manager_id === currentUser.user_id)
      : teamLeadOptionsRaw;

  const currentUserRecord = allUsers.find((u) => u.user_id === currentUser?.user_id);
  const selfManager = allUsers.find((u) => u.user_id === currentUserRecord?.manager_id);

  useEffect(() => {
    if (!showHierarchyFields) {
      setValue("manager_id", "");
      setValue("teamlead_id", "");
      return;
    }

    if (currentUser?.role === "Manager") {
      setValue("manager_id", currentUser.user_id);
    } else if (currentUser?.role === "Team Lead") {
      setValue("manager_id", currentUserRecord?.manager_id ?? "");
      setValue("teamlead_id", currentUser.user_id);
    }
  }, [showHierarchyFields, currentUser, currentUserRecord, setValue]);

  const mutation = useMutation({
    mutationFn: async (values: UserFormValues) => {
      const isStaffRole = roleMap.get(values.role_id) === "Staff";
      const hierarchyFields = isStaffRole
        ? { manager_id: values.manager_id || null, teamlead_id: values.teamlead_id || null }
        : {};

      if (mode === "edit" && user) {
        return userService.update(user.user_id, {
          name: values.name,
          email: values.email,
          role_id: values.role_id,
          is_active: values.is_active,
          ...hierarchyFields,
        });
      }

      return userService.create({
        name: values.name,
        email: values.email,
        password: values.password as string,
        role_id: values.role_id,
        is_active: values.is_active,
        ...hierarchyFields,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users-table"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-users"] });
      toast({
        title: mode === "create" ? "User created" : "User updated",
        description:
          mode === "create"
            ? "The new user has been added successfully."
            : "The user's details have been saved.",
      });
      onOpenChange(false);
    },
    onError: () => {
      toast({
        variant: "destructive",
        title: mode === "create" ? "Failed to create user" : "Failed to update user",
        description: "Please check the form and try again.",
      });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{mode === "create" ? "Create User" : "Edit User"}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit((values) => mutation.mutate(values))} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Full Name</Label>
            <Input id="name" placeholder="Jane Doe" {...register("name")} />
            {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" placeholder="jane@company.com" {...register("email")} />
            {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">
              {mode === "create" ? "Password" : "New Password (optional)"}
            </Label>
            <div className="relative">
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                placeholder="••••••••"
                className="pr-10"
                {...register("password")}
              />
              <button
                type="button"
                onClick={() => setShowPassword((prev) => !prev)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
                aria-label={showPassword ? "Hide password" : "Show password"}
                tabIndex={-1}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            {errors.password && (
              <p className="text-sm text-destructive">{errors.password.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Role</Label>
            <Select value={roleId} onValueChange={(value) => setValue("role_id", value, { shouldValidate: true })}>
              <SelectTrigger>
                <SelectValue placeholder={rolesQuery.isLoading ? "Loading roles..." : "Select a role"} />
              </SelectTrigger>
              <SelectContent>
                {roles.map((role) => (
                  <SelectItem key={role.role_id} value={role.role_id}>
                    {role.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {errors.role_id && <p className="text-sm text-destructive">{errors.role_id.message}</p>}
          </div>

          {showHierarchyFields && (
            <div className="space-y-4 rounded-lg border border-dashed border-border p-3">
              <p className="text-xs font-medium text-muted-foreground">Reporting Structure</p>

              {currentUser?.role === "Super Admin" && (
                <>
                  <div className="space-y-2">
                    <Label>Manager</Label>
                    <Select
                      value={managerId || ""}
                      onValueChange={(value) => setValue("manager_id", value, { shouldValidate: true })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select a manager" />
                      </SelectTrigger>
                      <SelectContent>
                        {managerOptions.map((m) => (
                          <SelectItem key={m.user_id} value={m.user_id}>
                            {m.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {errors.manager_id && (
                      <p className="text-sm text-destructive">{errors.manager_id.message}</p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label>Team Lead</Label>
                    <Select
                      value={teamleadId || ""}
                      onValueChange={(value) => setValue("teamlead_id", value, { shouldValidate: true })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select a team lead" />
                      </SelectTrigger>
                      <SelectContent>
                        {teamLeadOptions.map((t) => (
                          <SelectItem key={t.user_id} value={t.user_id}>
                            {t.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {errors.teamlead_id && (
                      <p className="text-sm text-destructive">{errors.teamlead_id.message}</p>
                    )}
                  </div>
                </>
              )}

              {currentUser?.role === "Manager" && (
                <>
                  <div className="space-y-2">
                    <Label>Manager</Label>
                    <Input value={currentUser.name} disabled />
                    <p className="text-xs text-muted-foreground">Automatically assigned as you.</p>
                  </div>

                  <div className="space-y-2">
                    <Label>Team Lead</Label>
                    <Select
                      value={teamleadId || ""}
                      onValueChange={(value) => setValue("teamlead_id", value, { shouldValidate: true })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select a team lead" />
                      </SelectTrigger>
                      <SelectContent>
                        {teamLeadOptions.map((t) => (
                          <SelectItem key={t.user_id} value={t.user_id}>
                            {t.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {errors.teamlead_id && (
                      <p className="text-sm text-destructive">{errors.teamlead_id.message}</p>
                    )}
                    {teamLeadOptions.length === 0 && (
                      <p className="text-xs text-muted-foreground">No team leads report to you yet.</p>
                    )}
                  </div>
                </>
              )}

              {currentUser?.role === "Team Lead" && (
                <>
                  <div className="space-y-2">
                    <Label>Manager</Label>
                    <Input value={selfManager?.name ?? "Unassigned"} disabled />
                    <p className="text-xs text-muted-foreground">
                      Automatically inherited from your assignment.
                    </p>
                  </div>

                  <div className="space-y-2">
                    <Label>Team Lead</Label>
                    <Input value={currentUser.name} disabled />
                    <p className="text-xs text-muted-foreground">Automatically assigned as you.</p>
                  </div>
                </>
              )}
            </div>
          )}

          <div className="flex items-center justify-between rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">Active</p>
              <p className="text-xs text-muted-foreground">Inactive users cannot sign in.</p>
            </div>
            <Switch
              checked={isActive}
              onCheckedChange={(checked) => setValue("is_active", checked)}
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {mode === "create" ? "Create User" : "Save Changes"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
