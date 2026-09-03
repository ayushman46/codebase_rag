"""Hybrid, source-grounded retrieval over Turso chunks."""

import asyncio
import logging
import re
from collections import defaultdict
from typing import Dict, List

from config import ModelConfigurationError, settings
from ingest.embedder import EmbeddingUnavailableError, embed_query

logger = logging.getLogger(__name__)

FILE_PATH_PATTERN = re.compile(
    r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:"
    r"py|js|jsx|ts|tsx|java|go|rs|rb|php|c|cc|cpp|cxx|h|hpp|cs|swift|kt|kts|scala|"
    r"sql|sh|bash|zsh|ps1|yaml|yml|json|toml|ini|cfg|conf|md|rst|txt|html|css|scss|"
    r"sass|less|xml|graphql|gql|proto|dockerfile"
    r"))(?![\w.-])",
    re.IGNORECASE,
)
EXPLORATORY_REPOSITORY_PATTERN = re.compile(
    # Keep this deliberately narrow. Technical questions such as "explain
    # authentication" need implementation evidence, not an automatically
    # injected README. This is only for genuinely repository-wide questions.
    r"(?:\bwhat is (?:this|the) (?:project|repository|codebase)\b|"
    r"\b(?:give|show|provide)\b.{0,32}\b(?:overview|architecture|high[- ]level)\b|"
    r"\b(?:overall|high[- ]level)\s+(?:architecture|overview)\b|"
    r"\b(?:what makes|how is)\b.{0,56}\b(?:different|unique)\b|"
    r"\b(?:purpose|about)\s+(?:this|the)\s+(?:project|repository|codebase)\b)",
    re.IGNORECASE,
)
WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
MAX_CHUNKS_PER_FILE = 2
IMPACT_QUESTION_PATTERN = re.compile(
    r"\b(?:what\s+(?:breaks|is\s+affected)|impact|depend(?:s|encies|ent)|affected\s+files?)\b|"
    r"\bif\s+.+\s+(?:changes?|is\s+removed|is\s+renamed)\b",
    re.IGNORECASE,
)

# These files are useful for repository-wide orientation, but they are not
# implementation evidence for a targeted question. Keep them out of normal
# sparse/dense retrieval so a question about a component cannot be cited with
# a generic README simply because it repeats a few of the same words.
OVERVIEW_FILE_NAMES = {
    "readme", "readme.md", "readme.rst", "readme.txt",
    "contributing", "contributing.md", "changelog", "changelog.md",
    "changes.md", "license", "license.md", "copying",
}

DOCUMENTATION_REQUEST_PATTERN = re.compile(
    r"\b(?:readme|documentation|docs?|contributing|changelog|license)\b",
    re.IGNORECASE,
)

