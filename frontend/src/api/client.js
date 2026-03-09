import axios from 'axios'
import toast from 'react-hot-toast'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT token on every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('twinai_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Handle 401 → redirect to login
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('twinai_token')
      window.location.href = '/login'
    }
    const msg = err.response?.data?.error?.message
      || err.response?.data?.detail
      || 'Something went wrong'
    toast.error(msg)
    return Promise.reject(err)
  }
)

export default api
