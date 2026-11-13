import React, { useState, useEffect } from 'react';
import { apiLogin, apiRegister, setAuthToken, setStoredUser } from '../api';
import { ShieldCheck, UserCheck, Lock, Mail, AlertCircle, ArrowRight, Sparkles } from 'lucide-react';

export default function LoginPage({ onLoginSuccess, initialError = '' }) {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const [countdown, setCountdown] = useState(0);
  const [demoMode, setDemoMode] = useState(false);

  useEffect(() => {
    fetch('/api/config')
      .then((res) => res.json())
      .then((cfg) => {
        if (cfg && cfg.demo_mode) {
          setDemoMode(true);
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

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (countdown > 0) return;
    setError('');
    setLoading(true);

    try {
      let data;
      if (isRegister) {
        data = await apiRegister(email, password);
      } else {
        data = await apiLogin(email, password);
      }
      setAuthToken(data.access_token);
      setStoredUser(data.user);
      onLoginSuccess(data.user);
    } catch (err) {
      const msg = err.message || '';
      if (msg.toLowerCase().includes('too many attempts') || msg.toLowerCase().includes('rate limit')) {
        const match = msg.match(/(\d+)\s*seconds?/i);
        const sec = match ? parseInt(match[1], 10) : 60;
        setCountdown(sec);
        setError(`Too many attempts. Try again in ${sec} seconds`);
      } else if (msg.toLowerCase().includes('invalid email or password') || msg.toLowerCase().includes('credentials') || msg.includes('401')) {
        setError('Invalid email or password');
      } else if (msg.toLowerCase().includes('failed to fetch') || msg.toLowerCase().includes('network') || msg.toLowerCase().includes('unreachable') || msg.toLowerCase().includes('server unreachable')) {
        setError('Server unreachable');
      } else {
        setError(msg || 'Authentication failed');
      }
    } finally {
      setLoading(false);
    }
  };

  const fillCredentials = (demoEmail, demoPass) => {
    setEmail(demoEmail);
    setPassword(demoPass);
    setError('');
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-gray-50 via-gray-100 to-emerald-50 dark:from-zinc-950 dark:via-zinc-900 dark:to-zinc-950">
      <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-2xl shadow-xl border border-gray-200 dark:border-zinc-800 p-8">
        {/* Brand Header */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 mx-auto mb-4 bg-emerald-600 rounded-2xl flex items-center justify-center shadow-lg shadow-emerald-600/20 text-white">
            <Sparkles className="w-7 h-7" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
            ABC Technologies Assistant
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Enterprise RAG Intelligence & Multimodal Assistant
          </p>
        </div>

        {/* Demo Quick Logins (only shown when DEMO_MODE=true) */}
        {demoMode && (
          <div className="mb-6 p-3 bg-gray-50 dark:bg-zinc-800/60 rounded-xl border border-gray-200/80 dark:border-zinc-700/60">
            <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider block mb-2">
              Quick Demo Accounts
            </span>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => fillCredentials('admin@abctechnologies.com', 'Admin@123')}
                className="flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg text-xs font-medium bg-emerald-100 dark:bg-emerald-950/50 text-emerald-800 dark:text-emerald-300 hover:bg-emerald-200 transition"
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                Admin (Full Access)
              </button>
              <button
                type="button"
                onClick={() => fillCredentials('user@abctechnologies.com', 'User@123')}
                className="flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg text-xs font-medium bg-blue-100 dark:bg-blue-950/50 text-blue-800 dark:text-blue-300 hover:bg-blue-200 transition"
              >
                <UserCheck className="w-3.5 h-3.5" />
                Regular User
              </button>
            </div>
          </div>
        )}

        {/* Error Notification */}
        {error && (
          <div className="mb-5 p-3 rounded-xl bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900/50 flex items-start gap-2.5 text-red-600 dark:text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>{countdown > 0 ? `Too many attempts. Try again in ${countdown} seconds` : error}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
              Email Address
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 absolute left-3.5 top-3 text-gray-400" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@abctechnologies.com"
                className="w-full pl-10 pr-4 py-2.5 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase mb-1">
              Password
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 absolute left-3.5 top-3 text-gray-400" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-10 pr-4 py-2.5 bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || countdown > 0}
            className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-sm font-semibold flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <span className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
            ) : countdown > 0 ? (
              <span>Disabled ({countdown}s)</span>
            ) : (
              <>
                {isRegister ? 'Create Account' : 'Sign In'}
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        {/* Toggle Mode */}
        <div className="mt-6 text-center text-xs text-gray-500 dark:text-gray-400">
          {isRegister ? 'Already registered?' : "Don't have an account?"}{' '}
          <button
            type="button"
            onClick={() => {
              setIsRegister(!isRegister);
              setError('');
            }}
            className="text-emerald-600 dark:text-emerald-400 font-semibold hover:underline ml-1"
          >
            {isRegister ? 'Sign In here' : 'Register as new user'}
          </button>
        </div>
      </div>
    </div>
  );
}
