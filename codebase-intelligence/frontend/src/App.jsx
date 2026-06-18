import React from 'react';
import RepoList from './components/RepoList';
import ChatWindow from './components/ChatWindow';
import RepoInput from './components/RepoInput';

function App() {
  return (
    <div className="flex h-screen bg-slate-950 text-slate-200 overflow-hidden">
      <RepoList />
      
      <main className="flex-1 flex flex-col h-full overflow-hidden">
        <header className="p-6 border-b border-slate-900 bg-slate-950/80 backdrop-blur-md z-10">
          <div className="max-w-4xl mx-auto flex justify-between items-center">
            <div>
              <h1 className="text-2xl font-black text-white tracking-tighter">
                CODEBASE <span className="text-blue-500">INTELLIGENCE</span>
              </h1>
              <p className="text-xs text-slate-500 font-mono mt-1">PRODUCTION-GRADE RAG ENGINE</p>
            </div>
          </div>
        </header>
        
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="max-w-4xl w-full mx-auto pt-8 px-6">
            <RepoInput />
          </div>
          <ChatWindow />
        </div>
      </main>
    </div>
  );
}

export default App;
