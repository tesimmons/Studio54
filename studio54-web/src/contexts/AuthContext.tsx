import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import type { AuthUser, UserRole } from '../types'

interface AuthContextType {
  user: AuthUser | null
  token: string | null
  isLoading: boolean
  isAuthenticated: boolean
  isDirector: boolean
  isDjOrAbove: boolean
  hasRole: (...roles: UserRole[]) => boolean
  login: (token: string, user: AuthUser) => void
  logout: () => void
  updateUser: (user: AuthUser) => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Restore session from localStorage on mount
  useEffect(() => {
    const storedToken = localStorage.getItem('studio54_token')
    const storedUser = localStorage.getItem('studio54_user')

    if (storedToken && storedUser) {
      try {
        const parsed = JSON.parse(storedUser) as AuthUser
        setToken(storedToken)
        setUser(parsed)
      } catch {
        localStorage.removeItem('studio54_token')
        localStorage.removeItem('studio54_user')
      }
    }
    setIsLoading(false)
  }, [])

  const login = useCallback((newToken: string, newUser: AuthUser) => {
    setToken(newToken)
    setUser(newUser)
    localStorage.setItem('studio54_token', newToken)
    localStorage.setItem('studio54_user', JSON.stringify(newUser))
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    localStorage.removeItem('studio54_token')
    localStorage.removeItem('studio54_user')
  }, [])

  const updateUser = useCallback((updatedUser: AuthUser) => {
    setUser(updatedUser)
    localStorage.setItem('studio54_user', JSON.stringify(updatedUser))
  }, [])

  const hasRole = useCallback((...roles: UserRole[]) => {
    if (!user) return false
    return roles.includes(user.role)
  }, [user])

  const isDirector = user?.role === 'director'
  const isDjOrAbove = user?.role === 'director' || user?.role === 'dj'

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        isAuthenticated: !!user && !!token,
        isDirector,
        isDjOrAbove,
        hasRole,
        login,
        logout,
        updateUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
