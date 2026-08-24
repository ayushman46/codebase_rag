import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, ArrowLeft, SearchCode } from 'lucide-react';
import useStore from '../store/useStore';
import MessageBubble from './MessageBubble';

const ChatWindow = ({ onClose }) => {
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
    <div className="flex h-[calc(100dvh-7rem)] min-h-[34rem] flex-1 flex-col overflow-hidden rounded-[24px] border border-sand bg-pure-white sm:h-[calc(100dvh-8rem)]">
      <div className="flex items-center justify-between gap-5 border-b border-sand bg-pure-white px-5 py-4 sm:px-7 sm:py-5">
        <div className="flex min-w-0 items-center gap-3">
          <button 
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate transition hover:bg-warm-canvas md:hidden"
            aria-label="Close chat"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="min-w-0">
            <h2 className="truncate text-body font-semibold leading-none text-ink-black">
              {selectedRepo}
            </h2>
            <p className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-warm-gray">Active session</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-4">
          <span className="hidden text-caption font-semibold uppercase tracking-wider text-burnt-rust sm:inline">Agent ready</span>
          <button onClick={onClose} className="hidden text-sm font-semibold text-ember-orange transition-colors hover:text-burnt-rust md:inline">Close chat</button>
        </div>
      </div>
      
      <div className="flex-1 space-y-6 overflow-y-auto bg-pure-white px-5 py-7 sm:px-10 sm:py-10">
        {messages.length === 0 && (
          <div className="mx-auto flex h-full max-w-xl flex-col items-center justify-center space-y-4 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full border border-sand bg-warm-canvas text-ember-orange">
              <SearchCode className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-ink-black">Ready to analyze</h3>
              <p className="mt-2 text-sm leading-relaxed text-pewter sm:text-base">
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

      <div className="border-t border-sand bg-warm-canvas/50 px-4 py-4 sm:px-7 sm:py-5">
        <form onSubmit={handleSubmit} className="relative mx-auto flex w-full max-w-5xl items-center">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this codebase..."
            className="h-16 w-full rounded-2xl border border-sand bg-pure-white pl-5 pr-18 text-base text-ink-black shadow-sm outline-none transition focus:border-stone focus:ring-2 focus:ring-peach-blush/40 placeholder:text-stone sm:pl-6"
            disabled={isQuerying}
          />
          <button
            type="submit"
            disabled={isQuerying || !input.trim()}
            className="absolute right-2 flex h-12 w-12 items-center justify-center rounded-xl bg-ember-orange text-pure-white transition-colors hover:bg-burnt-rust disabled:opacity-50"
            aria-label="Send question"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
};

export default ChatWindow;