# Natural-language component names do not always include a literal filename
# such as ``SiteHeader.jsx``. These hints bridge that gap without treating a
# whole repository as relevant.
QUESTION_PATH_HINTS = (
    (re.compile(r"\b(?:nav(?:igation)?(?:\s*bar)?|navbar|menu|header)\b", re.IGNORECASE),
     ("nav", "navbar", "navigation", "header", "siteheader")),
    (re.compile(r"\b(?:sidebar|side\s*bar)\b", re.IGNORECASE), ("sidebar", "side-bar")),
    (re.compile(r"\b(?:chat|conversation|message)\b", re.IGNORECASE), ("chat", "conversation", "message")),
    (re.compile(r"\b(?:authentication|authorization|sign[ -]?in|login|oauth)\b", re.IGNORECASE),
     ("auth", "login", "signin", "oauth", "session", "security", "middleware", "route", "router", "api", "main", "app", "config")),
    (re.compile(r"\b(?:api|apis|endpoint|endpoints|route|routes|router|routers|handler|handlers|rest|request|requests)\b", re.IGNORECASE),
     ("api", "apis", "endpoint", "endpoints", "route", "routes", "router", "routers", "handler", "handlers", "server", "main", "app")),
    (re.compile(r"\b(?:database|databases|db|schema|sql|query|queries|migration|migrations)\b", re.IGNORECASE),
     ("database", "db", "schema", "sql", "migration", "migrations", "model", "models", "repository")),
    (re.compile(r"\b(?:index|indexing|ingest|ingestion|clone|cloning|chunk|chunking|embed|embedding|worker|queue|summar(?:y|ize|izer)|manifest)\b", re.IGNORECASE),
     ("index", "indexing", "ingest", "ingestion", "clone", "cloning", "pipeline", "chunk", "chunker", "embed", "embedder", "embedding", "worker", "queue", "summarizer", "manifest")),
    (re.compile(r"\b(?:retriev(?:e|al)|search|semantic|keyword|vector|citation|citations|evidence)\b", re.IGNORECASE),
     ("retriev", "retriever", "search", "query", "vector", "embed", "citation", "evidence", "context")),
)
NARROW_COMPONENT_PATTERN = re.compile(
    r"\b(?:nav(?:igation)?(?:\s*bar)?|navbar|menu|header|sidebar|side\s*bar|chat|conversation|message)\b",
    re.IGNORECASE,
)
LOCATION_QUERY_PATTERN = re.compile(
    r"\b(?:where|which|what)\b.{0,60}\b(?:located|location|defined|implemented|live|lives|entry\s*point|file|path|endpoint|route|api)\b|"
    r"\b(?:locate|find|show)\b.{0,40}\b(?:api|endpoint|route|router|handler|entry\s*point|file)\b",
    re.IGNORECASE,
)
API_QUERY_PATTERN = re.compile(
    r"\b(?:api|apis|endpoint|endpoints|route|routes|router|routers|handler|handlers|rest)\b",
    re.IGNORECASE,
)

# Ordinary question words create very broad FTS matches (for example, a
# question containing ``where`` can match dozens of comments and README
# paragraphs). Remove them before sparse retrieval; technical terms remain.
QUERY_STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "does", "doing", "from",
    "give", "how", "into", "its", "just", "like", "located", "location", "make",
    "please", "show", "that", "the", "this", "what", "when", "where", "which",
    "with", "would", "your", "project", "repository", "codebase", "code", "work",
}


def is_overview_file(file_path: str) -> bool:
    """Return whether a path is orientation/documentation-only evidence."""
    basename = file_path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return basename in OVERVIEW_FILE_NAMES


def overview_file_sql(alias: str = "c") -> str:
    """Build a static SQL predicate for overview-file exclusion.

    The names are constants, not user input, so this remains parameter-safe
    while allowing both root and nested README paths.
    """
    parts = []
    for name in sorted(OVERVIEW_FILE_NAMES):
        parts.extend([f"lower({alias}.file_path) = '{name}'", f"lower({alias}.file_path) LIKE '%/{name}'"])
    return "(" + " OR ".join(parts) + ")"

# Codebases often name authentication modules `auth`, not `authentication`.
# These small, domain-specific expansions improve keyword retrieval without
# treating a broad README as proof for an implementation-level answer.
RETRIEVAL_TERM_ALIASES = {
    "authentication": ("auth", "login", "oauth", "session"),
    "authorization": ("authorize", "auth", "permission", "role"),
    "authenticate": ("auth", "login", "oauth", "session"),
    "authorize": ("authorization", "auth", "permission", "role"),
    "signin": ("sign_in", "login", "oauth", "auth"),
    "login": ("auth", "signin", "oauth", "session"),
}

