import React, { useState, useEffect } from 'react';
import {
  apiLogin,
  apiRegister,
  apiForgotPassword,
  apiResetPassword,
  setAuthToken,
  setStoredUser,
  formatError,
} from '../api';
import {
  ShieldCheck,
  UserCheck,
  Lock,
  Mail,
  User,
  AlertCircle,
  ArrowRight,
  Sparkles,
  Eye,
  EyeOff,
  CheckCircle,
  HelpCircle,
  KeyRound,
} from 'lucide-react';

export default function LoginPage({ onLoginSuccess, initialError = '' }) {
  const [activeTab, setActiveTab] = useState('login'); // 'login' | 'register' | 'forgot' | 'reset'
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  // Register fields
  const [regUsername, setRegUsername] = useState('');
  const [regEmail, setRegEmail] = useState('');
  const [regDisplayName, setRegDisplayName] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regConfirmPassword, setRegConfirmPassword] = useState('');

  // Reset fields
  const [resetToken, setResetToken] = useState('');
  const [resetNewPassword, setResetNewPassword] = useState('');
  const [resetConfirmPassword, setResetConfirmPassword] = useState('');

  // State & Feedback
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const [successMsg, setSuccessMsg] = useState('');
  const [countdown, setCountdown] = useState(0);

  // Branding & Demo mode
  const [branding, setBranding] = useState(() => {
    try {
      const cached = localStorage.getItem('app_branding');
      return cached ? JSON.parse(cached) : null;
    } catch {
      return null;
    }
  });
  const [demoMode, setDemoMode] = useState(false);
  const [demoCreds, setDemoCreds] = useState(null);

  // Check query params for reset token on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (token) {
      setResetToken(token);
      setActiveTab('reset');
    }
  }, []);

  useEffect(() => {
    fetch('/api/config')
      .then((res) => res.json())
      .then((cfg) => {
        if (cfg) {
          if (cfg.branding) {
            setBranding(cfg.branding);
            localStorage.setItem('app_branding', JSON.stringify(cfg.branding));
            if (cfg.branding.company_name) {
              document.title = `${cfg.branding.company_name} Assistant`;
            }
          }
          if (cfg.demo_mode) {
            setDemoMode(true);
            setDemoCreds({
              adminEmail: cfg.demo_admin_email || '',
              adminPassword: cfg.demo_admin_password || '',
              userEmail: cfg.demo_user_email || '',
              userPassword: cfg.demo_user_password || '',
            });
          }
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (initialError) {
      setError(initialError);
    }
  }, [initialError]);

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          setError('');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [countdown]);

  const handleLoginSubmit = async (e) => {
    e.preventDefault();
    if (countdown > 0) return;
    setError('');
    setSuccessMsg('');

    const cleanId = identifier.trim();
    if (!cleanId) {
      setError('Please enter your email or username');
      return;
    }

    setLoading(true);
    try {
      const data = await apiLogin(cleanId, password);
      setAuthToken(data.access_token);
      setStoredUser(data.user);
      onLoginSuccess(data.user);
    } catch (err) {
      const formatted = formatError(err);
      if (formatted.toLowerCase().includes('too many attempts') || formatted.toLowerCase().includes('rate limit')) {
        const match = formatted.match(/(\d+)\s*seconds?/i);
        const sec = match ? parseInt(match[1], 10) : 60;
        setCountdown(sec);
        setError(`Too many attempts. Try again in ${sec} seconds`);
      } else {
        setError(formatted);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleRegisterSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMsg('');

    const cleanUsername = regUsername.trim();
    const cleanEmail = regEmail.trim();

    if (!/^[a-zA-Z0-9_.]+$/.test(cleanUsername) || cleanUsername.length < 3 || cleanUsername.length > 30) {
      setError('Username must be 3-30 characters (letters, numbers, underscore, dot)');
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      setError('Please enter a valid email address');
      return;
    }
    if (regPassword.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    if (regPassword !== regConfirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setLoading(true);
    try {
      const data = await apiRegister(
        cleanUsername,
        cleanEmail,
        regPassword,
        regDisplayName.trim() || cleanUsername
      );
      setAuthToken(data.access_token);
      setStoredUser(data.user);
      onLoginSuccess(data.user);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setLoading(false);
    }
  };

  const handleForgotSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMsg('');

    const cleanId = identifier.trim();
    if (!cleanId) {
      setError('Enter your registered email or username');
      return;
    }

    setLoading(true);
    try {
      const res = await apiForgotPassword(cleanId);
      setSuccessMsg(
        res.detail ||
          'If an account exists, password reset instructions have been dispatched. If email delivery is not configured, your administrator has been notified to approve your request.'
      );
    } catch (err) {
      setError(formatError(err));
    } finally {
      setLoading(false);
    }
  };

  const handleResetSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMsg('');

    if (resetNewPassword.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    if (resetNewPassword !== resetConfirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setLoading(true);
    try {
      await apiResetPassword(resetToken.trim(), resetNewPassword);
      setSuccessMsg('Your password has been reset successfully! You can now sign in.');
      setTimeout(() => {
        setActiveTab('login');
        setResetToken('');
        // Clean URL parameter
        window.history.replaceState({}, document.title, window.location.pathname);
      }, 2000);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setLoading(false);
    }
  };

  const fillCredentials = (demoEmail, demoPass) => {
    setIdentifier(demoEmail);
    setPassword(demoPass);
    setError('');
  };

  const companyName = branding?.company_name || 'Enterprise Assistant';
  const tagline = branding?.tagline || 'Enterprise RAG Intelligence & Multimodal Assistant';
  const logoUrl = branding?.logo_url;
  const accentColor = branding?.accent_color || '#10b981';

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-gray-50 via-gray-100 to-emerald-50/40 dark:from-zinc-950 dark:via-zinc-900 dark:to-zinc-950">
      <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-2xl shadow-xl border border-gray-200 dark:border-zinc-800 p-8 animate-in fade-in zoom-in-95 duration-200">
        {/* Brand Header */}
        <div className="text-center mb-6">
          <div className="w-14 h-14 mx-auto mb-3.5 flex items-center justify-center">
            {logoUrl ? (
              <img
                src={logoUrl}
                alt="Logo"
                className="w-14 h-14 rounded-2xl object-contain bg-gray-50 dark:bg-zinc-800 p-1 shadow-md shadow-emerald-500/10"
              />
            ) : (
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center shadow-lg text-white"
                style={{ backgroundColor: accentColor }}
              >
                <Sparkles className="w-7 h-7" />
              </div>
            )}
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
            {companyName}
          </h1>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-xs mx-auto">
            {tagline}
          </p>
        </div>

        {/* Demo Quick Logins (only when demo_mode=true) */}
        {demoMode && activeTab === 'login' && (
          <div className="mb-5 p-3 bg-gray-50 dark:bg-zinc-800/60 rounded-xl border border-gray-200/80 dark:border-zinc-700/60">
            <span className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider block mb-2">
              Quick Demo Accounts
            </span>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => fillCredentials(demoCreds?.adminEmail || '', demoCreds?.adminPassword || '')}
                className="flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg text-xs font-medium bg-emerald-100 dark:bg-emerald-950/50 text-emerald-800 dark:text-emerald-300 hover:bg-emerald-200 transition"
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                Admin
              </button>
              <button
                type="button"
                onClick={() => fillCredentials(demoCreds?.userEmail || '', demoCreds?.userPassword || '')}
                className="flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg text-xs font-medium bg-blue-100 dark:bg-blue-950/50 text-blue-800 dark:text-blue-300 hover:bg-blue-200 transition"
              >
                <UserCheck className="w-3.5 h-3.5" />
                Regular User
              </button>
            </div>
          </div>
        )}

        {/* Tabs: Sign In / Create Account (hidden on forgot/reset view) */}
        {activeTab !== 'forgot' && activeTab !== 'reset' && (
          <div className="grid grid-cols-2 gap-1 p-1 bg-gray-100 dark:bg-zinc-800 rounded-xl mb-5 text-xs font-semibold">
            <button
              type="button"
              onClick={() => {
                setActiveTab('login');
                setError('');
                setSuccessMsg('');
              }}
              className={`py-2 rounded-lg transition ${
                activeTab === 'login'
                  ? 'bg-white dark:bg-zinc-900 text-gray-900 dark:text-white shadow-xs'
                  : 'text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200'
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTab('register');
                setError('');
                setSuccessMsg('');
              }}
              className={`py-2 rounded-lg transition ${
                activeTab === 'register'
                  ? 'bg-white dark:bg-zinc-900 text-gray-900 dark:text-white shadow-xs'
                  : 'text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200'
              }`}
            >
              Create Account
            </button>
          </div>
        )}

        {/* Alerts */}
        {error && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900/50 flex items-start gap-2.5 text-red-600 dark:text-red-400 text-xs">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>{countdown > 0 ? `Too many attempts. Try again in ${countdown} seconds` : error}</span>
          </div>
        )}
        {successMsg && (
          <div className="mb-4 p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-900/50 flex items-start gap-2.5 text-emerald-700 dark:text-emerald-300 text-xs">
            <CheckCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}

        {/* VIEW 1: SIGN IN */}
        {activeTab === 'login' && (
          <form onSubmit={handleLoginSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
                Email or Username
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 absolute left-3.5 top-3 text-gray-400" />
                <input
                  type="text"
                  required
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder="name@company.com or username"
                  className="w-full pl-10 pr-4 py-2.5 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase">
                  Password
                </label>
                <button
                  type="button"
                  onClick={() => {
                    setActiveTab('forgot');
                    setError('');
                    setSuccessMsg('');
                  }}
                  className="text-xs text-emerald-600 dark:text-emerald-400 hover:underline font-medium"
                >
                  Forgot password?
                </button>
              </div>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3.5 top-3 text-gray-400" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-10 pr-10 py-2.5 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading || countdown > 0}
              className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? (
                <span className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
              ) : countdown > 0 ? (
                <span>Disabled ({countdown}s)</span>
              ) : (
                <>
                  Sign In
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
        )}

        {/* VIEW 2: CREATE ACCOUNT */}
        {activeTab === 'register' && (
          <form onSubmit={handleRegisterSubmit} className="space-y-3.5">
            <div>
              <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
                Username
              </label>
              <div className="relative">
                <User className="w-4 h-4 absolute left-3.5 top-3 text-gray-400" />
                <input
                  type="text"
                  required
                  minLength={3}
                  maxLength={30}
                  pattern="^[a-zA-Z0-9_.]+$"
                  value={regUsername}
                  onChange={(e) => setRegUsername(e.target.value)}
                  placeholder="john_doe"
                  className="w-full pl-10 pr-4 py-2 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                />
              </div>
              <span className="text-[10px] text-gray-400 mt-0.5 block">
                3-30 chars (letters, numbers, _ .)
              </span>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
                Email Address
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 absolute left-3.5 top-3 text-gray-400" />
                <input
                  type="email"
                  required
                  value={regEmail}
                  onChange={(e) => setRegEmail(e.target.value)}
                  placeholder="name@company.com"
                  className="w-full pl-10 pr-4 py-2 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
                Display Name (Optional)
              </label>
              <input
                type="text"
                value={regDisplayName}
                onChange={(e) => setRegDisplayName(e.target.value)}
                placeholder="John Doe"
                className="w-full px-3.5 py-2 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-[11px] font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
                  Password
                </label>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={regPassword}
                  onChange={(e) => setRegPassword(e.target.value)}
                  placeholder="Min 8 chars"
                  className="w-full px-3 py-2 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
                  Confirm
                </label>
                <input
                  type="password"
                  required
                  value={regConfirmPassword}
                  onChange={(e) => setRegConfirmPassword(e.target.value)}
                  placeholder="Repeat"
                  className="w-full px-3 py-2 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full mt-2 py-2.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25 transition disabled:opacity-50"
            >
              {loading ? (
                <span className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
              ) : (
                <>
                  Create Account
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
        )}

        {/* VIEW 3: FORGOT PASSWORD */}
        {activeTab === 'forgot' && (
          <form onSubmit={handleForgotSubmit} className="space-y-4">
            <div className="text-left">
              <h2 className="text-sm font-bold text-gray-900 dark:text-white">Reset your password</h2>
              <p className="text-xs text-gray-500 dark:text-zinc-400 mt-1">
                Enter your email address or username and we will initiate the password reset process.
              </p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
                Email or Username
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 absolute left-3.5 top-3 text-gray-400" />
                <input
                  type="text"
                  required
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder="name@company.com or username"
                  className="w-full pl-10 pr-4 py-2.5 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25 transition disabled:opacity-50"
            >
              {loading ? (
                <span className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
              ) : (
                'Request Password Reset'
              )}
            </button>

            <button
              type="button"
              onClick={() => {
                setActiveTab('login');
                setError('');
                setSuccessMsg('');
              }}
              className="w-full text-center text-xs text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200"
            >
              &larr; Back to Sign In
            </button>
          </form>
        )}

        {/* VIEW 4: RESET PASSWORD WITH TOKEN */}
        {activeTab === 'reset' && (
          <form onSubmit={handleResetSubmit} className="space-y-4">
            <div className="text-left">
              <h2 className="text-sm font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-emerald-500" />
                Set New Password
              </h2>
              <p className="text-xs text-gray-500 dark:text-zinc-400 mt-1">
                Enter your new password below.
              </p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
                New Password
              </label>
              <input
                type="password"
                required
                minLength={8}
                value={resetNewPassword}
                onChange={(e) => setResetNewPassword(e.target.value)}
                placeholder="Minimum 8 characters"
                className="w-full px-3.5 py-2.5 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
                Confirm New Password
              </label>
              <input
                type="password"
                required
                value={resetConfirmPassword}
                onChange={(e) => setResetConfirmPassword(e.target.value)}
                placeholder="Repeat password"
                className="w-full px-3.5 py-2.5 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25 transition disabled:opacity-50"
            >
              {loading ? (
                <span className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
              ) : (
                'Set New Password and Sign In'
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
