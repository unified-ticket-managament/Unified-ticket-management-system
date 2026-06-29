"use client";

import { useMutation } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { ProfileForm } from "@/types";

const profileSchema = z.object({
  name: z.string().min(1).optional(),
  email: z.string().email().optional(),
  current_password: z.string().optional(),
  password: z.string().min(8).optional(),
});

export default function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const [message, setMessage] = useState<string | null>(null);

  const form = useForm<ProfileForm>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      name: user?.name || "",
      email: user?.email || "",
    },
  });

  const updateMutation = useMutation({
    mutationFn: authService.updateProfile,
    onSuccess: async () => {
      const me = await authService.me();
      setUser(me);
      setMessage("Profile updated successfully");
      form.reset({ name: me.name, email: me.email, password: "", current_password: "" });
    },
  });

  return (
    <div>
      <PageHeader title="Profile" description="View and update your account information" />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Account Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-sm text-muted-foreground">Role</p>
              <Badge className="mt-1">{user?.role}</Badge>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Permissions</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {user?.permissions.map((p) => (
                  <Badge key={p} variant="secondary">
                    {p}
                  </Badge>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Update Profile</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={form.handleSubmit((data) => {
                setMessage(null);
                updateMutation.mutate(data);
              })}
              className="space-y-4"
            >
              <div className="space-y-2">
                <Label>Name</Label>
                <Input {...form.register("name")} />
              </div>
              <div className="space-y-2">
                <Label>Email</Label>
                <Input type="email" {...form.register("email")} />
              </div>
              <div className="space-y-2">
                <Label>Current Password</Label>
                <Input type="password" {...form.register("current_password")} />
              </div>
              <div className="space-y-2">
                <Label>New Password</Label>
                <Input type="password" {...form.register("password")} />
              </div>
              {message && (
                <p className="text-sm text-emerald-500">{message}</p>
              )}
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? "Saving..." : "Save Changes"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