EVIDENCE_WORKFLOWS = {
    "general": {
        "label": "Repository question",
        "focus": "Answer the question from the most directly relevant source files.",
        "terms": (),
        "path_hints": (),
    },
    "onboarding": {
        "label": "New engineer onboarding",
        "focus": "Explain the entry points, main flow, configuration, and first files a new engineer should read.",
        "terms": ("entrypoint", "main", "app", "config", "route", "service", "readme"),
        "path_hints": ("readme", "main", "app", "config", "route", "server", "index"),
    },
    "security": {
        "label": "Security review",
        "focus": "Trace authentication, authorization, trust boundaries, secrets, validation, and externally reachable handlers.",
        "terms": ("auth", "authentication", "authorization", "permission", "token", "session", "secret", "middleware", "webhook", "upload", "cors", "route", "validate", "sanitize"),
        "path_hints": ("auth", "middleware", "security", "permission", "token", "session", "config", "route", "api", "test"),
    },
    "architecture": {
        "label": "Architecture interview",
        "focus": "Describe components, boundaries, data flow, persistence, and integration points without inventing relationships.",
        "terms": ("module", "package", "service", "route", "config", "schema", "model", "database", "worker", "queue"),
        "path_hints": ("app", "api", "backend", "service", "worker", "config", "schema", "model"),
    },
    "contributor": {
        "label": "Open-source contributor",
        "focus": "Point to local development, tests, conventions, CI, and the smallest safe change surface.",
        "terms": ("contributing", "readme", "test", "tests", "ci", "workflow", "package", "script", "config"),
        "path_hints": ("contribut", "test", "spec", "ci", "workflow", "package", "readme"),
    },
    "due_diligence": {
        "label": "Technical due diligence",
        "focus": "Summarize deployment, dependencies, license, tests, configuration, and operational risks supported by the index.",
        "terms": ("license", "readme", "deploy", "docker", "config", "dependency", "test", "ci", "security"),
        "path_hints": ("license", "readme", "docker", "deploy", "config", "test", "ci", "package"),
    },
}


def extract_requested_file_paths(query: str) -> list[str]:
    paths: list[str] = []
    for match in FILE_PATH_PATTERN.finditer(query):
        path = match.group(1).lstrip("./")
        if path and path not in paths:
            paths.append(path)
    return paths


def extract_question_path_hints(query: str) -> list[str]:
    """Infer a small set of component-name path hints from natural language."""
    hints: list[str] = []
    for pattern, candidates in QUESTION_PATH_HINTS:
        if pattern.search(query):
            hints.extend(candidates)
    return list(dict.fromkeys(hints))[:16]


def is_narrow_component_question(query: str) -> bool:
    """Identify UI-component questions where unrelated files are noise."""
    return bool(NARROW_COMPONENT_PATTERN.search(query))


def is_location_question(query: str) -> bool:
    """Identify requests for the implementation location of a feature.

    Location questions need a small, path-focused evidence set. Returning
    semantically similar files merely to fill ``top_k`` is especially harmful
    here because the user is asking *where* the implementation lives.
    """
    return bool(LOCATION_QUERY_PATTERN.search(query))


def is_api_question(query: str) -> bool:
    """Identify API/route questions so retrieval can prefer server handlers."""
    return bool(API_QUERY_PATTERN.search(query))


def is_strict_target_question(
    query: str,
    requested_paths: list[str],
    include_overview_files: bool = False,
) -> bool:
    """Return whether evidence should be limited to explicit/path-targeted files."""
    # An explicit documentation request is allowed to use README/docs
    # evidence. A named file still follows the exact-file contract below.
    if include_overview_files and not requested_paths:
        return False
    return bool(
        requested_paths
        or is_narrow_component_question(query)
        or is_location_question(query)
        or is_api_question(query)
        or bool(extract_question_path_hints(query))
    )


def path_matches_hints(file_path: str, hints: list[str]) -> bool:
    """Match a path hint on filename/directory boundaries, not arbitrary text.

    Boundary matching prevents a hint such as ``api`` from selecting unrelated
    names like ``capillary.py`` while still matching ``api_client.py`` and
    ``backend/api/routes.py``.
    """
    tokens = [token for token in re.split(r"[^a-z0-9]+", file_path.lower()) if token]
    normalized_tokens = set(tokens)
    # Treat simple plural filenames (routes.py, apis.ts) as the same path
    # family as their singular query term without using substring matching.
    normalized_tokens.update(token[:-1] for token in tokens if token.endswith("s") and len(token) > 3)
    return any(hint.lower() in normalized_tokens for hint in hints)


def is_exploratory_repository_question(query: str, requested_paths: list[str]) -> bool:
    return not requested_paths and bool(EXPLORATORY_REPOSITORY_PATTERN.search(query))


def question_requests_overview_files(query: str, requested_paths: list[str]) -> bool:
    """Allow orientation files only when the user asks for them explicitly."""
    return any(is_overview_file(path) for path in requested_paths) or bool(DOCUMENTATION_REQUEST_PATTERN.search(query))


