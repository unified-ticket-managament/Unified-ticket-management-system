import axios, { InternalAxiosRequestConfig } from "axios";

// ==========================================================
// Separate axios instance pointed at the RBAC service.
//
// RBAC is the sole issuer of tokens (login/refresh/me) — kept as its
// own instance rather than reusing `apiClient` (this service's own
// backend) since the two have different base URLs, and sharing one
// instance's interceptors would risk a refresh loop against the
// wrong backend.
// ==========================================================

export const authClient = axios.create({
  baseURL: import.meta.env.VITE_RBAC_API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// /auth/login and /auth/refresh don't need a token, but /auth/me does —
// attach it whenever one is already stored, same as apiClient.
authClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const access = localStorage.getItem("access_token");
  if (access) {
    config.headers.Authorization = `Bearer ${access}`;
  }
  return config;
});
