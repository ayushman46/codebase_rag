import React, { useState, useEffect, useRef } from 'react';
import { GitPullRequest, GitBranch, Check, ExternalLink, AlertCircle, Loader2, ArrowRight, X, Github } from 'lucide-react';
import { getGithubStatus, getGithubLoginUrl, getGithubFile, pushGithubPR } from '../api/client';

const EDITOR_MAX_BYTES = 2_000_000;

const applyExactChanges = (content, changes = []) => {
  let next = content;
  for (const change of changes) {
    const oldText = String(change?.old ?? '');
    const newText = String(change?.new ?? '');
    if (!oldText) throw new Error('The generated patch contained an empty search hunk.');
    const first = next.indexOf(oldText);
    if (first < 0) throw new Error('The generated patch no longer matches the current GitHub file. Refresh and generate it again.');
    if (next.indexOf(oldText, first + oldText.length) >= 0) {
      throw new Error('The generated patch matched more than one location. It was not applied automatically.');
    }
    next = `${next.slice(0, first)}${newText}${next.slice(first + oldText.length)}`;
  }
  return next;
};

const suggestedFiles = (editSuggestion, fallbackPath = '') => {
  if (Array.isArray(editSuggestion?.files) && editSuggestion.files.length > 0) {
    return editSuggestion.files
      .map((file) => ({
        file_path: String(file?.file_path || '').trim(),
        changes: Array.isArray(file?.changes) ? file.changes : [],
      }))
      .filter((file) => file.file_path);
  }
  if (editSuggestion?.file_path) {
    return [{
      file_path: String(editSuggestion.file_path).trim(),
      changes: Array.isArray(editSuggestion.changes) ? editSuggestion.changes : [],
    }];
  }
  return fallbackPath ? [{ file_path: fallbackPath, changes: [] }] : [];
};