def is_impact_question(query: str) -> bool:
    return bool(IMPACT_QUESTION_PATTERN.search(query))


def select_diverse_chunks(candidates: list[Dict], limit: int, excluded_ids: set[str] | None = None) -> list[Dict]:
    excluded_ids = excluded_ids or set()
    selected: list[Dict] = []
    selected_ids = set(excluded_ids)
    per_file = defaultdict(int)
    for chunk in candidates:
        chunk_id, file_path = chunk["id"], chunk["file_path"]
        if chunk_id in selected_ids or per_file[file_path] >= MAX_CHUNKS_PER_FILE:
            continue
        selected.append(chunk)
        selected_ids.add(chunk_id)
        per_file[file_path] += 1
        if len(selected) == limit:
            return selected
    for chunk in candidates:
        if chunk["id"] in selected_ids:
            continue
        selected.append(chunk)
        selected_ids.add(chunk["id"])
        if len(selected) == limit:
            break
    return selected


def search_terms(query: str) -> list[str]:
    """Keep sparse matching resilient to punctuation and provider-unavailable embeddings."""
    terms = [
        word.lower()
        for word in WORD_PATTERN.findall(query)
        if len(word) >= 3 and word.lower() not in QUERY_STOPWORDS
    ]
    for term in list(terms):
        terms.extend(RETRIEVAL_TERM_ALIASES.get(term, ()))
    return list(dict.fromkeys(terms))[:10]


def build_evidence_plan(query: str, workflow: str = "general") -> dict:
    """Create a deterministic retrieval plan that is visible to the client.

    The plan guides sparse retrieval and gives the answer/UI an honest account
    of what was targeted. It does not claim that every target exists in a
    repository; absent targets remain an explicit evidence limitation.
    """
    profile = EVIDENCE_WORKFLOWS.get(workflow, EVIDENCE_WORKFLOWS["general"])
    terms = list(dict.fromkeys([*search_terms(query), *profile["terms"]]))[:20]
    # Query-specific hints take precedence over workflow defaults. This keeps
    # a security or due-diligence profile from pushing the actual API/component
    # paths out of the bounded evidence plan.
    path_hints = list(dict.fromkeys([*extract_question_path_hints(query), *profile["path_hints"]]))[:16]
    requested_files = extract_requested_file_paths(query)
    if requested_files:
        scope = "explicit_file"
    elif is_narrow_component_question(query):
        scope = "targeted_component"
    elif is_location_question(query):
        scope = "targeted_api_location" if is_api_question(query) else "targeted_location"
    elif is_exploratory_repository_question(query, requested_files):
        scope = "repository_overview"
    elif extract_question_path_hints(query):
        scope = "targeted_topic"
    else:
        scope = "general"
    return {
        "workflow": workflow if workflow in EVIDENCE_WORKFLOWS else "general",
        "label": profile["label"],
        "focus": profile["focus"],
        "search_terms": terms,
        "path_hints": path_hints,
        "requested_files": requested_files,
        "query_scope": scope,
    }


