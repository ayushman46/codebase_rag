import React, { useEffect, useRef } from 'react';
import Prism from 'prismjs';
import { GitPullRequest } from 'lucide-react';
import 'prismjs/themes/prism-tomorrow.css';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-go';
import 'prismjs/components/prism-rust';
import 'prismjs/components/prism-sql';

const CodeBlock = ({ code, language, file, startLine, endLine, retrievalReasons = [], onPushToBranch }) => {
  const codeRef = useRef(null);
  const prismLanguage = ({ py: 'python', rb: 'ruby', rs: 'rust', sh: 'bash', yml: 'yaml' }[language] || language || 'javascript');

  useEffect(() => {
    if (codeRef.current) Prism.highlightElement(codeRef.current);
  }, [code, prismLanguage]);

  return (
    <div className="my-3 rounded-[20px] overflow-hidden bg-deep-charcoal border border-charcoal text-pure-white">
      <div className="bg-[#242424] px-4 py-3 text-caption font-medium text-stone flex justify-between items-center border-b border-charcoal uppercase tracking-widest">
        <span>{file} {startLine ? `: L${startLine}${endLine && endLine !== startLine ? `-L${endLine}` : ''}` : ''}</span>
        <div className="flex items-center gap-3">
          {onPushToBranch && file && (
            <button
              type="button"
              onClick={() => onPushToBranch({ file, code, language })}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-ember-orange/20 hover:bg-ember-orange text-ember-orange hover:text-pure-white text-[11px] font-semibold normal-case tracking-normal transition-all"
              title="Review & Push to GitHub in a new branch"
            >
              <GitPullRequest className="w-3.5 h-3.5" />
              <span>Review & Push PR</span>
            </button>
          )}
          <span>{language}</span>
        </div>
      </div>
      {retrievalReasons.length > 0 && (
        <p className="border-b border-charcoal bg-[#242424] px-4 pb-3 text-xs normal-case tracking-normal text-stone">
          Why this file: {retrievalReasons.join('; ')}
        </p>
      )}
      <pre className="p-5 text-sm overflow-x-auto m-0 !bg-transparent font-mono leading-relaxed">
        <code ref={codeRef} className={`language-${prismLanguage}`}>
          {code}
        </code>
      </pre>
    </div>
  );
};

export default React.memo(CodeBlock);
