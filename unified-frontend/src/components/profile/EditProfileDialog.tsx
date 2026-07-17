"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PROFILE_RECORD_QUERY_KEY } from "@/hooks/use-profile";
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { User } from "@/types";

type EditProfileValues = {
  name: string;
  email: string;
  phoneNumber?: string;
  alternateEmail?: string;
  officeLocation?: string;
  dateOfBirth?: string;
  department?: string;
};

interface EditProfileDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  record?: User;
}

function defaultsFromRecord(record: User | undefined, name: string, email: string): EditProfileValues {
  return {
    name,
    email,
    phoneNumber: record?.phone_number ?? "",
    alternateEmail: record?.alternate_email ?? "",
    officeLocation: record?.office_location ?? "",
    dateOfBirth: record?.date_of_birth ?? "",
    department: record?.department ?? "",
  };
}

// The single edit surface for every user-editable identity/contact
// Profile field — reached from the page header's "Edit Profile"
// button. Every field here saves straight to the `users` table via
// PATCH /auth/me (see AuthService.update_profile). Application
// preferences (Language/Time Zone/Date Format/Time Format/Default
// Dashboard) live exclusively in the Settings dialog now, not here —
// see root CLAUDE.md's Profile module section for why the two edit
// surfaces were split this way (one field, one editable place).
export function EditProfileDialog({ open, onOpenChange, record }: EditProfileDialogProps) {
  const { toast } = useToast();
  const { t } = useTranslation();
  const currentUser = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const queryClient = useQueryClient();

  const editProfileSchema = useMemo(
    () =>
      z.object({
        name: z.string().min(1, t("profile.validationNameRequired")),
        email: z.string().email(t("profile.validationInvalidEmail")),
        phoneNumber: z.string().optional(),
        alternateEmail: z.string().email(t("profile.validationInvalidEmail")).optional().or(z.literal("")),
        officeLocation: z.string().optional(),
        dateOfBirth: z.string().optional(),
        department: z.string().optional(),
      }),
    [t]
  );

  const form = useForm<EditProfileValues>({
    resolver: zodResolver(editProfileSchema),
    defaultValues: defaultsFromRecord(record, currentUser?.name ?? "", currentUser?.email ?? ""),
  });

  useEffect(() => {
    if (open) {
      form.reset(defaultsFromRecord(record, currentUser?.name ?? "", currentUser?.email ?? ""));
    }
    // Only re-sync when the dialog opens, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const mutation = useMutation({
    mutationFn: async (values: EditProfileValues) => {
      await authService.updateProfile({
        name: values.name,
        email: values.email,
        phone_number: values.phoneNumber || null,
        alternate_email: values.alternateEmail || null,
        office_location: values.officeLocation || null,
        date_of_birth: values.dateOfBirth || null,
        department: values.department || null,
      });
    },
    onSuccess: async () => {
      const me = await authService.me();
      setUser(me);
      await queryClient.invalidateQueries({ queryKey: [PROFILE_RECORD_QUERY_KEY] });
      toast({
        title: t("profile.toastUpdatedTitle"),
        description: t("profile.toastUpdatedDescription"),
      });
      onOpenChange(false);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: t("profile.toastUpdateFailedTitle"),
        description: error.response?.data?.detail ?? t("common.checkDetailsError"),
      });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("profile.editProfile")}</DialogTitle>
        </DialogHeader>

        <form
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          className="space-y-6"
        >
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-muted-foreground">
              {t("profile.personalInformation")}
            </h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">{t("profile.fullName")}</Label>
                <Input id="name" {...form.register("name")} />
                {form.formState.errors.name && (
                  <p className="text-sm text-destructive">{form.formState.errors.name.message}</p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="dateOfBirth">{t("profile.dateOfBirth")}</Label>
                <Input id="dateOfBirth" type="date" {...form.register("dateOfBirth")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="department">{t("profile.department")}</Label>
                <Input
                  id="department"
                  placeholder={t("profile.departmentPlaceholder")}
                  {...form.register("department")}
                />
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-muted-foreground">
              {t("profile.contactInformation")}
            </h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="email">{t("profile.email")}</Label>
                <Input id="email" type="email" {...form.register("email")} />
                {form.formState.errors.email && (
                  <p className="text-sm text-destructive">{form.formState.errors.email.message}</p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="alternateEmail">{t("profile.alternateEmail")}</Label>
                <Input id="alternateEmail" type="email" {...form.register("alternateEmail")} />
                {form.formState.errors.alternateEmail && (
                  <p className="text-sm text-destructive">
                    {form.formState.errors.alternateEmail.message}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="phoneNumber">{t("profile.phone")}</Label>
                <Input
                  id="phoneNumber"
                  placeholder={t("profile.phonePlaceholder")}
                  {...form.register("phoneNumber")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="officeLocation">{t("profile.officeLocation")}</Label>
                <Input
                  id="officeLocation"
                  placeholder={t("profile.officeLocationPlaceholder")}
                  {...form.register("officeLocation")}
                />
              </div>
            </div>
          </section>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting || mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t("common.saveChanges")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