async def sparse_search(
    store,
    repo_id: str,
    query: str,
    limit: int = 20,
    plan: dict | None = None,
    include_overview_files: bool = False,
) -> list[Dict]:
    terms = list(dict.fromkeys([*search_terms(query), *(plan or {}).get("search_terms", [])]))[:20]
    if not terms:
        return []
    # FTS5 is maintained with triggers in turso/00_init.sql. It avoids a
    # repository-wide LIKE scan for ordinary natural-language questions. Keep
    # the LIKE implementation as a compatibility fallback for databases that
    # were created before this migration.
    fts_expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
    overview_filter = "" if include_overview_files else f" AND NOT {overview_file_sql('c')}"
    try:
        return await store.fetch_all(
            "SELECT c.id, c.file_path, c.start_line, c.end_line, c.language, c.symbols, c.content, "
            "bm25(chunks_fts) AS score FROM chunks_fts "
            "JOIN chunks c ON c.rowid = chunks_fts.rowid "
            f"WHERE chunks_fts MATCH ? AND c.repo_id = ?{overview_filter} "
            "ORDER BY score ASC, c.file_path ASC, c.start_line ASC LIMIT ?",
            [fts_expression, repo_id, limit],
        )
    except Exception as error:
        logger.warning("Turso FTS unavailable; using bounded keyword fallback (%s)", type(error).__name__)
    score_parts = ["CASE WHEN lower(content) LIKE ? OR lower(file_path) LIKE ? THEN 1 ELSE 0 END" for _ in terms]
    matching_parts = ["(lower(content) LIKE ? OR lower(file_path) LIKE ?)" for _ in terms]
    score_args = [value for term in terms for value in (f"%{term}%", f"%{term}%")]
    sql = (
        "SELECT id, file_path, start_line, end_line, language, symbols, content, "
        f"({' + '.join(score_parts)}) AS score FROM chunks c WHERE c.repo_id = ? "
        f"AND ({' OR '.join(matching_parts)}){overview_filter} "
        "ORDER BY score DESC, file_path ASC, start_line ASC LIMIT ?"
    )
    return await store.fetch_all(sql, [*score_args, repo_id, *score_args, limit])


async def dense_search(
    store,
    repo_id: str,
    query_embedding: list[float],
    limit: int = 20,
    include_overview_files: bool = False,
) -> list[Dict]:
    """Use Turso's native cosine-distance function; query filtering preserves tenant isolation."""
    import json
    overview_filter = "" if include_overview_files else f" AND NOT {overview_file_sql('chunks')}"
    return await store.fetch_all(
        "SELECT id, file_path, start_line, end_line, language, symbols, content, "
        "vector_distance_cos(embedding, vector32(?)) AS distance "
        f"FROM chunks WHERE repo_id = ? AND embedding IS NOT NULL{overview_filter} ORDER BY distance ASC LIMIT ?",
        [json.dumps(query_embedding), repo_id, limit],
    )


async def requested_file_chunks(store, repo_id: str, file_path: str, limit: int) -> list[Dict]:
    exact_or_suffix = file_path.lower() if "/" in file_path else f"%/{file_path.lower()}"
    return await store.fetch_all(
        "SELECT id, file_path, start_line, end_line, language, symbols, content FROM chunks "
        "WHERE repo_id = ? AND (lower(file_path) = ? OR lower(file_path) LIKE ?) ORDER BY file_path, start_line LIMIT ?",
        [repo_id, file_path.lower(), exact_or_suffix, limit],
    )


async def requested_files_chunks(store, repo_id: str, file_paths: list[str], limit: int) -> list[Dict]:
    """Fetch all explicitly requested files in one database round trip.

    Explicit paths are an exact citation contract: the caller will return only
    these rows. A single OR query retains the previous per-path candidate
    budget while avoiding one network round trip per path.
    """
    if not file_paths:
        return []
    conditions: list[str] = []
    args: list[object] = [repo_id]
    for file_path in file_paths:
        exact_or_suffix = file_path.lower() if "/" in file_path else f"%/{file_path.lower()}"
        conditions.append("(lower(file_path) = ? OR lower(file_path) LIKE ?)")
        args.extend([file_path.lower(), exact_or_suffix])
    args.append(max(1, limit) * len(file_paths))
    return await store.fetch_all(
        "SELECT id, file_path, start_line, end_line, language, symbols, content FROM chunks "
        f"WHERE repo_id = ? AND ({' OR '.join(conditions)}) ORDER BY file_path, start_line LIMIT ?",
        args,
    )


async def path_hint_chunks(
    store,
    repo_id: str,
    hint: str,
    limit: int = 2,
    include_overview_files: bool = False,
) -> list[Dict]:
    """Fetch a small representative sample for an evidence-plan path hint."""
    overview_filter = "" if include_overview_files else f" AND NOT {overview_file_sql('chunks')}"
    return await store.fetch_all(
        "SELECT id, file_path, start_line, end_line, language, symbols, content FROM chunks "
        f"WHERE repo_id = ? AND lower(file_path) LIKE ?{overview_filter} ORDER BY file_path, start_line LIMIT ?",
        [repo_id, f"%{hint.lower()}%", limit],
    )


