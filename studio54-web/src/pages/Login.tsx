import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { FiLock, FiUser, FiEye, FiEyeOff } from 'react-icons/fi'
import { useAuth } from '../contexts/AuthContext'
import { authApi } from '../api/client'
import { S54 } from '../assets/graphics'

export default function Login() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const [mustChangePassword, setMustChangePassword] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [tempToken, setTempToken] = useState('')

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      const response = await authApi.login(username, password)

      if (response.user.must_change_password) {
        setTempToken(response.access_token)
        setMustChangePassword(true)
        setIsLoading(false)
        return
      }

      login(response.access_token, response.user)
      navigate('/artists')
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      setError(detail || 'Login failed. Please check your credentials.')
    } finally {
      setIsLoading(false)
    }
  }

  const handleChangePassword = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    if (newPassword.length < 6) {
      setError('Password must be at least 6 characters')
      return
    }

    setIsLoading(true)

    try {
      const updatedUser = await authApi.changePassword(password, newPassword, tempToken)
      login(tempToken, updatedUser)
      navigate('/artists')
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      setError(detail || 'Failed to change password')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4 relative"
      style={{
        backgroundImage: `url(${S54.background})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      {/* Dark overlay */}
      <div className="absolute inset-0 bg-[#0D1117]/80" />

      <div className="w-full max-w-sm relative z-10">
        {/* Logo */}
        <div className="text-center mb-8">
          <img src={S54.logo} alt="Studio54" className="w-[10.5rem] h-[10.5rem] mx-auto mb-4 object-contain" />
          <h1 className="text-3xl font-bold text-white">Studio54</h1>
          <p className="text-[#8B949E] mt-1">Music Acquisition System</p>
        </div>

        {/* Card */}
        <div className="bg-[#161B22] rounded-xl shadow-2xl p-6 border border-[#30363D]">
          {!mustChangePassword ? (
            <>
              <h2 className="text-lg font-semibold text-white mb-4">Sign In</h2>
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-[#8B949E] mb-1">Username</label>
                  <div className="relative">
                    <FiUser className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B949E] w-4 h-4" />
                    <input
                      type="text"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="w-full pl-10 pr-4 py-2.5 bg-[#0D1117] border border-[#30363D] rounded-lg text-white placeholder-[#8B949E] focus:outline-none focus:ring-2 focus:ring-[#FF1493] focus:border-transparent"
                      placeholder="Enter username"
                      autoFocus
                      autoComplete="username"
                      required
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-[#8B949E] mb-1">Password</label>
                  <div className="relative">
                    <FiLock className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B949E] w-4 h-4" />
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="w-full pl-10 pr-10 py-2.5 bg-[#0D1117] border border-[#30363D] rounded-lg text-white placeholder-[#8B949E] focus:outline-none focus:ring-2 focus:ring-[#FF1493] focus:border-transparent"
                      placeholder="Enter password"
                      autoComplete="current-password"
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[#8B949E] hover:text-[#E6EDF3]"
                    >
                      {showPassword ? <FiEyeOff className="w-4 h-4" /> : <FiEye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                {error && (
                  <div className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full py-2.5 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ background: 'linear-gradient(135deg, #FF1493, #FF8C00)' }}
                >
                  {isLoading ? 'Signing in...' : 'Sign In'}
                </button>
              </form>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-white mb-2">Change Password</h2>
              <p className="text-sm text-[#8B949E] mb-4">You must change your password before continuing.</p>
              <form onSubmit={handleChangePassword} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-[#8B949E] mb-1">New Password</label>
                  <div className="relative">
                    <FiLock className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B949E] w-4 h-4" />
                    <input
                      type="password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="w-full pl-10 pr-4 py-2.5 bg-[#0D1117] border border-[#30363D] rounded-lg text-white placeholder-[#8B949E] focus:outline-none focus:ring-2 focus:ring-[#FF1493] focus:border-transparent"
                      placeholder="Enter new password"
                      autoComplete="new-password"
                      required
                      minLength={6}
                      autoFocus
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-[#8B949E] mb-1">Confirm Password</label>
                  <div className="relative">
                    <FiLock className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B949E] w-4 h-4" />
                    <input
                      type="password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      className="w-full pl-10 pr-4 py-2.5 bg-[#0D1117] border border-[#30363D] rounded-lg text-white placeholder-[#8B949E] focus:outline-none focus:ring-2 focus:ring-[#FF1493] focus:border-transparent"
                      placeholder="Confirm new password"
                      autoComplete="new-password"
                      required
                      minLength={6}
                    />
                  </div>
                </div>

                {error && (
                  <div className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full py-2.5 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ background: 'linear-gradient(135deg, #FF1493, #FF8C00)' }}
                >
                  {isLoading ? 'Changing...' : 'Change Password'}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
