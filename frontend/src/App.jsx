import React from 'react';
import { AuthProvider, LoginButton, useAuth } from './AuthContext';
import Gallery from './Gallery';

const Main = () => {
  const { user } = useAuth();
  if (!user) {
    return <LoginButton />;
  }
  return <Gallery />;
};

function App() {
  return (
    <AuthProvider>
      <Main />
    </AuthProvider>
  );
}

export default App;
