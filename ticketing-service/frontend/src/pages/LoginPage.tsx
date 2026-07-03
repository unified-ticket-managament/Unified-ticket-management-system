import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { TextInput } from "@/components/common/FormField";
import { Button } from "@/components/common/Button";
import { useAuthContext } from "@/context/AuthContext";

export function LoginPage() {
  const { currentUser, isLoading, login } = useAuthContext();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Already logged in — don't show the login form again.
  if (!isLoading && currentUser) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid email or password.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm rounded-md2 border border-border bg-surface p-7 shadow-card">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="flex h-10 w-10 items-center justify-center rounded-md2 bg-accent text-sm font-bold text-white shadow-xs">
            T
          </div>
          <h1 className="text-lg font-semibold text-slate-900">Agent Workspace</h1>
          <p className="text-xs text-muted">Sign in with your RBAC account to continue.</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <TextInput
            label="Email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <TextInput
            label="Password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error && (
            <p className="rounded-md2 border border-danger/20 bg-danger/5 px-3 py-2 text-xs text-danger">
              {error}
            </p>
          )}

          <Button type="submit" variant="primary" isLoading={isSubmitting} className="mt-1 w-full">
            Sign In
          </Button>
        </form>
      </div>
    </div>
  );
}
