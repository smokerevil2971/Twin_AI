import React, { createContext, useContext, useState, useEffect } from 'react'
import api from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('twinai_token')
    const stored = localStorage.getItem('twinai_user')
    if (token && stored) {
      setUser(JSON.parse(stored))
    }
    setLoading(false)
  }, [])

  const login = async (email, password) => {
    const res = await api.post('/auth/login', { email, password })
    const { access_token, tenant_id, email: userEmail } = res.data.data
    localStorage.setItem('twinai_token', access_token)
    localStorage.setItem('twinai_user', JSON.stringify({ email: userEmail, tenant_id }))
    setUser({ email: userEmail, tenant_id })
    return res.data
  }

  const logout = () => {
    localStorage.removeItem('twinai_token')
    localStorage.removeItem('twinai_user')
    setUser(null)
    window.location.href = '/login'
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
