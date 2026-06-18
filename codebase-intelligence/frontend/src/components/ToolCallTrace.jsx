import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const ToolCallTrace = ({ toolCalls }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!toolCalls || toolCalls.length === 0) return null;

  return (
    <div className="mt-4 border border-blue-900/30 rounded-lg bg-blue-900/10 overflow-hidden">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-4 py-2 text-left text-sm font-medium text-blue-400 flex justify-between items-center hover:bg-blue-900/20 transition-colors"
      >
        <span>Agent Tool History ({toolCalls.length})</span>
        <span>{isOpen ? '−' : '+'}</span>
      </button>
      
      <AnimatePresence>
        {isOpen && (
          <motion.div 
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="p-4 space-y-3 border-t border-blue-900/30 bg-slate-900/50">
              {toolCalls.map((call, idx) => (
                <div key={idx} className="text-xs space-y-1">
                  <div className="flex items-center space-x-2">
                    <span className="px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400 border border-blue-500/30 font-mono">
                      {call.tool}
                    </span>
                    <span className="text-slate-500">→</span>
                    <code className="text-slate-400">{JSON.stringify(call.input)}</code>
                  </div>
                  <div className="pl-4 border-l border-slate-700 py-1 text-slate-300 italic">
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
