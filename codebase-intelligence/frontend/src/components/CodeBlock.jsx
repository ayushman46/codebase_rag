import React, { useEffect } from 'react';
import Prism from 'prismjs';
import 'prismjs/themes/prism-tomorrow.css';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-go';
import 'prismjs/components/prism-rust';

const CodeBlock = ({ code, language, file, startLine }) => {
  useEffect(() => {
    Prism.highlightAll();
  }, [code]);

  return (
    <div className="my-4 rounded-lg overflow-hidden bg-slate-900 border border-slate-700 shadow-xl">
      <div className="bg-slate-800 px-4 py-2 text-xs text-slate-400 flex justify-between items-center">
        <span>{file} {startLine ? `: L${startLine}` : ''}</span>
        <span className="uppercase">{language}</span>
      </div>
      <pre className="p-4 text-sm overflow-x-auto">
        <code className={`language-${language}`}>
          {code}
        </code>
      </pre>
    </div>
  );
};

export default CodeBlock;
