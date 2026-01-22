import React from 'react';
import Dashboard from './components/Dashboard';
import { AuthProvider } from './components/AuthProvider';

function App() {
  return (
    <AuthProvider>
      <div className="App">
        <Dashboard />
      </div>
    </AuthProvider>
  );
}

export default App;