import React, { useState } from 'react';
import { motion } from 'framer-motion';
import CodeBlock from './CodeBlock';
import ToolCallTrace from './ToolCallTrace';

const MessageBubble = ({ message }) => {
  const isAssistant = message.role === 'assistant';
  const [showCitations, setShowCitations] = useState(false);

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex ${isAssistant ? 'justify-start' : 'justify-end'} mb-6`}
    >
      <div className={`max-w-[85%] ${isAssistant ? 'bg-slate-800' : 'bg-blue-600'} rounded-2xl p-5 shadow-lg border ${isAssistant ? 'border-slate-700' : 'border-blue-500'}`}>
        {isAssistant && message.mode && (
          <div className="flex items-center space-x-2 mb-2">
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider ${
              message.mode === 'rag' ? 'bg-purple-600 text-white' : 
              message.mode === 'full_context' ? 'bg-orange-600 text-white' : 'bg-green-600 text-white'
            }`}>
              {message.mode}
            </span>
          </div>
        )}
        
        <div className="text-slate-100 leading-relaxed whitespace-pre-wrap">
          {message.content}
        </div>

        {isAssistant && message.citations && message.citations.length > 0 && (
          <div className="mt-4 pt-4 border-t border-slate-700">
            <button 
              onClick={() => setShowCitations(!showCitations)}
              className="text-xs text-slate-400 hover:text-slate-200 flex items-center space-x-1"
            >
              <span>{showCitations ? 'Hide Citations' : `View ${message.citations.length} Citations`}</span>
              <span className="text-[10px]">{showCitations ? '▲' : '▼'}</span>
            </button>
            
            {showCitations && (
              <div className="mt-3 space-y-4">
                {message.citations.map((cite, idx) => (
                  <CodeBlock 
                    key={idx}
                    code={cite.snippet} 
                    language={cite.file.split('.').pop()} 
                    file={cite.file}
                    startLine={cite.start_line}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {isAssistant && <ToolCallTrace toolCalls={message.tool_calls} />}
      </div>
    </motion.div>
  );
};

export default MessageBubble;
