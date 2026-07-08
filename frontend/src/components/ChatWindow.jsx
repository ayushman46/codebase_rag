import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, ArrowLeft } from 'lucide-react';
import useStore from '../store/useStore';
import MessageBubble from './MessageBubble';

const ChatWindow = () => {
  const { selectedRepo, setSelectedRepo, messages, askQuestion, isQuerying } = useStore();
  const [input, setInput] = useState('');
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isQuerying]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || isQuerying) return;
    askQuestion(input);
    setInput('');
  };

  return (
    <div className="flex flex-col h-full bg-pure-white border border-sand rounded-[24px] overflow-hidden flex-1">
      {/* Chat header */}
      <div className="px-6 py-4 border-b border-sand bg-pure-white flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <button 
            onClick={() => setSelectedRepo(null)}
            className="md:hidden p-1.5 hover:bg-warm-canvas rounded-lg text-slate"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h2 className="font-semibold text-ink-black text-body leading-none">
              {selectedRepo}
            </h2>
            <p className="text-[10px] text-warm-gray mt-1 uppercase tracking-wider font-semibold">Active Session</p>
          </div>
        </div>
        <span className="px-3 py-1 bg-peach-blush text-burnt-rust text-caption font-semibold rounded-badges tracking-caption">
          AGENT STABLE
        </span>
      </div>
      
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-pure-white">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto space-y-4">
            <div className="w-12 h-12 rounded-full bg-warm-canvas border border-sand flex items-center justify-center text-ember-orange">
              ✦
            </div>
            <div>
              <h3 className="font-semibold text-ink-black">Ready to Analyze</h3>
              <p className="text-sm text-pewter mt-1">
                Ask anything about the architecture, endpoint paths, imports, variables, or general flow of this repository.
              </p>
            </div>
          </div>
        )}
        
        {messages.map((msg, idx) => (
          <MessageBubble key={idx} message={msg} />
        ))}
        {isQuerying && (
          <div className="flex items-center space-x-3 text-stone p-4 bg-warm-canvas/30 rounded-xl max-w-xs">
            <Loader2 className="w-4 h-4 animate-spin text-ember-orange" />
            <span className="text-sm font-medium">Agent is analyzing...</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input container */}
      <div className="p-4 border-t border-sand bg-pure-white">
        <form onSubmit={handleSubmit} className="relative flex items-center w-full max-w-4xl mx-auto">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this codebase..."
            className="w-full h-12 pl-5 pr-14 bg-warm-canvas border border-sand rounded-xl text-sm text-ink-black focus:outline-none focus:border-stone placeholder-stone"
            disabled={isQuerying}
          />
          <button
            type="submit"
            disabled={isQuerying || !input.trim()}
            className="absolute right-1.5 w-9 h-9 bg-ember-orange hover:bg-burnt-rust text-pure-white rounded-full flex items-center justify-center transition-colors disabled:opacity-50"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
};

export default ChatWindow;
