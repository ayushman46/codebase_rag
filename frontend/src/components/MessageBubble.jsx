import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import CodeBlock from './CodeBlock';
import ToolCallTrace from './ToolCallTrace';

const MessageBubble = ({ message }) => {
  const [showCitations, setShowCitations] = useState(false);
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-full sm:max-w-[85%] ${isUser ? 'order-1' : 'order-2'}`}>
        <div className={`p-5 rounded-[24px] ${
          isUser 
            ? 'bg-ember-orange text-pure-white rounded-br-none' 
            : 'bg-warm-canvas border border-sand text-ink-black rounded-bl-none'
        }`}>
          {isUser ? (
            <div className="whitespace-pre-wrap text-body leading-body">{message.content}</div>
          ) : (
            <ReactMarkdown
              skipHtml
              components={{
                h2: ({ children }) => <h2 className="mt-7 text-lg font-semibold tracking-tight first:mt-0">{children}</h2>,
                h3: ({ children }) => <h3 className="mt-6 text-base font-semibold first:mt-0">{children}</h3>,
                p: ({ children }) => <p className="mt-3 leading-relaxed first:mt-0">{children}</p>,
                ul: ({ children }) => <ul className="mt-3 list-disc space-y-2 pl-5 marker:text-ember-orange">{children}</ul>,
                ol: ({ children }) => <ol className="mt-3 list-decimal space-y-2 pl-5 marker:font-semibold marker:text-ember-orange">{children}</ol>,
                li: ({ children }) => <li className="pl-1 leading-relaxed">{children}</li>,
                strong: ({ children }) => <strong className="font-semibold text-ink-black">{children}</strong>,
                code: ({ children }) => <code className="rounded bg-pure-white px-1.5 py-0.5 font-mono text-[0.9em] text-charcoal">{children}</code>,
              }}
            >
              {message.content}
            </ReactMarkdown>
          )}
        </div>
        
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-3 pl-2">
            <button 
              onClick={() => setShowCitations(!showCitations)}
              className="text-caption font-medium text-warm-gray hover:text-charcoal flex items-center tracking-caption uppercase"
            >
              {showCitations ? '− Hide Citations' : `+ View ${message.citations.length} Citations`}
            </button>
            {showCitations && (
              <div className="mt-3 space-y-3">
                {message.citations.map((cit, idx) => (
                  <CodeBlock 
                    key={idx} 
                    code={cit.content} 
                    language={cit.language} 
                    file={cit.file_path}
                    startLine={cit.start_line}
                  />
                ))}
              </div>
            )}
          </div>
        )}
        
        {!isUser && message.tool_calls && <ToolCallTrace toolCalls={message.tool_calls} />}
        
      </div>
    </div>
  );
};

export default MessageBubble;
