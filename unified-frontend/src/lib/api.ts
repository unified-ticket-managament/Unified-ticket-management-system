import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export const api = axios.create({
  baseURL: API_URL,
  headers: { "Content-Type": "application/json" },
  withCredentials: false,
});

let refreshPromise: Promise<string | null> | null = null;

// Tokens are cached in-memory per tab, seeded once from localStorage at
// module load, rather than re-read from localStorage on every request.
// localStorage is shared across every tab of the same browser origin —
// reading it fresh per-request meant a login in one tab silently
// reassigned an already-open tab's identity on its very next request
// (including a real write, e.g. an Internal Note's sender), without any
// reload. Seeding once at load still lets a freshly opened tab pick up
// whatever's currently logged in; only an already-open tab's mid-session
// identity is now stable until that tab's own login/refresh/logout.
let cachedTokens: { access: string | null; refresh: string | null } =
  typeof window === "undefined"
    ? { access: null, refresh: null }
    : {
        access: localStorage.getItem("access_token"),
        refresh: localStorage.getItem("refresh_token"),
      };

export const getStoredTokens = () => cachedTokens;

export const setTokens = (accessToken: string, refreshToken: string) => {
  localStorage.setItem("access_token", accessToken);
  localStorage.setItem("refresh_token", refreshToken);
  cachedTokens = { access: accessToken, refresh: refreshToken };
};

export const clearTokens = () => {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  cachedTokens = { access: null, refresh: null };
};

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const { access } = getStoredTokens();
  if (access) {
    config.headers.Authorization = `Bearer ${access}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
    const isAuthEndpoint = originalRequest.url?.includes("/auth/login") || originalRequest.url?.includes("/auth/refresh");

    if (error.response?.status !== 401 || originalRequest._retry || isAuthEndpoint) {
      return Promise.reject(error);
    }

    originalRequest._retry = true;
    const { refresh } = getStoredTokens();

    if (!refresh) {
      clearTokens();
      if (typeof window !== "undefined" && !window.location.pathname.includes("/login")) {
        window.location.href = "/login";
      }
      return Promise.reject(error);
    }

    if (!refreshPromise) {
      refreshPromise = api
        .post("/auth/refresh", { refresh_token: refresh })
        .then((res) => {
          const { access_token, refresh_token } = res.data;
          setTokens(access_token, refresh_token);
          return access_token as string;
        })
        .catch(() => {
          clearTokens();
          if (typeof window !== "undefined") {
            window.location.href = "/login";
          }
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
    return api(originalRequest);
  }
);

export default api;
