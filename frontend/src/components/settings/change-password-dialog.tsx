"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
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
import { useToast } from "@/hooks/use-toast";
import { authService } from "@/services";

const changePasswordSchema = z
  .object({
    old_password: z.string().min(1, "Enter your current password"),
    new_password: z.string().min(8, "Password must be at least 8 characters"),
    confirm_password: z.string().min(1, "Confirm your new password"),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });

type ChangePasswordValues = z.infer<typeof changePasswordSchema>;

interface PasswordFieldProps {
  id: string;
  label: string;
  visible: boolean;
  onToggleVisible: () => void;
  error?: string;
  registration: ReturnType<typeof useForm<ChangePasswordValues>>["register"];
  name: keyof ChangePasswordValues;
}

function PasswordField({ id, label, visible, onToggleVisible, error, registration, name }: PasswordFieldProps) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input
          id={id}
          type={visible ? "text" : "password"}
          placeholder="••••••••"
          className="pr-10"
          {...registration(name)}
        />
        <button
          type="button"
          onClick={onToggleVisible}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
          aria-label={visible ? "Hide password" : "Show password"}
          tabIndex={-1}
        >
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}

interface ChangePasswordDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ChangePasswordDialog({ open, onOpenChange }: ChangePasswordDialogProps) {
  const { toast } = useToast();
  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { old_password: "", new_password: "", confirm_password: "" },
  });

  useEffect(() => {
    if (open) {
      reset({ old_password: "", new_password: "", confirm_password: "" });
      setShowOld(false);
      setShowNew(false);
      setShowConfirm(false);
    }
  }, [open, reset]);

  const mutation = useMutation({
    mutationFn: (values: ChangePasswordValues) =>
      authService.changePassword({
        old_password: values.old_password,
        new_password: values.new_password,
      }),
    onSuccess: () => {
      toast({ title: "Password updated", description: "Your password has been changed successfully." });
      onOpenChange(false);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to update password",
        description: error.response?.data?.detail ?? "Please check your details and try again.",
      });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change Password</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit((values) => mutation.mutate(values))} className="space-y-4">
          <PasswordField
            id="old_password"
            label="Old Password"
            visible={showOld}
            onToggleVisible={() => setShowOld((prev) => !prev)}
            error={errors.old_password?.message}
            registration={register}
            name="old_password"
          />
          <PasswordField
            id="new_password"
            label="New Password"
            visible={showNew}
            onToggleVisible={() => setShowNew((prev) => !prev)}
            error={errors.new_password?.message}
            registration={register}
            name="new_password"
          />
          <PasswordField
            id="confirm_password"
            label="Confirm Password"
            visible={showConfirm}
            onToggleVisible={() => setShowConfirm((prev) => !prev)}
            error={errors.confirm_password?.message}
            registration={register}
            name="confirm_password"
          />

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Update Password
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
