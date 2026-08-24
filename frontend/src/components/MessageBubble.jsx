import React, { useState } from 'react';
import CodeBlock from './CodeBlock';
import ToolCallTrace from './ToolCallTrace';
import { motion } from 'framer-motion';

const MessageBubble = ({ message }) => {
  const [showCitations, setShowCitations] = useState(false);
  const isUser = message.role === 'user';

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      <div className={`max-w-full sm:max-w-[85%] ${isUser ? 'order-1' : 'order-2'}`}>
        <div className={`p-5 rounded-[24px] ${
          isUser 
            ? 'bg-ember-orange text-pure-white rounded-br-none' 
            : 'bg-warm-canvas border border-sand text-ink-black rounded-bl-none'
        }`}>
          <div className="whitespace-pre-wrap text-body leading-body">
            {message.content}
          </div>
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
        
        {!isUser && message.mode && (
          <div className="mt-2 pl-2 text-[10px] text-stone uppercase font-medium tracking-widest">
            {message.mode} • {message.latency_ms}ms
          </div>
        )}
      </div>
    </motion.div>
  );
};

export default MessageBubble;
