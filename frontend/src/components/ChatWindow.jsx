import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, ArrowLeft, ChevronDown, GitPullRequest } from 'lucide-react';
import useStore from '../store/useStore';
import MessageBubble from './MessageBubble';
import DiffReviewModal from './DiffReviewModal';

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
  const { selectedRepo, user, messages, askQuestion, isQuerying, isHistoryLoading, historyError, setSelectedRepo } = useStore();
  const [input, setInput] = useState('');
  const [modelProfile, setModelProfile] = useState('fast');
  const [workflow, setWorkflow] = useState('general');
  const [activeDiff, setActiveDiff] = useState(null);
  const bottomRef = useRef(null);
  const isEmpty = messages.length === 0 && !isQuerying && !isHistoryLoading;
  const name = firstName(user);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isQuerying]);

  useEffect(() => {
    // The code model is deliberately reachable only through the editing
    // workflow. Reset a stale selection when the user returns to normal chat.
    setModelProfile((current) => workflow === 'editing' ? 'code' : (current === 'code' ? 'fast' : current));
  }, [workflow]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || isQuerying || isHistoryLoading) return;
    askQuestion(input, modelProfile, workflow);
    setInput('');
  };

  const composer = (centered = false) => (
    <div className={`mx-auto w-full ${centered ? 'max-w-3xl' : 'max-w-5xl'}`}>
      {workflow !== 'editing' && (
        <button
          type="button"
          onClick={() => setWorkflow('editing')}
          className="mb-3 inline-flex items-center gap-2 rounded-full border border-ember-orange/40 bg-ember-orange/5 px-4 py-2 text-xs font-semibold text-ember-orange transition-colors hover:bg-ember-orange/10"
        >
          <GitPullRequest className="h-3.5 w-3.5" aria-hidden="true" />
          Need a code change? Switch to Code editing and PR
        </button>
      )}
      {workflow === 'editing' && (
        <p className="mb-3 text-xs text-warm-gray" role="status">
          Code editing and PR mode generates an exact patch first. The GitHub review and push action appears after the patch passes validation.
        </p>
      )}
      <form onSubmit={handleSubmit} className="flex w-full flex-wrap items-center gap-1 rounded-3xl border border-sand bg-pure-white p-2 shadow-lg shadow-charcoal/5 sm:flex-nowrap sm:gap-2 sm:rounded-full">
      <div className="min-w-0 basis-full flex-1 sm:basis-auto">
        <input
          type="text"
          aria-label="Ask a question about the selected codebase"
          autoComplete="off"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={workflow === 'editing' ? 'Describe a focused fix for path/to/file' : 'Ask about this codebase'}
          className="h-14 min-w-0 w-full truncate bg-transparent px-3 text-base text-ink-black outline-none placeholder:text-warm-gray sm:pl-5"
          disabled={isQuerying || isHistoryLoading}
        />
      </div>
      <div className="flex min-w-0 max-w-full shrink-0 items-center gap-1 text-warm-gray">
        <div className="relative flex items-center">
          <label className="sr-only" htmlFor="model-profile-select">Answer model</label>
          <select
            id="model-profile-select"
            value={modelProfile}
            onChange={(event) => setModelProfile(event.target.value)}
            disabled={isQuerying || isHistoryLoading}
            className="h-10 min-w-0 max-w-[10.75rem] appearance-none bg-transparent px-2 pr-6 text-xs font-medium text-pewter outline-none transition-colors hover:text-ink-black disabled:opacity-50 sm:max-w-none sm:text-sm"
          >
            {workflow === 'editing' ? (
              <option value="code">Nemotron Super · Code editing</option>
            ) : (
              <>
                <option value="fast">Super 120B · Fast</option>
                <option value="detailed">Ultra 550B · Detailed</option>
              </>
            )}
          </select>
          <ChevronDown className="pointer-events-none absolute right-1 h-3.5 w-3.5" aria-hidden="true" />
        </div>
        <div className="relative flex items-center">
          <label className="sr-only" htmlFor="workflow-select">Answer workflow</label>
          <select
            id="workflow-select"
            value={workflow}
            onChange={(event) => setWorkflow(event.target.value)}
            disabled={isQuerying || isHistoryLoading}
            className="h-10 min-w-0 max-w-[9rem] appearance-none bg-transparent px-2 pr-5 text-xs font-medium text-pewter outline-none transition-colors hover:text-ink-black disabled:opacity-50 sm:max-w-none sm:text-sm"
          >
            <option value="general">Repository question</option>
            <option value="onboarding">New engineer onboarding</option>
            <option value="security">Security review</option>
            <option value="architecture">Architecture interview</option>
            <option value="contributor">Open-source contributor</option>
            <option value="due_diligence">Technical due diligence</option>
            <option value="editing">Code editing and PR</option>
          </select>
          <ChevronDown className="pointer-events-none absolute right-0 h-3.5 w-3.5" aria-hidden="true" />
        </div>
      </div>
      <button
        type="submit"
        disabled={isQuerying || isHistoryLoading || !input.trim()}
        className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-ember-orange text-pure-white transition-colors hover:bg-burnt-rust disabled:opacity-50"
        aria-label="Send question"
      >
        <Send className="h-5 w-5" aria-hidden="true" />
      </button>
      </form>
    </div>
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
          <div className="mx-auto flex h-full max-w-xl items-center justify-center gap-3 text-sm text-pewter" role="status" aria-live="polite">
            <Loader2 className="h-4 w-4 animate-spin text-ember-orange" aria-hidden="true" />
            Loading conversation
          </div>
        )}
        {historyError && !isHistoryLoading && (
          <div className="mx-auto flex max-w-xl items-center justify-between gap-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">
            <span>{historyError}</span>
            <button type="button" className="font-semibold underline" onClick={() => setSelectedRepo(selectedRepo)}>Retry</button>
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
          <MessageBubble
            key={msg.id || `${msg.created_at || 'message'}-${idx}`}
            message={msg}
            onPushToBranch={(diff) => setActiveDiff(diff)}
          />
        ))}
        {isQuerying && (
          <div className="flex items-center space-x-3 text-stone p-4 bg-warm-canvas/30 rounded-xl max-w-xs" role="status" aria-live="polite">
            <Loader2 className="w-4 h-4 animate-spin text-ember-orange" />
            <span className="text-sm font-medium">Agent is analyzing...</span>
          </div>
        )}
        <div ref={bottomRef} />
        {!isQuerying && messages.length > 0 && messages[messages.length - 1].role === 'assistant' && (
          <p className="sr-only" role="status" aria-live="polite">Response ready.</p>
        )}
      </div>

      {!isEmpty && !isHistoryLoading && (
        <div className="border-t border-sand bg-warm-canvas/50 px-4 py-4 sm:px-7 sm:py-5">{composer()}</div>
      )}

      <DiffReviewModal
        isOpen={Boolean(activeDiff)}
        onClose={() => setActiveDiff(null)}
        repoName={selectedRepo}
        filePath={activeDiff?.file || ''}
        suggestedContent={activeDiff?.code || ''}
        editTicket={activeDiff?.editTicket || ''}
        editSuggestion={activeDiff?.editSuggestion || null}
      />
    </div>
  );
};

export default ChatWindow;
