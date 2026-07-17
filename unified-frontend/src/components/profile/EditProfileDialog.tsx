"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { Language, LANGUAGES } from "@/lib/i18n/translations";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { useProfileExtrasStore } from "@/store/profile-extras-store";
import { useSettingsStore } from "@/store/settings-store";

// The single edit surface for every user-editable Profile field — reached
// from the page-level "Edit Profile" button and each info card's own Edit
// button. Reuses exactly the same backend/service calls the Settings
// page's inline form already uses (authService.updateProfile,
// profile-extras-store, settings-store's language setter); this only adds
// a modal presentation, no new business logic.
const editProfileSchema = z.object({
  name: z.string().min(1, "Name is required"),
  email: z.string().email("Enter a valid email"),
  phone: z.string().optional(),
  alternateEmail: z.string().email("Enter a valid email").optional().or(z.literal("")),
  officeLocation: z.string().optional(),
  employeeId: z.string().optional(),
  dateOfBirth: z.string().optional(),
  timezone: z.string().optional(),
  language: z.string().optional(),
  dateFormat: z.string().optional(),
  timeFormat: z.string().optional(),
  defaultDashboard: z.string().optional(),
});

type EditProfileValues = z.infer<typeof editProfileSchema>;

const DATE_FORMAT_OPTIONS = ["MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD"];
const TIME_FORMAT_OPTIONS = [
  { value: "12h", label: "12-hour" },
  { value: "24h", label: "24-hour" },
];

interface EditProfileDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function EditProfileDialog({ open, onOpenChange }: EditProfileDialogProps) {
  const { toast } = useToast();
  const currentUser = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const extras = useProfileExtrasStore();
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);

  const form = useForm<EditProfileValues>({
    resolver: zodResolver(editProfileSchema),
    defaultValues: {
      name: currentUser?.name ?? "",
      email: currentUser?.email ?? "",
      phone: extras.phone,
      alternateEmail: extras.alternateEmail,
      officeLocation: extras.address,
      employeeId: extras.employeeId,
      dateOfBirth: extras.dateOfBirth,
      timezone: extras.timezone,
      language,
      dateFormat: extras.dateFormat,
      timeFormat: extras.timeFormat,
      defaultDashboard: extras.defaultDashboard,
    },
  });

  useEffect(() => {
    if (open) {
      form.reset({
        name: currentUser?.name ?? "",
        email: currentUser?.email ?? "",
        phone: extras.phone,
        alternateEmail: extras.alternateEmail,
        officeLocation: extras.address,
        employeeId: extras.employeeId,
        dateOfBirth: extras.dateOfBirth,
        timezone: extras.timezone,
        language,
        dateFormat: extras.dateFormat,
        timeFormat: extras.timeFormat,
        defaultDashboard: extras.defaultDashboard,
      });
    }
    // Only re-sync when the dialog opens, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const mutation = useMutation({
    mutationFn: async (values: EditProfileValues) => {
      if (values.name !== currentUser?.name || values.email !== currentUser?.email) {
        await authService.updateProfile({ name: values.name, email: values.email });
      }
      extras.setProfileExtras({
        phone: values.phone ?? "",
        alternateEmail: values.alternateEmail ?? "",
        address: values.officeLocation ?? "",
        employeeId: values.employeeId ?? "",
        dateOfBirth: values.dateOfBirth ?? "",
        timezone: values.timezone ?? "",
        dateFormat: values.dateFormat ?? "MM/DD/YYYY",
        timeFormat: values.timeFormat ?? "12h",
        defaultDashboard: values.defaultDashboard ?? "Dashboard",
      });
      if (values.language && values.language !== language) {
        setLanguage(values.language as Language);
      }
    },
    onSuccess: async () => {
      const me = await authService.me();
      setUser(me);
      toast({ title: "Profile updated", description: "Your changes have been saved." });
      onOpenChange(false);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to update profile",
        description: error.response?.data?.detail ?? "Please check your details and try again.",
      });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Profile</DialogTitle>
        </DialogHeader>

        <form
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          className="space-y-6"
        >
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-muted-foreground">Personal Information</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">Full Name</Label>
                <Input id="name" {...form.register("name")} />
                {form.formState.errors.name && (
                  <p className="text-sm text-destructive">{form.formState.errors.name.message}</p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="employeeId">Employee ID</Label>
                <Input id="employeeId" placeholder="EMP-00123" {...form.register("employeeId")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="dateOfBirth">Date of Birth</Label>
                <Input id="dateOfBirth" type="date" {...form.register("dateOfBirth")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="timezone">Time Zone</Label>
                <Input id="timezone" placeholder="e.g. America/New_York" {...form.register("timezone")} />
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-muted-foreground">Contact Information</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" {...form.register("email")} />
                {form.formState.errors.email && (
                  <p className="text-sm text-destructive">{form.formState.errors.email.message}</p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="alternateEmail">Alternate Email</Label>
                <Input id="alternateEmail" type="email" {...form.register("alternateEmail")} />
                {form.formState.errors.alternateEmail && (
                  <p className="text-sm text-destructive">
                    {form.formState.errors.alternateEmail.message}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="phone">Phone</Label>
                <Input id="phone" placeholder="+1 555 000 1234" {...form.register("phone")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="officeLocation">Office Location</Label>
                <Input
                  id="officeLocation"
                  placeholder="Street, City, Country"
                  {...form.register("officeLocation")}
                />
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-muted-foreground">Preferences</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>Language</Label>
                <Select
                  value={form.watch("language")}
                  onValueChange={(value) => form.setValue("language", value)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LANGUAGES.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Default Dashboard</Label>
                <Input {...form.register("defaultDashboard")} />
              </div>
              <div className="space-y-2">
                <Label>Date Format</Label>
                <Select
                  value={form.watch("dateFormat")}
                  onValueChange={(value) => form.setValue("dateFormat", value)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DATE_FORMAT_OPTIONS.map((option) => (
                      <SelectItem key={option} value={option}>
                        {option}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Time Format</Label>
                <Select
                  value={form.watch("timeFormat")}
                  onValueChange={(value) => form.setValue("timeFormat", value)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TIME_FORMAT_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </section>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting || mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save Changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
