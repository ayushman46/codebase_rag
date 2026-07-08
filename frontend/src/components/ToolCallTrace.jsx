import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const ToolCallTrace = ({ toolCalls }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!toolCalls || toolCalls.length === 0) return null;

  return (
    <div className="mt-3 ml-2 border border-sand rounded-[16px] bg-warm-canvas overflow-hidden">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-4 py-3 text-left text-caption font-medium text-charcoal flex justify-between items-center hover:bg-sand/30 transition-colors uppercase tracking-widest"
      >
        <span>Agent Tool History ({toolCalls.length})</span>
        <span className="text-stone">{isOpen ? '−' : '+'}</span>
      </button>
      
      <AnimatePresence>
        {isOpen && (
          <motion.div 
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="p-5 space-y-4 border-t border-sand bg-pure-white">
              {toolCalls.map((call, idx) => (
                <div key={idx} className="text-sm space-y-2">
                  <div className="flex items-center space-x-2">
                    <span className="px-2 py-1 rounded-[6px] bg-sand text-charcoal font-mono text-xs">
                      {call.tool}
                    </span>
                    <span className="text-stone">→</span>
                    <code className="text-pewter font-mono text-xs break-all bg-warm-canvas px-2 py-1 rounded-[6px]">{JSON.stringify(call.input)}</code>
                  </div>
                  <div className="pl-4 border-l-[1.5px] border-sand py-1 text-warm-gray text-body italic leading-relaxed">
                    {call.result_summary}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ToolCallTrace;
