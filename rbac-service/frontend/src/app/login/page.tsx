"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Eye, EyeOff, Loader2, Ticket } from "lucide-react";
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
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="mx-auto w-full max-w-[420px]"
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
              <Card className="rounded-2xl py-4 text-center shadow-xl">
                <CardContent className="flex flex-col items-center gap-3 pt-6">
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ type: "spring", stiffness: 300, damping: 18 }}
                    className="flex h-14 w-14 items-center justify-center rounded-full bg-success/15 text-success"
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
              <Card className="rounded-2xl shadow-xl">
                <div className="flex flex-col p-8 sm:p-10">
                  <div className="mb-6 text-center">
                    <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
                      <Ticket className="h-7 w-7" />
                    </div>
                    <CardTitle className="text-xl">Unified Ticket Management System</CardTitle>
                    <p className="mt-2 text-base font-semibold text-foreground">Welcome Back 👋</p>
                  </div>

                  <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
                    <div className="space-y-2">
                      <Label htmlFor="email">Email</Label>
                      <Input
                        id="email"
                        type="email"
                        placeholder="Enter your email"
                        disabled={isLoading}
                        className={cn(invalidCredentials && "border-destructive focus-visible:ring-destructive/20")}
                        {...register("email", {
                          onChange: () => setInvalidCredentials(false),
                        })}
                      />
                      {errors.email && (
                        <p className="text-sm text-destructive">{errors.email.message}</p>
                      )}
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="password">Password</Label>
                      <div className="relative">
                        <Input
                          id="password"
                          type={showPassword ? "text" : "password"}
                          placeholder="Enter your password"
                          disabled={isLoading}
                          className={cn(
                            "pr-10",
                            invalidCredentials && "border-destructive focus-visible:ring-destructive/20"
                          )}
                          {...register("password", {
                            onChange: () => setInvalidCredentials(false),
                          })}
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword((prev) => !prev)}
                          className="absolute right-3 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-primary"
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
                        Remember me
                      </Label>
                    </div>

                    <Button type="submit" className="w-full" disabled={isLoading}>
                      {status === "loading" ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Logging in...
                        </>
                      ) : (
                        "Login"
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

                    <button
                      type="button"
                      onClick={handleForgotPassword}
                      className="block w-full text-center text-sm font-medium text-primary hover:underline"
                    >
                      Forgot Password?
                    </button>
                  </form>
                </div>
              </Card>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
