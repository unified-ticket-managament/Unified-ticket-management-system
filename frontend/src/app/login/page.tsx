"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Shield,
  ShieldCheck,
  UserCog,
  Users,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";

const REMEMBERED_EMAIL_KEY = "rbac_remembered_email";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(8, "Password must be at least 8 characters"),
});

type LoginValues = z.infer<typeof loginSchema>;

type Status = "idle" | "loading" | "success";

export default function LoginPage() {
  const router = useRouter();
  const { toast } = useToast();
  const setUser = useAuthStore((s) => s.setUser);

  const [status, setStatus] = useState<Status>("idle");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [invalidCredentials, setInvalidCredentials] = useState(false);

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "admin@rbac.com", password: "Admin@123456" },
  });

  useEffect(() => {
    const remembered = localStorage.getItem(REMEMBERED_EMAIL_KEY);
    if (remembered) {
      setValue("email", remembered);
      setRememberMe(true);
    }
  }, [setValue]);

  const isLoading = status === "loading" || status === "success";

  const onSubmit = async (values: LoginValues) => {
    setStatus("loading");
    setInvalidCredentials(false);

    try {
      await authService.login(values);
      const user = await authService.me();

      if (rememberMe) {
        localStorage.setItem(REMEMBERED_EMAIL_KEY, values.email);
      } else {
        localStorage.removeItem(REMEMBERED_EMAIL_KEY);
      }

      setUser(user);
      setStatus("success");

      setTimeout(() => router.push("/dashboard"), 600);
    } catch {
      setStatus("idle");
      setInvalidCredentials(true);
      setValue("password", "");
      toast({
        variant: "destructive",
        title: "Sign in failed",
        description: "Invalid email or password. Please try again.",
      });
    }
  };

  const handleForgotPassword = () => {
    toast({
      title: "Forgot your password?",
      description: "Please contact your system administrator to reset it.",
    });
  };

  return (
    <div className="flex min-h-screen bg-background">
      {/* Left Panel */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 p-12 text-white lg:flex">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,_rgba(99,102,241,0.35),_transparent_45%)]" />
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_80%_80%,_rgba(59,130,246,0.25),_transparent_45%)]" />

        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="relative flex items-center gap-3"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 backdrop-blur">
            <Shield className="h-5 w-5" />
          </div>
          <span className="text-lg font-semibold tracking-tight">Enterprise RBAC</span>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="relative max-w-md"
        >
          <h1 className="text-3xl font-bold leading-tight tracking-tight">
            Welcome back to your access control center.
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-white/70">
            Manage users, roles, and permissions across your organization with
            confidence — every action tracked, every access controlled.
          </p>

          {/* Illustration */}
          <div className="relative mt-12 h-56">
            <motion.div
              animate={{ y: [0, -10, 0] }}
              transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
              className="absolute left-0 top-4 flex w-44 items-center gap-3 rounded-xl border border-white/10 bg-white/10 p-4 backdrop-blur"
            >
              <UserCog className="h-6 w-6 text-indigo-300" />
              <div>
                <p className="text-xs font-semibold">Role Manager</p>
                <p className="text-[11px] text-white/60">5 active roles</p>
              </div>
            </motion.div>

            <motion.div
              animate={{ y: [0, 10, 0] }}
              transition={{ duration: 6, repeat: Infinity, ease: "easeInOut", delay: 0.3 }}
              className="absolute right-0 top-20 flex w-48 items-center gap-3 rounded-xl border border-white/10 bg-white/10 p-4 backdrop-blur"
            >
              <KeyRound className="h-6 w-6 text-blue-300" />
              <div>
                <p className="text-xs font-semibold">Permissions</p>
                <p className="text-[11px] text-white/60">Granular access</p>
              </div>
            </motion.div>

            <motion.div
              animate={{ y: [0, -8, 0] }}
              transition={{ duration: 5.5, repeat: Infinity, ease: "easeInOut", delay: 0.6 }}
              className="absolute bottom-0 left-10 flex w-44 items-center gap-3 rounded-xl border border-white/10 bg-white/10 p-4 backdrop-blur"
            >
              <Users className="h-6 w-6 text-emerald-300" />
              <div>
                <p className="text-xs font-semibold">Team Directory</p>
                <p className="text-[11px] text-white/60">Org-wide visibility</p>
              </div>
            </motion.div>
          </div>
        </motion.div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="relative text-xs text-white/50"
        >
          &copy; {new Date().getFullYear()} Enterprise RBAC Platform. All rights reserved.
        </motion.p>
      </div>

      {/* Right Panel */}
      <div className="relative flex w-full flex-1 items-center justify-center overflow-hidden px-4 py-12 lg:w-1/2">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(120,119,198,0.12),_transparent_45%)] lg:hidden" />

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="relative w-full max-w-md"
        >
          <AnimatePresence mode="wait">
            {status === "success" ? (
              <motion.div
                key="success"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.3 }}
              >
                <Card className="border-border/60 bg-card/80 py-4 text-center backdrop-blur-xl">
                  <CardContent className="flex flex-col items-center gap-3 pt-6">
                    <motion.div
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{ type: "spring", stiffness: 300, damping: 18 }}
                      className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-500"
                    >
                      <CheckCircle2 className="h-8 w-8" />
                    </motion.div>
                    <CardTitle className="text-xl">Signed in successfully</CardTitle>
                    <CardDescription>Redirecting to your dashboard...</CardDescription>
                    <Progress value={100} className="mt-2 w-40" />
                  </CardContent>
                </Card>
              </motion.div>
            ) : (
              <motion.div
                key="form"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.2 }}
              >
                <Card className="border-border/60 bg-card/80 backdrop-blur-xl">
                  <CardHeader className="space-y-4 text-center">
                    <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground lg:hidden">
                      <ShieldCheck className="h-7 w-7" />
                    </div>
                    <div>
                      <CardTitle className="text-2xl">Welcome back</CardTitle>
                      <CardDescription>Sign in to the Enterprise RBAC Platform</CardDescription>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
                      <div className="space-y-2">
                        <Label htmlFor="email">Email</Label>
                        <Input
                          id="email"
                          type="email"
                          placeholder="you@company.com"
                          disabled={isLoading}
                          className={cn(invalidCredentials && "border-destructive focus-visible:ring-destructive")}
                          {...register("email", {
                            onChange: () => setInvalidCredentials(false),
                          })}
                        />
                        {errors.email && (
                          <p className="text-sm text-destructive">{errors.email.message}</p>
                        )}
                      </div>

                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <Label htmlFor="password">Password</Label>
                          <button
                            type="button"
                            onClick={handleForgotPassword}
                            className="text-xs font-medium text-primary hover:underline"
                          >
                            Forgot password?
                          </button>
                        </div>
                        <div className="relative">
                          <Input
                            id="password"
                            type={showPassword ? "text" : "password"}
                            placeholder="••••••••"
                            disabled={isLoading}
                            className={cn(
                              "pr-10",
                              invalidCredentials && "border-destructive focus-visible:ring-destructive"
                            )}
                            {...register("password", {
                              onChange: () => setInvalidCredentials(false),
                            })}
                          />
                          <button
                            type="button"
                            onClick={() => setShowPassword((prev) => !prev)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
                            aria-label={showPassword ? "Hide password" : "Show password"}
                            tabIndex={-1}
                          >
                            {showPassword ? (
                              <EyeOff className="h-4 w-4" />
                            ) : (
                              <Eye className="h-4 w-4" />
                            )}
                          </button>
                        </div>
                        {errors.password && (
                          <p className="text-sm text-destructive">{errors.password.message}</p>
                        )}
                        {invalidCredentials && !errors.password && (
                          <p className="text-sm text-destructive">Invalid email or password</p>
                        )}
                      </div>

                      <div className="flex items-center gap-2">
                        <Checkbox
                          id="remember-me"
                          checked={rememberMe}
                          onCheckedChange={(checked) => setRememberMe(checked === true)}
                          disabled={isLoading}
                        />
                        <Label htmlFor="remember-me" className="cursor-pointer text-sm font-normal">
                          Remember me on this device
                        </Label>
                      </div>

                      <Button type="submit" className="w-full" disabled={isLoading}>
                        {status === "loading" ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Signing in...
                          </>
                        ) : (
                          "Sign in"
                        )}
                      </Button>

                      <AnimatePresence>
                        {status === "loading" && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: "auto" }}
                            exit={{ opacity: 0, height: 0 }}
                          >
                            <Progress value={70} className="h-1" />
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </form>
                  </CardContent>
                </Card>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </div>
    </div>
  );
}