async def path_hint_chunks_batch(
    store,
    repo_id: str,
    hints: list[str],
    limit: int = 2,
    include_overview_files: bool = False,
) -> list[Dict]:
    """Fetch the bounded result for every path hint in one SQL statement.

    The window function applies the same ``LIMIT`` independently to each hint
    that the former one-query-per-hint implementation used. Rows carry the
    matching hint so callers can preserve the evidence-plan explanations.
    """
    hints = list(dict.fromkeys(hints))
    if not hints:
        return []
    values = ", ".join("(?, ?, ?)" for _ in hints)
    args: list[object] = []
    for hint_index, hint in enumerate(hints):
        args.extend([hint_index, hint, f"%{hint.lower()}%"])
    args.extend([repo_id, max(1, limit)])
    overview_filter = "" if include_overview_files else f" AND NOT {overview_file_sql('c')}"
    try:
        rows = await store.fetch_all(
            "WITH hints(hint_order, hint, pattern) AS (VALUES " + values + "), "
            "ranked AS ("
            "SELECT c.id, c.file_path, c.start_line, c.end_line, c.language, c.symbols, c.content, "
            "h.hint AS matched_hint, h.hint_order AS hint_order, "
            "ROW_NUMBER() OVER (PARTITION BY h.hint ORDER BY c.file_path, c.start_line) AS hint_rank "
            "FROM chunks c JOIN hints h ON lower(c.file_path) LIKE h.pattern "
            f"WHERE c.repo_id = ?{overview_filter}) "
            "SELECT id, file_path, start_line, end_line, language, symbols, content, matched_hint, hint_order "
            "FROM ranked WHERE hint_rank <= ? ORDER BY hint_order, file_path, start_line",
            args,
        )
        return rows
    except Exception as error:
        # Keep repositories created on older SQLite/libSQL versions working;
        # the compatibility path has identical per-hint ordering and limits.
        logger.warning("Batched path-hint retrieval unavailable; using compatibility queries (%s)", type(error).__name__)
        rows: list[Dict] = []
        for hint_order, hint in enumerate(hints):
            for chunk in await path_hint_chunks(
                store, repo_id, hint, limit=limit, include_overview_files=include_overview_files
            ):
                row = dict(chunk)
                row["matched_hint"] = hint
                row["hint_order"] = hint_order
                rows.append(row)
        return rows


async def dependent_file_chunks(store, repo_id: str, target_paths: list[str], limit: int = 20) -> list[Dict]:
    """Retrieve files that import a target according to the resolved graph."""
    if not target_paths:
        return []
    target_conditions = []
    target_args = []
    for path in target_paths:
        target_conditions.append("(d.target_file = ? OR d.target_file LIKE ?)")
        target_args.extend([path, f"%/{path}"])
    return await store.fetch_all(
        "SELECT DISTINCT c.id, c.file_path, c.start_line, c.end_line, c.language, c.symbols, c.content "
        "FROM repo_dependencies d JOIN chunks c ON c.repo_id = d.repo_id AND c.file_path = d.source_file "
        f"WHERE d.repo_id = ? AND ({' OR '.join(target_conditions)}) "
        "ORDER BY c.file_path, c.start_line LIMIT ?",
        [repo_id, *target_args, limit],
    )


