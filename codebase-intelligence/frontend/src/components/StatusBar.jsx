import React from 'react';
import useStore from '../store/useStore';

const StatusBar = ({ lastResponse }) => {
  return (
    <div className="fixed bottom-0 right-0 p-2 text-[10px] text-slate-600 bg-slate-950/80 backdrop-blur pointer-events-none">
      {lastResponse ? (
        <span className="space-x-4">
          <span>MODE: {lastResponse.mode.toUpperCase()}</span>
          <span>LATENCY: {lastResponse.latency_ms}MS</span>
        </span>
      ) : (
        <span>SYSTEM READY</span>
      )}
    </div>
  );
};

export default StatusBar;
