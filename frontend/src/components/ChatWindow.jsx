import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, ArrowLeft } from 'lucide-react';
import useStore from '../store/useStore';
import MessageBubble from './MessageBubble';

const firstName = (user) => {
  const name = user?.user_metadata?.full_name || user?.user_metadata?.name || user?.email?.split('@')[0] || '';
  return name.trim().split(/\s+/)[0];
};

const greeting = () => {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
};

const ChatWindow = ({ onClose }) => {
  const { selectedRepo, user, messages, askQuestion, isQuerying, isHistoryLoading } = useStore();
  const [input, setInput] = useState('');
  const bottomRef = useRef(null);
  const isEmpty = messages.length === 0 && !isQuerying && !isHistoryLoading;
  const name = firstName(user);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isQuerying]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || isQuerying || isHistoryLoading) return;
    askQuestion(input);
    setInput('');
  };

  const composer = (centered = false) => (
    <form onSubmit={handleSubmit} className={`relative mx-auto flex w-full items-center rounded-full border border-sand bg-pure-white p-2 shadow-lg shadow-charcoal/5 ${centered ? 'max-w-3xl' : 'max-w-5xl'}`}>
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="Ask about this codebase"
        className="h-14 w-full bg-transparent pl-5 pr-16 text-base text-ink-black outline-none placeholder:text-warm-gray sm:pl-6"
        disabled={isQuerying || isHistoryLoading}
      />
      <button
        type="submit"
        disabled={isQuerying || isHistoryLoading || !input.trim()}
        className="absolute right-2 flex h-12 w-12 items-center justify-center rounded-full bg-ember-orange text-pure-white transition-colors hover:bg-burnt-rust disabled:opacity-50"
        aria-label="Send question"
      >
        <Send className="h-4 w-4" aria-hidden="true" />
      </button>
    </form>
  );

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
          </div>
        </div>
        <button onClick={onClose} className="hidden text-sm font-semibold text-ember-orange transition-colors hover:text-burnt-rust md:inline">Close chat</button>
      </div>
      
      <div className="flex-1 space-y-6 overflow-y-auto bg-pure-white px-5 py-7 sm:px-10 sm:py-10">
        {isHistoryLoading && (
          <div className="mx-auto flex h-full max-w-xl items-center justify-center gap-3 text-sm text-pewter">
            <Loader2 className="h-4 w-4 animate-spin text-ember-orange" aria-hidden="true" />
            Loading conversation
          </div>
        )}
        {isEmpty && (
          <div className="mx-auto flex h-full w-full max-w-4xl flex-col items-center justify-center text-center">
            <p className="text-lg text-pewter sm:text-xl">{greeting()}{name ? `, ${name}` : ''}.</p>
            <h3 className="heading-lg mt-3 text-3xl text-ink-black sm:text-4xl">What’s on your mind today?</h3>
            <div className="mt-10 w-full">{composer(true)}</div>
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

      {!isEmpty && !isHistoryLoading && (
        <div className="border-t border-sand bg-warm-canvas/50 px-4 py-4 sm:px-7 sm:py-5">{composer()}</div>
      )}
    </div>
  );
};

export default ChatWindow;
