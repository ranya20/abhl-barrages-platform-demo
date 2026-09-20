import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  changeOwnPassword,
  getCurrentUser,
  loginAccount,
  logoutAccount,
  signupAccount,
} from "../api";


const AuthContext = createContext(null);
const TOKEN_KEY = "abhl_access_token";


export function getStoredToken() {
  return window.sessionStorage.getItem(TOKEN_KEY) || "";
}


function storeToken(token) {
  if (token) {
    window.sessionStorage.setItem(TOKEN_KEY, token);
  } else {
    window.sessionStorage.removeItem(TOKEN_KEY);
  }
}


export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState("");

  function clearSession() {
    storeToken("");
    setUser(null);
  }

  useEffect(() => {
    let cancelled = false;
    const token = getStoredToken();

    if (!token) {
      setLoading(false);
      return undefined;
    }

    getCurrentUser()
      .then((result) => {
        if (!cancelled) {
          setUser(result.user);
          setAuthError("");
        }
      })
      .catch((error) => {
        if (!cancelled) {
          clearSession();
          setAuthError(error.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function handleUnauthorized() {
      clearSession();
      setAuthError("Votre session a expiré. Veuillez vous reconnecter.");
    }

    window.addEventListener("abhl:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("abhl:unauthorized", handleUnauthorized);
  }, []);

  async function login(identifier, password) {
    setAuthError("");
    const result = await loginAccount({ identifier, password });
    storeToken(result.access_token);
    setUser(result.user);
    return result;
  }

  async function signup(payload) {
    setAuthError("");
    return signupAccount(payload);
  }

  async function logout() {
    try {
      if (getStoredToken()) {
        await logoutAccount();
      }
    } catch {
      // La session locale doit être supprimée même si le backend est indisponible.
    } finally {
      clearSession();
    }
  }

  async function changePassword(payload) {
    const result = await changeOwnPassword(payload);
    setUser(result.user);
    return result;
  }

  async function refreshUser() {
    const result = await getCurrentUser();
    setUser(result.user);
    return result.user;
  }

  const value = useMemo(() => {
    const role = user?.role_code || "";
    return {
      user,
      loading,
      authError,
      setAuthError,
      login,
      signup,
      logout,
      changePassword,
      refreshUser,
      isAuthenticated: Boolean(user),
      isAdmin: role === "ADMIN",
      canWrite: ["ADMIN", "SAISIE", "VALIDATEUR"].includes(role),
    };
  }, [user, loading, authError]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}


export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth doit être utilisé dans AuthProvider.");
  }
  return context;
}
