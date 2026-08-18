"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { CategoryMultiSelect } from "@/components/users/CategoryMultiSelect";
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
import { dedupeRolesByName, getCreatableRoleNames, ROLE_NAMES } from "@/lib/role-access";
import { categoryService, roleService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { Category, Role, User } from "@/types";
import { listConfiguredClientContacts } from "@tw/api/clients";

// The five internal-organization roles — every role except Client.
// Mirrors unified-backend/app/rbac/services/user_service.py's
// DESIGNATION_REQUIRED_ROLE_NAMES exactly (all five require
// Designation + Personal Email; keep both in sync if this changes).
const INTERNAL_ROLE_NAMES: string[] = [
  ROLE_NAMES.SUPER_ADMIN,
  ROLE_NAMES.SITE_LEAD,
  ROLE_NAMES.ACCOUNT_MANAGER,
  ROLE_NAMES.TEAM_LEAD,
  ROLE_NAMES.STAFF,
];

// Mirrors user_service.py's REPORTING_MANAGER_OPTIONAL_ROLE_NAMES —
// every internal role requires a Reporting Manager except Site Lead.
const REPORTING_MANAGER_OPTIONAL_ROLE_NAMES: string[] = [ROLE_NAMES.SITE_LEAD];

function buildSchema(mode: "create" | "edit", currentUserRole: string | undefined, roleMap: Map<string, string>) {
  return z
    .object({
      name: z.string().min(2, "Name must be at least 2 characters"),
      email: z.string().email("Enter a valid email"),
      role_id: z.string().min(1, "Select a role"),
      is_active: z.boolean(),
      manager_id: z.string().optional(),
      teamlead_id: z.string().optional(),
      // Organization-Chart-only field, independent of manager_id/
      // teamlead_id above and their role-specific required-ness rules
      // below — unrestricted by role, always optional at the schema
      // level (required-ness for internal roles other than Site Lead
      // is enforced in the superRefine below instead, since it
      // depends on which role is selected).
      reporting_manager_id: z.string().optional(),
      // Full multi-category selection — the field this form actually
      // writes now. Legacy `category_id` is no longer submitted by
      // this form (the backend derives it from the first entry here).
      category_ids: z.array(z.string()).optional(),
      designation: z.string().optional(),
      employee_number: z.string().optional(),
      alternate_email: z
        .union([z.string().email("Enter a valid email"), z.literal("")])
        .optional(),
      contact_emails: z
        .array(z.object({ value: z.string() }))
        .optional(),
      // Client has no login of its own — required-ness (min 8 chars in
      // create mode) is enforced below in superRefine, gated on the
      // selected role, rather than unconditionally here, since the
      // Password field is hidden entirely for Client (see the JSX).
      password: z
        .union([z.string().min(8, "Password must be at least 8 characters"), z.literal("")])
        .optional(),
    })
    .superRefine((data, ctx) => {
      const selectedRoleName = roleMap.get(data.role_id);
      const needsCategory =
        selectedRoleName === ROLE_NAMES.STAFF || selectedRoleName === ROLE_NAMES.TEAM_LEAD;

      if (
        mode === "create" &&
        selectedRoleName !== ROLE_NAMES.CLIENT &&
        (!data.password || data.password.length < 8)
      ) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["password"],
          message: "Password must be at least 8 characters",
        });
      }

      if (needsCategory && (!data.category_ids || data.category_ids.length === 0)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["category_ids"],
          message: "Select at least one category",
        });
      }

      if (selectedRoleName === ROLE_NAMES.STAFF) {
        if (currentUserRole === ROLE_NAMES.SUPER_ADMIN) {
          if (!data.manager_id) {
            ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["manager_id"], message: "Select a manager" });
          }
          if (!data.teamlead_id) {
            ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["teamlead_id"], message: "Select a team lead" });
          }
        } else if (currentUserRole === ROLE_NAMES.ACCOUNT_MANAGER) {
          if (!data.teamlead_id) {
            ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["teamlead_id"], message: "Select a team lead" });
          }
        }
      } else if (selectedRoleName === ROLE_NAMES.TEAM_LEAD) {
        if (currentUserRole === ROLE_NAMES.SUPER_ADMIN && !data.manager_id) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["manager_id"], message: "Select a reporting manager" });
        }
      } else if (selectedRoleName === ROLE_NAMES.CLIENT) {
        // The backend requires an owning Account Manager to create the
        // linked `clients` row (see root CLAUDE.md's Client-role
        // section) — enforced here too so the error surfaces on this
        // field instead of as a generic submit failure.
        if (!data.manager_id) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["manager_id"], message: "Select an Account Manager" });
        }

        const emails = (data.contact_emails ?? [])
          .map((entry) => entry.value.trim())
          .filter((value) => value.length > 0);

        if (emails.length === 0) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["contact_emails"],
            message: "At least one contact email is required.",
          });
        }

        const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        const seen = new Set<string>();
        data.contact_emails?.forEach((entry, index) => {
          const value = entry.value.trim();
          if (!value) return;

          if (!emailPattern.test(value)) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              path: ["contact_emails", index, "value"],
              message: "Enter a valid email",
            });
            return;
          }

          const normalized = value.toLowerCase();
          if (seen.has(normalized)) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              path: ["contact_emails", index, "value"],
              message: "Duplicate contact email",
            });
          }
          seen.add(normalized);
        });
      } else if (selectedRoleName && INTERNAL_ROLE_NAMES.includes(selectedRoleName)) {
        // Designation + Personal Email are mandatory for every
        // internal role; Reporting Manager is mandatory for every
        // internal role except Site Lead — mirrors
        // user_service.py's own DESIGNATION_REQUIRED_ROLE_NAMES/
        // REPORTING_MANAGER_OPTIONAL_ROLE_NAMES exactly.
        if (!data.designation || !data.designation.trim()) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["designation"], message: "Designation is required" });
        }
        if (!data.employee_number || !data.employee_number.trim()) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["employee_number"], message: "Employee ID is required" });
        }
        if (!data.alternate_email || !data.alternate_email.trim()) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["alternate_email"],
            message: "Personal Email is required",
          });
        }
        if (
          !REPORTING_MANAGER_OPTIONAL_ROLE_NAMES.includes(selectedRoleName) &&
          !data.reporting_manager_id
        ) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["reporting_manager_id"],
            message: "Reporting Manager is required",
          });
        }
      }
    });
}

