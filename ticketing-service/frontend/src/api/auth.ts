import { authClient } from "./authClient";
import { setTokens } from "./client";
import type { CurrentUser } from "@/types";

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

// POST /auth/login (RBAC)
export async function login(email: string, password: string): Promise<CurrentUser> {
  const { data } = await authClient.post<TokenResponse>("/auth/login", {
    email,
    password,
  });
  setTokens(data.access_token, data.refresh_token);
  return getMe();
}

// GET /auth/me (RBAC)
export async function getMe(): Promise<CurrentUser> {
  const { data } = await authClient.get<CurrentUser>("/auth/me");
  return data;
}
