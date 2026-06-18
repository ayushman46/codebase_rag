import React, { useState, useRef, useEffect } from 'react';
import useStore from '../store/useStore';
import { queryRepo } from '../api/client';
import MessageBubble from './MessageBubble';

const ChatWindow = () => {
  const { selectedRepo, messages, addMessage, isQuerying, setQuerying } = useStore();
  const [input, setInput] = useState('');
  const [lastResponse, setLastResponse] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isQuerying]);

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input || isQuerying || !selectedRepo) return;

    const userMessage = { role: 'user', content: input };
    addMessage(userMessage);
    setInput('');
    setQuerying(true);

    try {
      const res = await queryRepo(selectedRepo, input);
      const assistantMessage = {
        role: 'assistant',
        content: res.data.answer,
        mode: res.data.mode,
        citations: res.data.citations,
        tool_calls: res.data.tool_calls,
        latency: res.data.latency_ms
      };
      addMessage(assistantMessage);
      setLastResponse(res.data);
    } catch (error) {
      console.error('Query failed', error);
      addMessage({ 
        role: 'assistant', 
        content: 'Sorry, I encountered an error processing your request. Please try again.' 
      });
    } finally {
      setQuerying(false);
    }
  };

  if (!selectedRepo) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-slate-500 bg-slate-950">
        <div className="text-6xl mb-4 text-slate-800">⌨</div>
        <p className="text-lg">Select a repository to start chatting</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-slate-950 relative overflow-hidden">
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.map((msg, idx) => (
          <MessageBubble key={idx} message={msg} />
        ))}
        {isQuerying && (
          <div className="flex justify-start">
            <div className="bg-slate-800 rounded-2xl p-5 border border-slate-700 animate-pulse">
              <div className="flex space-x-2">
                <div className="h-2 w-2 bg-slate-500 rounded-full animate-bounce" />
                <div className="h-2 w-2 bg-slate-500 rounded-full animate-bounce [animation-delay:0.2s]" />
                <div className="h-2 w-2 bg-slate-500 rounded-full animate-bounce [animation-delay:0.4s]" />
              </div>
            </div>
          </div>
        )}
        <div ref={scrollRef} />
      </div>

      <div className="p-6 bg-slate-900/50 border-t border-slate-800">
        <form onSubmit={handleSend} className="max-w-4xl mx-auto flex space-x-4">
          <input 
            type="text" 
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isQuerying}
            placeholder={`Ask about ${selectedRepo}...`}
            className="flex-1 bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-slate-200 focus:outline-none focus:border-blue-500 transition-colors shadow-inner"
          />
          <button 
            type="submit"
            disabled={isQuerying || !input}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-bold p-3 rounded-xl transition-all shadow-lg hover:shadow-blue-500/20 active:scale-95"
          >
            <svg className="w-6 h-6 transform rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </form>
        
        {lastResponse && (
          <div className="mt-3 text-center text-[10px] text-slate-500 uppercase tracking-widest flex justify-center space-x-4">
            <span>Mode: {lastResponse.mode}</span>
            <span>Latency: {lastResponse.latency_ms}ms</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatWindow;
