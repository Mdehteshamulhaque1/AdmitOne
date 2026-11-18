import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { api, clearTokens, getAccessToken, getRefreshToken, setTokens } from "@/lib/api"
import type { AuthTokens, MeResponse, Organization, Permission, User } from "@/lib/types"

interface RegisterPayload {
  email: string
  full_name: string
  phone?: string
  password: string
}

interface AuthContextValue {
  user: User | null
  org: Organization | null
  loading: boolean
  isAuthenticated: boolean
  /**
   * The caller's effective permissions, as computed by the server in
   * `GET /api/auth/me/`. Drives *rendering only* -- see `can()`.
   */
  permissions: Permission[]
  can: (perm: Permission) => boolean
  login: (email: string, password: string) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [org, setOrg] = useState<Organization | null>(null)
  const [permissions, setPermissions] = useState<Permission[]>([])
  const [loading, setLoading] = useState(true)

  const refreshUser = useCallback(async () => {
    try {
      const me = await api<MeResponse>("/api/auth/me/")
      setUser(me.user)
      setOrg(me.organization)
      setPermissions(me.permissions ?? [])
    } catch {
      clearTokens()
      setUser(null)
      setOrg(null)
      setPermissions([])
    }
  }, [])

  useEffect(() => {
    if (!getAccessToken()) {
      setLoading(false)
      return
    }
    void refreshUser().finally(() => setLoading(false))
  }, [refreshUser])

  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await api<AuthTokens>("/api/auth/token/", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      })
      setTokens(tokens)
      await refreshUser()
    },
    [refreshUser],
  )

  const register = useCallback(
    async (payload: RegisterPayload) => {
      const response = await api<{ user: User } & AuthTokens>("/api/auth/register/", {
        method: "POST",
        body: JSON.stringify(payload),
      })
      setTokens({ access: response.access, refresh: response.refresh })
      setUser(response.user)
      setOrg(null)
      // A freshly registered user has no workspace and no role yet, so no
      // permissions. Re-fetched after onboarding completes.
      setPermissions([])
    },
    [],
  )

  const logout = useCallback(() => {
    // Best-effort server-side invalidation: blacklist the refresh token so it
    // can never be replayed. Local tokens are always cleared regardless of
    // whether the request reached the backend.
    const refresh = getRefreshToken()
    if (refresh) {
      void api("/api/auth/logout/", {
        method: "POST",
        body: JSON.stringify({ refresh }),
      }).catch(() => undefined)
    }
    clearTokens()
    setUser(null)
    setOrg(null)
    setPermissions([])
  }, [])

  // Fails closed: until the server has answered, nothing is permitted, so a
  // gated control is never rendered for a user whose capabilities are unknown.
  const can = useCallback(
    (perm: Permission) => permissions.includes(perm),
    [permissions],
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      org,
      loading,
      isAuthenticated: Boolean(user),
      permissions,
      can,
      login,
      register,
      logout,
      refreshUser,
    }),
    [user, org, loading, permissions, can, login, register, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