async def retrieve_context(store, repo_id: str, query: str, top_k: int = 8, workflow: str = "general") -> List[Dict]:
    requested_paths = extract_requested_file_paths(query)
    include_overview = is_exploratory_repository_question(query, requested_paths)
    evidence_plan = build_evidence_plan(query, workflow)
    include_overview_files = include_overview or question_requests_overview_files(query, requested_paths)
    evidence_plan["overview_files_allowed"] = include_overview_files

    # A named file is an exact request. Running broad semantic/keyword searches
    # here only adds latency because the final evidence contract already
    # discards those results. Returning an empty set when the path is absent is
    # also safer than filling the answer with similarly-worded files.
    if requested_paths:
        rows = await requested_files_chunks(store, repo_id, requested_paths, top_k)
        if not rows:
            return []
        requested_chunks = []
        for chunk in sorted(rows, key=lambda item: (item["file_path"], item["start_line"])):
            enriched = dict(chunk)
            enriched["_retrieval_methods"] = ["requested_file"]
            enriched["_retrieval_reasons"] = ["Explicit file path requested in the question"]
            enriched["_evidence_plan"] = evidence_plan
            enriched["_relevance_score"] = 2.0
            requested_chunks.append(enriched)
        return requested_chunks[:top_k]

    strict_target = is_strict_target_question(query, requested_paths, include_overview_files)

    sparse_task = asyncio.create_task(
        sparse_search(store, repo_id, query, plan=evidence_plan, include_overview_files=include_overview_files)
    )
    plan_hints = evidence_plan.get("path_hints", [])[:8]
    plan_task = asyncio.create_task(
        path_hint_chunks_batch(store, repo_id, plan_hints, include_overview_files=include_overview_files)
    ) if plan_hints else None
    readme_task = (
        asyncio.create_task(store.fetch_all(
            "SELECT id, file_path, start_line, end_line, language, symbols, content FROM chunks "
            "WHERE repo_id = ? AND lower(file_path) LIKE '%readme.md' ORDER BY start_line LIMIT 1", [repo_id]
        )) if include_overview else None
    )
    overview_task = (
        asyncio.create_task(store.fetch_all(
            "SELECT id, file_path, start_line, end_line, language, symbols, content FROM chunks "
            "WHERE repo_id = ? ORDER BY file_path, start_line LIMIT ?", [repo_id, settings.overview_retrieval_candidates]
        )) if include_overview else None
    )

    dense_task = None
    if not strict_target:
        try:
            query_embedding = await asyncio.to_thread(embed_query, query)
            dense_task = asyncio.create_task(
                dense_search(store, repo_id, query_embedding, include_overview_files=include_overview_files)
            )
        except (EmbeddingUnavailableError, ModelConfigurationError):
            logger.warning("NVIDIA query embedding unavailable; falling back to keyword retrieval")
    else:
        # Strict target questions are filtered to the planned path families
        # below, so exact dense search cannot contribute to the final set.
        logger.debug("Skipping dense retrieval for strict targeted question")

    pending = [sparse_task]
    if dense_task:
        pending.insert(0, dense_task)
    if plan_task:
        pending.append(plan_task)
    if readme_task:
        pending.append(readme_task)
    if overview_task:
        pending.append(overview_task)
    results = await asyncio.gather(*pending, return_exceptions=True)

    successful = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("A retrieval strategy failed for %s (%s)", repo_id, type(result).__name__)
            successful.append([])
        else:
            successful.append(result)
    cursor = 0
    dense_chunks = successful[cursor] if dense_task else []
    cursor += 1 if dense_task else 0
    sparse_chunks = successful[cursor]
    cursor += 1
    plan_results = successful[cursor] if plan_task else []
    cursor += 1 if plan_task else 0
    readme_chunks = successful[cursor] if readme_task else []
    cursor += 1 if readme_task else 0
    overview_chunks = successful[cursor] if overview_task else []

    # Keep this guard in addition to the SQL predicates. It protects callers
    # that provide a compatibility/mock store and makes the citation contract
    # explicit at the final evidence boundary.
    if not include_overview_files:
        dense_chunks = [chunk for chunk in dense_chunks if not is_overview_file(str(chunk.get("file_path", "")))]
        sparse_chunks = [chunk for chunk in sparse_chunks if not is_overview_file(str(chunk.get("file_path", "")))]
        plan_results = [chunk for chunk in plan_results if not is_overview_file(str(chunk.get("file_path", "")))]

    def annotate(chunk: Dict, method: str, reason: str) -> Dict:
        enriched = dict(chunk)
        enriched["_retrieval_methods"] = list(dict.fromkeys([*(enriched.get("_retrieval_methods") or []), method]))
        enriched["_retrieval_reasons"] = list(dict.fromkeys([*(enriched.get("_retrieval_reasons") or []), reason]))
        enriched["_evidence_plan"] = evidence_plan
        return enriched

    planned_map: dict[str, Dict] = {}
    for chunk in plan_results:
        matched_hint = str(chunk.get("matched_hint") or "path")
        row = dict(chunk)
        row.pop("matched_hint", None)
        row.pop("hint_rank", None)
        row.pop("hint_order", None)
        existing = planned_map.get(row["id"], row)
        planned_map[row["id"]] = annotate(
            existing,
            "workflow_target",
            f"Evidence-plan target matching the '{matched_hint}' path hint",
        )
    scores: dict[str, float] = {}
    chunk_map: dict[str, Dict] = {}
    for chunk in planned_map.values():
        chunk_map[chunk["id"]] = chunk
        scores[chunk["id"]] = scores.get(chunk["id"], 0) + 0.5
    for source, method, reason in (
        (dense_chunks, "semantic", "Semantic similarity to the question"),
        (sparse_chunks, "keyword", "Keyword match in file path or source content"),
    ):
        for rank, chunk in enumerate(source):
            annotated = annotate(chunk_map.get(chunk["id"], chunk), method, reason)
            chunk_map[chunk["id"]] = annotated
            scores[chunk["id"]] = scores.get(chunk["id"], 0) + 1.0 / (60 + rank + 1)
            if path_matches_hints(str(chunk.get("file_path", "")), evidence_plan["path_hints"]):
                # A path match is stronger evidence than a generic semantic
                # match, particularly for ``where is the API defined?``
                # questions. Keep this boost deterministic and bounded.
                scores[chunk["id"]] += 0.75
    ranked_chunks = [chunk_map[chunk_id] for chunk_id in sorted(scores, key=scores.get, reverse=True)]

    # Impact questions get one extra, explicitly labelled pass over the
    # resolved dependency graph. If no file is named, use only a few directly
    # matched files as targets; unresolved package aliases are never invented.
    dependency_chunks: list[Dict] = []
    if is_impact_question(query):
        target_paths = list(requested_paths)
        if not target_paths:
            target_paths = list(dict.fromkeys(chunk["file_path"] for chunk in sparse_chunks[:3]))
        try:
            dependency_chunks = await dependent_file_chunks(store, repo_id, target_paths)
        except Exception as error:
            logger.warning("Dependency impact retrieval unavailable for %s (%s)", repo_id, type(error).__name__)
        for chunk in dependency_chunks:
            annotated = annotate(
                chunk_map.get(chunk["id"], chunk),
                "dependency",
                "Depends on a directly matched file in the indexed repository graph",
            )
            chunk_map[chunk["id"]] = annotated
            scores[chunk["id"]] = scores.get(chunk["id"], 0) + 0.02
        ranked_chunks = [chunk_map[chunk_id] for chunk_id in sorted(scores, key=scores.get, reverse=True)]

    # For a targeted component or implementation-location question, do not
    # fill the remaining context slots with arbitrary semantic matches. Keep
    # only files whose paths identify the requested area; if no such path is
    # present, returning no evidence is safer than citing unrelated files.
    if not requested_paths and is_strict_target_question(query, requested_paths, include_overview_files):
        target_hints = extract_question_path_hints(query)
        targeted_chunks = [
            chunk for chunk in ranked_chunks
            if path_matches_hints(str(chunk.get("file_path", "")), target_hints)
        ]
        ranked_chunks = targeted_chunks
    # Broad overview evidence is a fallback, never an automatic citation. If
    # dense or sparse retrieval has direct evidence, that evidence remains the
    # entire source set. This prevents README.md from appearing beside an
    # implementation question merely because it contains words like "explain".
    if include_overview and not ranked_chunks:
        fallback_by_id: dict[str, Dict] = {}
        for chunk in [*readme_chunks, *overview_chunks]:
            fallback_by_id.setdefault(chunk["id"], annotate(chunk, "overview", "Repository-wide overview fallback; no direct term match"))
        ranked_chunks = list(fallback_by_id.values())

    final_chunks = select_diverse_chunks(ranked_chunks, top_k)
    for chunk in final_chunks:
        chunk["_relevance_score"] = round(scores.get(chunk["id"], 0.0), 6)
    return final_chunks
