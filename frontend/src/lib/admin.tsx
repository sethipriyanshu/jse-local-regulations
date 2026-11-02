import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'

type AdminState = {
  isAdmin: boolean
  checked: boolean
  login: (passcode: string) => Promise<void>
  logout: () => Promise<void>
}

const AdminContext = createContext<AdminState | null>(null)

/** Tracks whether this browser is in the admin view (signed cookie set by the API). */
export function AdminProvider({ children }: { children: ReactNode }) {
  const [isAdmin, setIsAdmin] = useState(false)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    api<{ admin: boolean }>('/admin/session')
      .then((s) => setIsAdmin(s.admin))
      .catch(() => setIsAdmin(false))
      .finally(() => setChecked(true))
  }, [])

  const login = useCallback(async (passcode: string) => {
    await api('/admin/login', { method: 'POST', body: JSON.stringify({ passcode }) })
    setIsAdmin(true)
  }, [])

  const logout = useCallback(async () => {
    await api('/admin/logout', { method: 'POST' })
    setIsAdmin(false)
  }, [])

  return (
    <AdminContext.Provider value={{ isAdmin, checked, login, logout }}>
      {children}
    </AdminContext.Provider>
  )
}

export function useAdmin(): AdminState {
  const ctx = useContext(AdminContext)
  if (!ctx) throw new Error('useAdmin must be used inside <AdminProvider>')
  return ctx
}
