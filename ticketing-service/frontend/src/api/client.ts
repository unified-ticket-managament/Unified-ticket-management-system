import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import { authClient } from "./authClient";

// ==========================================================
// Axios instance pointed at the FastAPI backend.
//
// Base URL comes from VITE_API_BASE_URL (.env), so the
// backend host can change without touching any code.
// ==========================================================

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// ==========================================================
// Token storage — RBAC issues these (login/refresh), this app only
// stores and attaches them. Same localStorage keys and shape as
// RBAC's own frontend so the pattern is consistent across both.
// ==========================================================

const getStoredTokens = () => ({
  access: localStorage.getItem("access_token"),
  refresh: localStorage.getItem("refresh_token"),
});

export const setTokens = (accessToken: string, refreshToken: string) => {
  localStorage.setItem("access_token", accessToken);
  localStorage.setItem("refresh_token", refreshToken);
};

export const clearTokens = () => {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
};

let refreshPromise: Promise<string | null> | null = null;

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const { access } = getStoredTokens();
  if (access) {
    config.headers.Authorization = `Bearer ${access}`;
  }
  return config;
});

// Multipart requests (file uploads) must let the browser set its own
// Content-Type with the multipart boundary — the default JSON header
// above would otherwise be sent as-is and the backend couldn't parse it.
apiClient.interceptors.request.use((config) => {
  if (config.data instanceof FormData) {
    delete config.headers["Content-Type"];
  }
  return config;
});

// On a 401, try exactly once to refresh the access token (against
// RBAC, the sole issuer) and retry the original request. A second
// 401 after that (or no refresh token at all) means the session is
// genuinely gone — clear it and send the user to /login.
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    if (error.response?.status !== 401 || originalRequest._retry) {
      return Promise.reject(error);
    }

    originalRequest._retry = true;
    const { refresh } = getStoredTokens();

    if (!refresh) {
      clearTokens();
      if (!window.location.pathname.includes("/login")) {
        window.location.href = "/login";
      }
      return Promise.reject(error);
    }

    if (!refreshPromise) {
      refreshPromise = authClient
        .post("/auth/refresh", { refresh_token: refresh })
        .then((res) => {
          const { access_token, refresh_token } = res.data;
          setTokens(access_token, refresh_token);
          return access_token as string;
        })
        .catch(() => {
          clearTokens();
          window.location.href = "/login";
          return null;
        })
        .finally(() => {
          refreshPromise = null;
        });
    }

    const newAccessToken = await refreshPromise;
    if (!newAccessToken) {
      return Promise.reject(error);
    }

    originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
    return apiClient(originalRequest);
  }
);

// Surface backend error details consistently as a single
// readable message, so UI components don't each need to
// know FastAPI's error response shape.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail =
      error?.response?.data?.detail ??
      error?.message ??
      "Something went wrong while talking to the backend.";

    return Promise.reject(
      new Error(typeof detail === "string" ? detail : JSON.stringify(detail))
    );
  }
);
