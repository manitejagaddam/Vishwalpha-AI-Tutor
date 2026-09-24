import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { authApi } from '../api/client';

export default function AuthPage() {
  const { login } = useAuth();
  const [isLogin, setIsLogin] = useState(true);
  
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [classNum, setClassNum] = useState(10);
  
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    
    try {
      if (isLogin) {
        const data = await authApi.login(username, password);
        login(data);
      } else {
        const data = await authApi.register({
          username, email, password, class_num: parseInt(classNum, 10)
        });
        login(data);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-900 text-white p-4">
      <div className="text-center mb-8">
        <h1 className="text-4xl font-bold mb-2">Welcome to VishwAlpha</h1>
        <p className="text-gray-400">Log in or create an account to start learning</p>
      </div>
      
      <div className="bg-gray-800 p-8 rounded-xl shadow-xl w-full max-w-md border border-gray-700">
        <div className="flex mb-6 border-b border-gray-700">
          <button 
            className={`flex-1 pb-2 text-center font-medium ${isLogin ? 'text-indigo-400 border-b-2 border-indigo-500' : 'text-gray-500'}`}
            onClick={() => setIsLogin(true)}
          >
            Login
          </button>
          <button 
            className={`flex-1 pb-2 text-center font-medium ${!isLogin ? 'text-indigo-400 border-b-2 border-indigo-500' : 'text-gray-500'}`}
            onClick={() => setIsLogin(false)}
          >
            Register
          </button>
        </div>
        
        {error && <div className="bg-red-500/20 text-red-300 p-3 rounded mb-4 text-sm">{error}</div>}
        
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Username</label>
            <input 
              type="text" 
              value={username} 
              onChange={e => setUsername(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-indigo-500"
              required 
            />
          </div>
          
          {!isLogin && (
            <div>
              <label className="block text-sm text-gray-400 mb-1">Email</label>
              <input 
                type="email" 
                value={email} 
                onChange={e => setEmail(e.target.value)}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-indigo-500"
                required 
              />
            </div>
          )}
          
          <div>
            <label className="block text-sm text-gray-400 mb-1">Password</label>
            <input 
              type="password" 
              value={password} 
              onChange={e => setPassword(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-indigo-500"
              required 
            />
          </div>
          
          {!isLogin && (
            <div>
              <label className="block text-sm text-gray-400 mb-1">Class</label>
              <select 
                value={classNum} 
                onChange={e => setClassNum(e.target.value)}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-indigo-500"
              >
                {[6, 7, 8, 9, 10, 11, 12].map(c => (
                  <option key={c} value={c}>Class {c}</option>
                ))}
              </select>
            </div>
          )}
          
          <button 
            type="submit" 
            disabled={loading}
            className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 px-4 rounded transition-colors mt-2"
          >
            {loading ? 'Please wait...' : (isLogin ? 'Login' : 'Register')}
          </button>
        </form>
      </div>
    </div>
  );
}