type UserFormValues = z.infer<ReturnType<typeof buildSchema>>;

interface UserFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user?: User | null;
  // Create mode only (ignored once `user` is set) — lets a caller open
  // this dialog with a role already selected, e.g. the Roles page's
  // "Create Client" button on the Client role's own detail view.
  defaultRoleId?: string;
}

export function UserFormDialog({ open, onOpenChange, user, defaultRoleId }: UserFormDialogProps) {
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

  const allRoles: Role[] = dedupeRolesByName<Role>(rolesQuery.data?.roles ?? []);
  const roleMap = useMemo(() => {
    const map = new Map<string, string>();
    allRoles.forEach((role) => map.set(role.role_id, role.name));
    return map;
  }, [allRoles]);

  // Applied in both create AND edit mode — a role that's off-limits to
  // assign on creation (e.g. Site Lead can't hand out Super Admin) is
  // just as off-limits when editing an existing user's role. The
  // edited user's own current role is always included so the Select
  // never ends up empty for a user who already holds a role outside
  // the actor's creatable set.
  const creatableRoleNames = getCreatableRoleNames(currentUser?.role);
  const roles: Role[] =
    creatableRoleNames !== null
      ? allRoles.filter((role) => creatableRoleNames.includes(role.name) || role.role_id === user?.role_id)
      : allRoles;

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    control,
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
      reporting_manager_id: "",
      category_ids: [],
      designation: "",
      employee_number: "",
      alternate_email: "",
      contact_emails: [{ value: "" }],
    },
  });

  const contactEmailsArray = useFieldArray({ control, name: "contact_emails" });

  useEffect(() => {
    if (open) {
      reset({
        name: user?.name ?? "",
        email: user?.email ?? "",
        password: "",
        role_id: user?.role_id ?? defaultRoleId ?? "",
        is_active: user?.is_active ?? true,
        manager_id: user?.manager_id ?? "",
        teamlead_id: user?.teamlead_id ?? "",
        reporting_manager_id: user?.reporting_manager_id ?? "",
        category_ids: user?.category_ids ?? (user?.category_id ? [user.category_id] : []),
        designation: user?.designation ?? "",
        employee_number: user?.employee_number ?? "",
        alternate_email: user?.alternate_email ?? "",
        contact_emails: [{ value: "" }],
      });
      setShowPassword(false);
    }
  }, [open, user, defaultRoleId, reset]);

  const roleId = watch("role_id");
  const isActive = watch("is_active");
  const managerId = watch("manager_id");
  const teamleadId = watch("teamlead_id");
  const reportingManagerId = watch("reporting_manager_id");
  const categoryIds = watch("category_ids") ?? [];

  const roleName = roleMap.get(roleId);
  const showStaffHierarchy = roleName === ROLE_NAMES.STAFF;
  const showTeamLeadHierarchy = roleName === ROLE_NAMES.TEAM_LEAD;
  // Client needs only an owning Account Manager (manager_id) — no
  // category, no team lead — see the Client-role branch in
  // buildSchema/the mutation payload below.
  const showClientHierarchy = roleName === ROLE_NAMES.CLIENT;
  const showHierarchyFields = showStaffHierarchy || showTeamLeadHierarchy || showClientHierarchy;
  const showInternalRoleFields = !!roleName && INTERNAL_ROLE_NAMES.includes(roleName);

  // Editing an existing Client — fetch its curated (configured-only,
  // never the interaction-derived merge — see
  // listConfiguredClientContacts' own docstring) contact list to
  // prefill the field array below, once roles have loaded enough to
  // know the edited user is really a Client.
  const isEditingClient = mode === "edit" && showClientHierarchy;

  const clientContactsQuery = useQuery({
    queryKey: ["client-contacts", user?.user_id],
    queryFn: () => listConfiguredClientContacts(user!.user_id),
    enabled: open && isEditingClient,
  });

  useEffect(() => {
    if (clientContactsQuery.data && clientContactsQuery.data.length > 0) {
      setValue(
        "contact_emails",
        clientContactsQuery.data.map((contact) => ({ value: contact.email }))
      );
    }
  }, [clientContactsQuery.data, setValue]);

  // Enabled whenever the dialog is open (not gated on
  // showHierarchyFields) — the Reporting Manager picker below is
  // unrestricted by role and needs this list regardless of which role
  // is selected, unlike the Account Manager/Team Lead pickers it's
  // fetched alongside.
  const hierarchyUsersQuery = useQuery({
    queryKey: ["users-hierarchy-options"],
    queryFn: () => userService.list({ page_size: 100 }),
    enabled: open,
  });

  // Only Staff/Team Lead need a Work Category — Client has no
  // category concept at all (see the Client-role branch below), so
  // this is scoped narrower than showHierarchyFields.
  const showCategoryField = showStaffHierarchy || showTeamLeadHierarchy;

  const categoriesQuery = useQuery({
    queryKey: ["categories-options"],
    queryFn: () => categoryService.list({ page_size: 100 }),
    enabled: open && showCategoryField,
  });

  const categories: Category[] = categoriesQuery.data?.categories ?? [];

  const allUsers: User[] = hierarchyUsersQuery.data?.users ?? [];
  const managerOptions = allUsers.filter((u) => roleMap.get(u.role_id) === ROLE_NAMES.ACCOUNT_MANAGER);
  const teamLeadOptionsRaw = allUsers.filter((u) => roleMap.get(u.role_id) === ROLE_NAMES.TEAM_LEAD);
  const teamLeadOptions =
    currentUser?.role === ROLE_NAMES.ACCOUNT_MANAGER
      ? teamLeadOptionsRaw.filter((u) => u.manager_id === currentUser.user_id)
      : teamLeadOptionsRaw;
  // Unrestricted by role — any active user (other than the one being
  // edited) may be picked as the Organization Chart reporting manager.
  const reportingManagerOptions = allUsers.filter((u) => u.user_id !== user?.user_id);

  useEffect(() => {
    if (!showHierarchyFields) {
      setValue("manager_id", "");
      setValue("teamlead_id", "");
      setValue("category_ids", []);
      return;
    }

    if (currentUser?.role === ROLE_NAMES.ACCOUNT_MANAGER) {
      // Account Manager creating Staff or Team Lead — always reports to the current Account Manager.
      setValue("manager_id", currentUser.user_id);
      if (!showStaffHierarchy) {
        setValue("teamlead_id", "");
      }
    }
  }, [showHierarchyFields, showStaffHierarchy, currentUser, setValue]);

  const mutation = useMutation({
    mutationFn: async (values: UserFormValues) => {
      const selectedRoleName = roleMap.get(values.role_id);
      const needsCategory =
        selectedRoleName === ROLE_NAMES.STAFF || selectedRoleName === ROLE_NAMES.TEAM_LEAD;
      const hierarchyFields = {
        ...(selectedRoleName === ROLE_NAMES.STAFF
          ? { manager_id: values.manager_id || null, teamlead_id: values.teamlead_id || null }
          : selectedRoleName === ROLE_NAMES.TEAM_LEAD || selectedRoleName === ROLE_NAMES.CLIENT
            ? { manager_id: values.manager_id || null }
            : {}),
        ...(needsCategory ? { category_ids: values.category_ids ?? [] } : {}),
      };

      // Unconditional, unrestricted by role — independent of
      // hierarchyFields' role-specific manager_id/teamlead_id rules.
      // Absent entirely for Client (see root CLAUDE.md's Client-role
      // section — a Client has no Organization Chart position).
      const reportingManagerField =
        selectedRoleName === ROLE_NAMES.CLIENT
          ? {}
          : { reporting_manager_id: values.reporting_manager_id || null };

      // Designation + Personal Email — internal roles only.
      const internalProfileFields =
        selectedRoleName && INTERNAL_ROLE_NAMES.includes(selectedRoleName)
          ? {
              designation: values.designation || null,
              alternate_email: values.alternate_email || null,
              employee_number: values.employee_number || null,
            }
          : {};

      // Contact Emails — Client only, full-replace semantics on edit.
      const contactEmailFields =
        selectedRoleName === ROLE_NAMES.CLIENT
          ? {
              contact_emails: (values.contact_emails ?? [])
                .map((entry) => entry.value.trim())
                .filter((value) => value.length > 0),
            }
          : {};

      if (mode === "edit" && user) {
        return userService.update(user.user_id, {
          name: values.name,
          email: values.email,
          role_id: values.role_id,
          is_active: values.is_active,
          ...hierarchyFields,
          ...reportingManagerField,
          ...internalProfileFields,
          ...contactEmailFields,
        });
      }

      return userService.create({
        name: values.name,
        email: values.email,
        password: values.password as string,
        role_id: values.role_id,
        is_active: values.is_active,
        ...hierarchyFields,
        ...reportingManagerField,
        ...internalProfileFields,
        ...contactEmailFields,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users-table"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-users"] });
      // A Client save (create or edit) writes to `clients`/
      // `client_contacts`, not `users` — invalidate the Roles page's
      // Client-role list/contacts too so it doesn't keep showing
      // stale data after this dialog closes. Harmless no-op refetch
      // for every non-Client save.
      queryClient.invalidateQueries({ queryKey: ["clients-list"] });
      if (user) {
        queryClient.invalidateQueries({ queryKey: ["client-contacts-configured", user.user_id] });
      }
      // The Roles page's per-role "Assigned Users" counts (GET
      // /roles/{role_id}/users) are a separate cache key from
      // "users-table" — invalidate the whole prefix so creating/
      // editing/reactivating an internal user is reflected there too
      // without a manual reload.
      queryClient.invalidateQueries({ queryKey: ["role-users"] });
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

  // Flattens both the array-level ("at least one contact email is
  // required") and per-row ("enter a valid email"/"duplicate")
  // zod issues added in buildSchema's Client branch into one list of
  // plain strings — avoids fighting react-hook-form's not-fully-typed
  // array-error shape for a field this dynamic.
  const contactEmailErrorMessages: string[] = (() => {
    const arrayError = errors.contact_emails as
      | { message?: string; root?: { message?: string } }
      | Array<{ value?: { message?: string } }>
      | undefined;

    if (!arrayError) return [];

    if (Array.isArray(arrayError)) {
      return arrayError
        .map((entry) => entry?.value?.message)
        .filter((message): message is string => !!message);
    }

    const message = arrayError.message ?? arrayError.root?.message;
    return message ? [message] : [];
  })();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{mode === "create" ? "Create User" : "Edit User"}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit((values) => mutation.mutate(values))} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">{showClientHierarchy ? "Client Name" : "Full Name"}</Label>
            <Input
              id="name"
              placeholder={showClientHierarchy ? "Apollo Hospitals" : "Jane Doe"}
              {...register("name")}
            />
            {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
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

          {showInternalRoleFields && (
            <div className="space-y-2">
              <Label htmlFor="employee_number">Employee ID</Label>
              <Input
                id="employee_number"
                placeholder="266"
                {...register("employee_number")}
              />
              {errors.employee_number && (
                <p className="text-sm text-destructive">{errors.employee_number.message}</p>
              )}
            </div>
          )}

          {showInternalRoleFields && (
            <div className="space-y-2">
              <Label htmlFor="designation">Designation</Label>
              <Input
                id="designation"
                placeholder="Team Lead - AR Operations"
                {...register("designation")}
              />
              {errors.designation && (
                <p className="text-sm text-destructive">{errors.designation.message}</p>
              )}
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="email">Organization Email</Label>
            <Input id="email" type="email" placeholder="jane@company.com" {...register("email")} />
            {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
          </div>

          {showInternalRoleFields && (
            <div className="space-y-2">
              <Label htmlFor="alternate_email">Personal Email</Label>
              <Input
                id="alternate_email"
                type="email"
                placeholder="jane@gmail.com"
                {...register("alternate_email")}
              />
              {errors.alternate_email && (
                <p className="text-sm text-destructive">{errors.alternate_email.message}</p>
              )}
            </div>
          )}

          {!showClientHierarchy && (
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
          )}

          {showCategoryField && (
            <div className="space-y-2">
              <Label>Work Categories</Label>
              <CategoryMultiSelect
                categories={categories}
                selectedIds={categoryIds}
                onChange={(ids) => setValue("category_ids", ids, { shouldValidate: true })}
                placeholder={categoriesQuery.isLoading ? "Loading categories..." : "Select categories"}
              />
              {errors.category_ids && (
                <p className="text-sm text-destructive">{errors.category_ids.message}</p>
              )}
            </div>
          )}

          {showStaffHierarchy && (
            <div className="space-y-4 rounded-lg border border-dashed border-border p-3">
              <p className="text-xs font-medium text-muted-foreground">Reporting Structure</p>

              {currentUser?.role === ROLE_NAMES.SUPER_ADMIN && (
                <>
                  <div className="space-y-2">
                    <Label>Account Manager</Label>
                    <Select
                      value={managerId || ""}
                      onValueChange={(value) => setValue("manager_id", value, { shouldValidate: true })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select an Account Manager" />
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

              {currentUser?.role === ROLE_NAMES.ACCOUNT_MANAGER && (
                <>
                  <div className="space-y-2">
                    <Label>Account Manager</Label>
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
            </div>
          )}

          {showTeamLeadHierarchy && (
            <div className="space-y-4 rounded-lg border border-dashed border-border p-3">
              <p className="text-xs font-medium text-muted-foreground">Reporting Structure</p>

              {currentUser?.role === ROLE_NAMES.SUPER_ADMIN && (
                <div className="space-y-2">
                  <Label>Reporting Account Manager</Label>
                  <Select
                    value={managerId || ""}
                    onValueChange={(value) => setValue("manager_id", value, { shouldValidate: true })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select a reporting Account Manager" />
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
              )}

              {currentUser?.role === ROLE_NAMES.ACCOUNT_MANAGER && (
                <div className="space-y-2">
                  <Label>Reporting Account Manager</Label>
                  <Input value={currentUser.name} disabled />
                  <p className="text-xs text-muted-foreground">Automatically assigned as you.</p>
                </div>
              )}
            </div>
          )}

          {showClientHierarchy && (
            <div className="space-y-4 rounded-lg border border-dashed border-border p-3">
              <p className="text-xs font-medium text-muted-foreground">Reporting Structure</p>

              <div className="space-y-2">
                <Label>Account Manager</Label>
                <Select
                  value={managerId || ""}
                  onValueChange={(value) => setValue("manager_id", value, { shouldValidate: true })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select an Account Manager" />
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
                <p className="text-xs text-muted-foreground">
                  This Client user will also appear as a client company owned by the selected
                  Account Manager.
                </p>
              </div>

              <div className="space-y-2">
                <Label>Contact Emails</Label>
                {contactEmailsArray.fields.map((field, index) => (
                  <div key={field.id} className="flex items-center gap-2">
                    <Input
                      placeholder="contact@hospital.com"
                      {...register(`contact_emails.${index}.value` as const)}
                    />
                    {contactEmailsArray.fields.length > 1 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => contactEmailsArray.remove(index)}
                        aria-label="Remove contact email"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                ))}
                {contactEmailErrorMessages.map((message, index) => (
                  <p key={index} className="text-sm text-destructive">
                    {message}
                  </p>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="gap-1"
                  onClick={() => contactEmailsArray.append({ value: "" })}
                >
                  <Plus className="h-4 w-4" />
                  Add Contact
                </Button>
              </div>
            </div>
          )}

          {!showClientHierarchy && (
            <div className="space-y-2 rounded-lg border border-dashed border-border p-3">
              <Label>
                Reporting Manager (Organization Chart)
                {showInternalRoleFields &&
                  !REPORTING_MANAGER_OPTIONAL_ROLE_NAMES.includes(roleName ?? "") && (
                    <span className="text-destructive"> *</span>
                  )}
              </Label>
              <Select
                value={reportingManagerId || ""}
                onValueChange={(value) => setValue("reporting_manager_id", value, { shouldValidate: true })}
              >
                <SelectTrigger>
                  <SelectValue
                    placeholder={
                      showInternalRoleFields &&
                      REPORTING_MANAGER_OPTIONAL_ROLE_NAMES.includes(roleName ?? "")
                        ? "Select a reporting manager (optional)"
                        : "Select a reporting manager"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {reportingManagerOptions.map((u) => (
                    <SelectItem key={u.user_id} value={u.user_id}>
                      {u.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.reporting_manager_id && (
                <p className="text-sm text-destructive">{errors.reporting_manager_id.message}</p>
              )}
              <p className="text-xs text-muted-foreground">
                Determines this person&apos;s position in the Organization Chart. Independent of the
                Account Manager/Team Lead assignment above — any active user, of any role, may be
                picked.
                {showInternalRoleFields &&
                REPORTING_MANAGER_OPTIONAL_ROLE_NAMES.includes(roleName ?? "")
                  ? " Leave unset if they have no reporting manager (e.g. the top of the company)."
                  : ""}
              </p>
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
