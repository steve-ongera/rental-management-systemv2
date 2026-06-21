import { createContext, useContext, useEffect, useState } from "react";
import api, { clearTenantSession } from "../api/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const stored = localStorage.getItem("tenant_user");
    return stored ? JSON.parse(stored) : null;
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("tenant_access_token");
    if (!token) {
      setLoading(false);
      return;
    }
    api
      .get("/auth/me/")
      .then(({ data }) => {
        setUser(data);
        localStorage.setItem("tenant_user", JSON.stringify(data));
      })
      .catch(() => {
        // token invalid/expired and refresh failed -> interceptor already redirects
      })
      .finally(() => setLoading(false));
  }, []);

  async function login(username, password) {
    const { data } = await api.post("/auth/login/", { username, password });
    if (data.user.role !== "TENANT") {
      throw new Error("This portal is for tenants only. Please use the owner portal.");
    }
    localStorage.setItem("tenant_access_token", data.access);
    localStorage.setItem("tenant_refresh_token", data.refresh);
    localStorage.setItem("tenant_user", JSON.stringify(data.user));
    setUser(data.user);
    return data.user;
  }

  function logout() {
    clearTenantSession();
    setUser(null);
  }

  function updateUser(updated) {
    setUser(updated);
    localStorage.setItem("tenant_user", JSON.stringify(updated));
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, updateUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}