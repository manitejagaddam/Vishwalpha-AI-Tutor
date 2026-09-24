import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [student, setStudent] = useState(() => {
    const saved = localStorage.getItem('vishwalpha_student');
    return saved ? JSON.parse(saved) : null;
  });

  const login = (data) => {
    setStudent(data);
    localStorage.setItem('vishwalpha_student', JSON.stringify(data));
  };

  const logout = () => {
    setStudent(null);
    localStorage.removeItem('vishwalpha_student');
  };

  return (
    <AuthContext.Provider value={{ student, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
