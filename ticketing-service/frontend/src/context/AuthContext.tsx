import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { getMe, login as loginRequest } from "@/api/auth";
import { clearTokens } from "@/api/client";
import type { CurrentUser } from "@/types";

// ==========================================================
// AuthContext
//
// Holds the real, RBAC-verified identity of the logged-in agent.
// Replaces the old WorkflowContext.agentName fake "acting as"
// dropdown — every mutating/reading call now carries this identity
// implicitly via the Bearer token, not as an explicit parameter.
// ==========================================================

interface AuthContextValue {
  currentUser: CurrentUser | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const hasToken = Boolean(localStorage.getItem("access_token"));
    if (!hasToken) {
      setIsLoading(false);
      return;
    }

    getMe()
      .then(setCurrentUser)
      .catch(() => {
        clearTokens();
        setCurrentUser(null);
      })
      .finally(() => setIsLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const user = await loginRequest(email, password);
    setCurrentUser(user);
  }

  function logout() {
    clearTokens();
    setCurrentUser(null);
    window.location.href = "/login";
  }

  return (
    <AuthContext.Provider value={{ currentUser, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuthContext must be used inside an <AuthProvider>.");
  }
  return ctx;
}