const DiffReviewModal = ({
  isOpen,
  onClose,
  repoName,
  filePath = '',
  suggestedContent = '',
  initialTitle = '',
  editTicket = '',
  editSuggestion = null,
}) => {
  const [newContent, setNewContent] = useState('');
  const [suggestionApplied, setSuggestionApplied] = useState(false);
  const [fileSha, setFileSha] = useState('');
  const [fileSize, setFileSize] = useState(0);
  const [editPaths, setEditPaths] = useState([]);
  const [selectedPath, setSelectedPath] = useState(filePath);
  const [contentByPath, setContentByPath] = useState({});
  const [shaByPath, setShaByPath] = useState({});
  const [sizeByPath, setSizeByPath] = useState({});
  const [appliedByPath, setAppliedByPath] = useState({});
  const [isLoadingFile, setIsLoadingFile] = useState(false);
  const popupRef = useRef(null);
  const popupTimerRef = useRef(null);
  const popupTimeoutRef = useRef(null);
  const modalRef = useRef(null);
  const closeButtonRef = useRef(null);
  const previousFocusRef = useRef(null);
  const [branchName, setBranchName] = useState('');
  const [prTitle, setPrTitle] = useState(initialTitle || `Update ${filePath}`);
  const [commitMessage, setCommitMessage] = useState(`Apply suggested changes to ${filePath}`);
  const [githubConnected, setGithubConnected] = useState(false);
  const [githubUsername, setGithubUsername] = useState('');
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [prResult, setPrResult] = useState(null);
  const [idempotencyKey, setIdempotencyKey] = useState('');
  const loadCurrentFileRef = useRef(null);
  const checkAuthRef = useRef(null);

  useEffect(() => {
    if (!isOpen) {
      if (popupTimerRef.current) clearInterval(popupTimerRef.current);
      if (popupTimeoutRef.current) clearTimeout(popupTimeoutRef.current);
      popupTimerRef.current = null;
      popupTimeoutRef.current = null;
      return undefined;
    }
    previousFocusRef.current = document.activeElement;
    const focusTimer = window.setTimeout(() => closeButtonRef.current?.focus(), 0);
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== 'Tab' || !modalRef.current) return;
      const focusable = [...modalRef.current.querySelectorAll('button:not([disabled]), a[href], textarea, input, select')];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleKeyDown);
      previousFocusRef.current?.focus?.();
    };
  }, [isOpen, onClose]);

  // Initialize or reset fields when modal opens
  useEffect(() => {
    if (isOpen) {
      // ``suggestedContent`` is an evidence excerpt, not a complete file.
      // Never use it as the replacement document: doing so would truncate the
      // user's file when a citation contains only a small code window.
      setNewContent('');
      setSuggestionApplied(false);
      setFileSha('');
      setFileSize(0);
      const paths = suggestedFiles(editSuggestion, filePath).map((file) => file.file_path);
      setEditPaths(paths);
      setSelectedPath(paths[0] || filePath);
      setContentByPath({});
      setShaByPath({});
      setSizeByPath({});
      setAppliedByPath({});
      const randSuffix = Math.random().toString(36).substring(2, 7);
      const cleanPath = filePath ? filePath.split('/').pop().replace(/[^a-zA-Z0-9]/g, '-') : 'change';
      const issueReference = editSuggestion?.issue_reference ? `#${editSuggestion.issue_reference}` : '';
      setBranchName(`codebase-intel/${cleanPath}-${randSuffix}`);
      setPrTitle(initialTitle || (issueReference ? `Fix issue ${issueReference}: ${filePath || 'file'}` : `Update ${filePath || 'file'}`));
      setCommitMessage(`Apply suggested changes to ${filePath || 'file'}`);
      setSubmitError('');
      setPrResult(null);
      setIdempotencyKey(window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`);
      checkAuth();
    }
  }, [isOpen, suggestedContent, filePath, initialTitle, editTicket, editSuggestion]);

  // Listen for popup auth success
  useEffect(() => {
    const handleMessage = (event) => {
      if (event.source !== popupRef.current || event.data?.type !== 'GITHUB_AUTH_SUCCESS') return;
      if (event.source === popupRef.current && event.data?.type === 'GITHUB_AUTH_SUCCESS') {
        setGithubConnected(true);
        setGithubUsername(event.data.username || 'connected');
        setIsConnecting(false);
        loadCurrentFileRef.current?.();
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const checkAuth = async () => {
    setIsCheckingAuth(true);
    try {
      const res = await getGithubStatus();
      if (res.data?.connected) {
        setGithubConnected(true);
        setGithubUsername(res.data.github_username || '');
        await loadCurrentFile();
      } else {
        setGithubConnected(false);
        setGithubUsername('');
      }
    } catch {
      setGithubConnected(false);
    } finally {
      setIsCheckingAuth(false);
    }
  };

  const loadCurrentFile = async () => {
    const files = suggestedFiles(editSuggestion, filePath);
    if (!repoName || files.length === 0) return;
    if (!editTicket) {
      setSubmitError('Open this file from Code editing and PR mode before reviewing it.');
      return;
    }
    setIsLoadingFile(true);
    setSubmitError('');
    try {
      const loaded = await Promise.all(files.map(async (file) => {
        const res = await getGithubFile(repoName, file.file_path, editTicket);
        const data = res.data || {};
        const content = String(data.content || '');
        const size = Number(data.size || new Blob([content]).size);
        let proposed = content;
        if (file.changes.length > 0) proposed = applyExactChanges(content, file.changes);
        return {
          path: file.file_path,
          content: size <= EDITOR_MAX_BYTES ? proposed : '',
          sha: String(data.sha || ''),
          size,
          applied: proposed !== content,
        };
      }));
      const contents = Object.fromEntries(loaded.map((item) => [item.path, item.content]));
      const shas = Object.fromEntries(loaded.map((item) => [item.path, item.sha]));
      const sizes = Object.fromEntries(loaded.map((item) => [item.path, item.size]));
      const applied = Object.fromEntries(loaded.map((item) => [item.path, item.applied]));
      setContentByPath(contents);
      setShaByPath(shas);
      setSizeByPath(sizes);
      setAppliedByPath(applied);
      const first = files[0].file_path;
      setSelectedPath(first);
      setNewContent(contents[first] || '');
      setFileSha(shas[first] || '');
      setFileSize(sizes[first] || 0);
      setSuggestionApplied(Boolean(applied[first]));
    } catch (err) {
      // ``/github/status`` only tells us that a credential row exists. The
      // first file request is the real token check, so an expired, revoked,
      // or undecryptable token must immediately move the UI back to the
      // disconnected state. Otherwise the modal stays stuck on "Connected"
      // and gives the user no way to start OAuth again.
      if (err.response?.status === 401) {
        setGithubConnected(false);
        setGithubUsername('');
        setSubmitError('GitHub connection expired. Click Connect with GitHub to reconnect.');
      } else {
        setSubmitError(err.response?.data?.detail || 'Could not load the current GitHub file for review.');
      }
    } finally {
      setIsLoadingFile(false);
    }
  };

  // Popup callbacks are installed once, but the selected repository and issue
  // proposal can change between renders. Keep those callbacks pointed at the
  // current loader/auth check instead of a stale first-render closure.
  loadCurrentFileRef.current = loadCurrentFile;
  checkAuthRef.current = checkAuth;

  const selectFile = (path) => {
    setSelectedPath(path);
    setNewContent(contentByPath[path] || '');
    setFileSha(shaByPath[path] || '');
    setFileSize(sizeByPath[path] || 0);
    setSuggestionApplied(Boolean(appliedByPath[path]));
  };

  const handleContentChange = (value) => {
    setNewContent(value);
    setContentByPath((current) => ({ ...current, [selectedPath]: value }));
  };

  const handleConnectGithub = async () => {
    setIsConnecting(true);
    setSubmitError('');
    try {
      const res = await getGithubLoginUrl(window.location.pathname);
      const authUrl = res.data?.authorization_url;
      if (!authUrl) throw new Error('Authorization URL unavailable.');

      const width = 600;
      const height = 700;
      const left = window.screen.width / 2 - width / 2;
      const top = window.screen.height / 2 - height / 2;
      const popup = window.open(
        authUrl,
        'GitHubAuthPopup',
        `toolbar=no, location=no, directories=no, status=no, menubar=no, scrollbars=yes, resizable=yes, copyhistory=no, width=${width}, height=${height}, top=${top}, left=${left}`
      );
      if (!popup) throw new Error('Allow the GitHub popup to connect your account.');
      popupRef.current = popup;

      // Check if popup closed manually
      if (popupTimerRef.current) clearInterval(popupTimerRef.current);
      if (popupTimeoutRef.current) clearTimeout(popupTimeoutRef.current);
      const timer = setInterval(() => {
        if (popup?.closed) {
          clearInterval(timer);
          if (popupTimeoutRef.current) clearTimeout(popupTimeoutRef.current);
          popupTimeoutRef.current = null;
          popupTimerRef.current = null;
          setIsConnecting(false);
          checkAuthRef.current?.();
        }
      }, 1000);
      popupTimerRef.current = timer;
      popupTimeoutRef.current = window.setTimeout(() => {
        if (popupTimerRef.current === timer) {
          clearInterval(timer);
          popupTimerRef.current = null;
          popupTimeoutRef.current = null;
          setIsConnecting(false);
        }
      }, 5 * 60 * 1000);
    } catch (err) {
      setIsConnecting(false);
      setSubmitError(err.response?.data?.detail || err.message || 'Could not start GitHub authorization.');
    }
  };

  const handlePushPR = async () => {
    if (!editTicket) {
      setSubmitError('Open the review from Code editing and PR mode before pushing a pull request.');
      return;
    }
    if (!branchName.trim()) {
      setSubmitError('Branch name is required.');
      return;
    }
    if (isLoadingFile || editPaths.length === 0 || editPaths.some((path) => !shaByPath[path])) {
      setSubmitError('Wait for every current file to finish loading before pushing.');
      return;
    }
    if (editPaths.some((path) => Number(sizeByPath[path] || 0) > EDITOR_MAX_BYTES)) {
      setSubmitError('One of these files is too large for safe browser editing. Generate a smaller targeted change or edit it directly on GitHub.');
      return;
    }
    if (editPaths.some((path) => !String(contentByPath[path] ?? '').length)) {
      setSubmitError('A file content cannot be empty.');
      return;
    }
    setIsSubmitting(true);
    setSubmitError('');
    try {
      const files = editPaths.map((path) => ({
        file_path: path,
        new_content: contentByPath[path],
        file_sha: shaByPath[path],
      }));
      const res = await pushGithubPR({
        repo_name: repoName,
        ...(files.length === 1 ? { file_path: files[0].file_path, new_content: files[0].new_content, file_sha: files[0].file_sha } : { files }),
        branch_name: branchName.trim(),
        commit_message: commitMessage.trim(),
        pr_title: prTitle.trim(),
        pr_body: `${editSuggestion?.issue_reference ? `Fixes #${editSuggestion.issue_reference}.\n\n` : ''}### Proposed Changes\n\nAutomated updates to ${files.map((file) => `\`${file.file_path}\``).join(', ')}.\n\nReviewed and pushed via **Codebase Intelligence**.`,
        idempotency_key: idempotencyKey,
        edit_ticket: editTicket,
      });
      setPrResult(res.data);
    } catch (err) {
      setSubmitError(err.response?.data?.detail || 'Failed to push changes and open Pull Request. Check permissions.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto" role="presentation">
      <div ref={modalRef} className="relative w-full max-w-4xl rounded-[28px] bg-warm-canvas border border-sand shadow-2xl p-6 sm:p-8 my-8 text-ink-black animate-in fade-in zoom-in-95 duration-200" role="dialog" aria-modal="true" aria-labelledby="github-review-title">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-sand pb-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-ember-orange/10 text-ember-orange">
              <GitPullRequest className="w-5 h-5" />
            </div>
            <div>
              <h2 id="github-review-title" className="text-lg font-bold text-ink-black">Review & Push to GitHub</h2>
              <p className="text-xs text-warm-gray font-mono">
                {editPaths.length > 1 ? `${editPaths.length} files · review each before pushing` : (selectedPath || 'Modified file')}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            ref={closeButtonRef}
            aria-label="Close GitHub review"
            className="p-2 rounded-full hover:bg-sand/40 text-warm-gray hover:text-ink-black transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Success View */}
        {prResult ? (
          <div className="text-center py-8 space-y-6">
            <div className="w-16 h-16 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center mx-auto shadow-sm">
              <Check className="w-8 h-8 stroke-[2.5]" />
            </div>
            <div className="space-y-2">
              <h3 className="text-xl font-bold text-ink-black">
                Pull Request #{prResult.pr_number} {prResult.already_existed ? 'Updated' : 'Created'}!
              </h3>
              <p className="text-sm text-warm-gray max-w-md mx-auto">
                Your changes have been committed to branch <span className="font-mono text-charcoal font-semibold bg-sand/40 px-2 py-0.5 rounded">{prResult.branch_name}</span>.
              </p>
              {prResult.is_fork && (
                <p className="text-xs text-stone italic">
                  Created via your fork at {prResult.target_repo}
                </p>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-center gap-4 pt-4">
              <a
                href={prResult.pr_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-ember-orange text-pure-white font-semibold hover:bg-ember-orange/90 transition-all shadow-md hover:shadow-lg"
              >
                <span>View Pull Request on GitHub</span>
                <ExternalLink className="w-4 h-4" />
              </a>
              <button
                onClick={onClose}
                className="px-6 py-3 rounded-xl border border-sand hover:bg-sand/30 font-medium transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          /* Editor & Form View */
          <div className="space-y-6">
            {submitError && (
              <div role="alert" aria-live="assertive" className="flex items-start gap-3 p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">
                <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
                <p>{submitError}</p>
              </div>
            )}

            {/* GitHub Just-in-Time Connection Status */}
            <div className="p-4 rounded-2xl bg-sand/30 border border-sand flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-3">
                <Github className="w-5 h-5 text-charcoal" />
                {isCheckingAuth ? (
                  <span className="text-xs text-warm-gray flex items-center gap-2">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Checking GitHub connection...
                  </span>
                ) : githubConnected ? (
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                    <span className="text-sm font-medium text-charcoal">
                      Connected as <span className="font-bold">@{githubUsername}</span>
                    </span>
                  </div>
                ) : (
                  <div>
                    <p className="text-sm font-semibold text-charcoal">GitHub connection required</p>
                    <p className="text-xs text-warm-gray">Sign in to push to a new branch and open a PR.</p>
                  </div>
                )}
              </div>

              {!githubConnected && !isCheckingAuth && (
                <button
                  onClick={handleConnectGithub}
                  disabled={isConnecting}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-charcoal hover:bg-ink-black text-pure-white text-xs font-semibold transition-all"
                >
                  {isConnecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Github className="w-3.5 h-3.5" />}
                  <span>Connect with GitHub</span>
                </button>
              )}
            </div>

            {/* Review the exact current file. A citation is only an excerpt and
                is shown separately so it can never truncate the file. */}
            <div className="space-y-2">
              {editPaths.length > 1 && (
                <div className="flex flex-wrap gap-2" role="tablist" aria-label="Files in proposed change">
                  {editPaths.map((path) => (
                    <button
                      key={path}
                      type="button"
                      role="tab"
                      id={`github-file-tab-${editPaths.indexOf(path)}`}
                      aria-controls={`github-file-panel-${editPaths.indexOf(path)}`}
                      aria-selected={selectedPath === path}
                      onClick={() => selectFile(path)}
                      className={`rounded-lg border px-3 py-1.5 text-xs font-mono transition-colors ${selectedPath === path ? 'border-ember-orange bg-ember-orange/10 text-ember-orange' : 'border-sand text-warm-gray hover:border-ember-orange/50'}`}
                    >
                      {path}
                    </button>
                  ))}
                </div>
              )}
              <div id={`github-file-panel-${Math.max(0, editPaths.indexOf(selectedPath))}`} role="tabpanel" aria-labelledby={`github-file-tab-${Math.max(0, editPaths.indexOf(selectedPath))}`} className="flex items-center justify-between">
                <label htmlFor="github-file-content" className="text-xs font-semibold uppercase tracking-wider text-warm-gray">
                  File content ({selectedPath})
                </label>
                <span className="text-xs text-stone">
                  {isLoadingFile ? 'Loading current revision…' : fileSize ? `${Math.ceil(fileSize / 1024)} KB · review before push` : 'Connect GitHub to load the current revision'}
                </span>
              </div>
              {fileSize > EDITOR_MAX_BYTES ? (
                <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                  This file is larger than the safe in browser editor limit of 2 MB. The 50 MB ingestion limit remains available, but large files must be edited directly on GitHub or with a targeted patch.
                </div>
              ) : (
                <textarea
                  id="github-file-content"
                  value={newContent}
                  onChange={(e) => handleContentChange(e.target.value)}
                  rows={14}
                  disabled={isLoadingFile || !githubConnected}
                  aria-label={`Editable content for ${selectedPath}`}
                  className="w-full rounded-2xl bg-deep-charcoal border border-charcoal p-4 font-mono text-xs text-pure-white leading-relaxed focus:outline-none focus:ring-2 focus:ring-ember-orange resize-y disabled:opacity-60"
                  placeholder="The current GitHub file will appear here after connection."
                />
              )}
              {editSuggestion && (editPaths.some((path) => appliedByPath[path]) || suggestionApplied) && (
                <p className="text-xs text-emerald-700" role="status">
                  The validated generated patch was applied to the latest file. Review the complete result before pushing.
                </p>
              )}
              {suggestedContent && (
                <details className="text-xs text-warm-gray">
                  <summary className="cursor-pointer select-none">View the cited suggestion excerpt</summary>
                  <pre className="mt-2 max-h-40 overflow-auto rounded-xl bg-deep-charcoal p-3 font-mono text-[11px] text-stone">{suggestedContent}</pre>
                </details>
              )}
            </div>

            {/* Branch and PR Metadata */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-charcoal mb-1 flex items-center gap-1.5">
                  <GitBranch className="w-3.5 h-3.5 text-ember-orange" />
                  <span>Target Branch Name</span>
                </label>
                <input
                  type="text"
                  value={branchName}
                  onChange={(e) => setBranchName(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-sand bg-pure-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ember-orange"
                  placeholder="e.g. codebase-intel/fix-auth"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-charcoal mb-1">Pull Request Title</label>
                <input
                  type="text"
                  value={prTitle}
                  onChange={(e) => setPrTitle(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-sand bg-pure-white text-sm focus:outline-none focus:ring-2 focus:ring-ember-orange"
                  placeholder="PR title..."
                />
              </div>
            </div>

            {/* Commit Message */}
            <div>
              <label className="block text-xs font-semibold text-charcoal mb-1">Commit Message</label>
              <input
                type="text"
                value={commitMessage}
                onChange={(e) => setCommitMessage(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl border border-sand bg-pure-white text-sm focus:outline-none focus:ring-2 focus:ring-ember-orange"
                placeholder="Commit message..."
              />
            </div>

            {/* Modal Actions */}
            <div className="flex items-center justify-end gap-3 pt-4 border-t border-sand">
              <button
                type="button"
                onClick={onClose}
                disabled={isSubmitting}
                className="px-5 py-2.5 rounded-xl border border-sand hover:bg-sand/40 text-sm font-medium transition-colors"
              >
                Cancel
              </button>

              {githubConnected ? (
                <button
                  type="button"
                  onClick={handlePushPR}
                  disabled={isSubmitting}
                  className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-ember-orange hover:bg-ember-orange/90 text-pure-white text-sm font-semibold transition-all shadow-sm hover:shadow-md disabled:opacity-50"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Creating Branch & PR...</span>
                    </>
                  ) : (
                    <>
                      <span>Push & Create Pull Request</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleConnectGithub}
                  disabled={isConnecting}
                  className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-charcoal hover:bg-ink-black text-pure-white text-sm font-semibold transition-all shadow-sm"
                >
                  <Github className="w-4 h-4" />
                  <span>Connect GitHub to Continue</span>
                </button>
              )}
            </div>
          </div>
        )}

      </div>
    </div>
  );
};

export default React.memo(DiffReviewModal);
