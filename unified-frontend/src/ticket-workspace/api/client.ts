import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import rbacApi, { clearTokens, setTokens } from "@/lib/api";

// ==========================================================
// Axios instance pointed at the Ticketing routes, which since the
// RBAC/Ticketing backend merge are served by the same unified FastAPI
// app as RBAC's own `@/lib/api` instance — just mounted unprefixed
// instead of under /api/v1 (see unified-backend/app/main.py). Kept as
// a separate axios instance (rather than reusing `rbacApi`) because
// the base URL and interceptor behavior still differ; both share the
// same localStorage tokens since they're the same origin/app.
// `rbacApi` is reused only for the actual refresh call below.
// ==========================================================

const TICKETING_API_URL =
  process.env.NEXT_PUBLIC_TICKETING_API_URL || "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: TICKETING_API_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

const getStoredTokens = () => {
  if (typeof window === "undefined") return { access: null, refresh: null };
  return {
    access: localStorage.getItem("access_token"),
    refresh: localStorage.getItem("refresh_token"),
  };
};

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

let refreshPromise: Promise<string | null> | null = null;

// On a 401, try exactly once to refresh the access token (against
// RBAC, the sole issuer, via `rbacApi`) and retry the original request
// against Ticketing. A second 401 after that (or no refresh token at
// all) means the session is genuinely gone — clear it and send the
// user to RBAC's own /login.
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
      window.location.href = "/login";
      return Promise.reject(error);
    }

    if (!refreshPromise) {
      refreshPromise = rbacApi
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
    // A request aborted via AbortController (e.g. a stale-response
    // guard superseding an in-flight fetch, or a page unmounting
    // mid-request) is not a backend error — it's expected, silent
    // cancellation. Passing it through unchanged (rather than
    // rewrapping it into a plain Error below) preserves
    // axios.isCancel()/error.code === "ERR_CANCELED" for every
    // caller's own cancellation check; rewrapping it turned every
    // such check into a false negative (a plain Error's `.message`
    // happens to be the literal string "canceled", but its `.name`
    // is just "Error", not "CanceledError"), which is what let a
    // routine, intentional cancellation surface as a visible
    // "canceled" error toast instead of being silently absorbed.
    if (axios.isCancel(error)) {
      return Promise.reject(error);
    }

    const detail =
      error?.response?.data?.detail ??
      error?.message ??
      "Something went wrong while talking to the backend.";

    return Promise.reject(
      new Error(typeof detail === "string" ? detail : JSON.stringify(detail))
    );
  }
);
