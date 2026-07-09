# Codebase Intelligence System

A production ready AI powered codebase understanding platform that allows developers to chat with any GitHub repository using Retrieval Augmented Generation (RAG), hybrid search, and agentic reasoning.

The system automatically clones a repository, indexes its source code, generates semantic embeddings, and enables natural language conversations with accurate, cited responses grounded in the repository itself.

---

## Overview

Understanding a large codebase is one of the biggest challenges for developers joining new projects.

This platform automates repository ingestion, semantic indexing, and intelligent retrieval so developers can ask questions such as:

* How does authentication work?
* Where is this API implemented?
* Trace the execution of this function.
* Explain the overall architecture.
* Which files are responsible for database operations?

Instead of searching manually through hundreds of files, the system retrieves only the relevant code and provides grounded answers.

---

## Features

* GitHub repository ingestion
* Automatic code parsing and intelligent chunking
* Local embedding generation
* Hybrid semantic and keyword search
* Reciprocal Rank Fusion based retrieval
* Agentic multi-step reasoning
* Repository onboarding manual generation
* Multi-tenant architecture
* Google OAuth authentication
* Source cited responses
* Background asynchronous indexing

---

## Architecture

```
React + Vite
      │
      ▼
 FastAPI Backend
      │
 ┌────┴────────────────────┐
 │                         │
 ▼                         ▼
Ingestion             Query Engine
 │                         │
 ▼                         ▼
Supabase PostgreSQL with pgvector
```

---

## Technology Stack

### Frontend

* React
* Vite
* Tailwind CSS
* Zustand

### Backend

* FastAPI
* Python
* AsyncIO

### Database

* Supabase
* PostgreSQL
* pgvector

### AI

* Sentence Transformers
* Groq
* Google Gemini

### Authentication

* Supabase Auth
* Google OAuth

---

## Retrieval Pipeline

1. Repository is cloned from GitHub.
2. Source files are intelligently chunked.
3. Each chunk is converted into vector embeddings.
4. Embeddings and metadata are stored inside PostgreSQL.
5. User queries are embedded.
6. Dense vector search and keyword search run simultaneously.
7. Reciprocal Rank Fusion merges both result sets.
8. Retrieved context is passed to the LLM.
9. Agent tools expand context when required.
10. A grounded response is returned with citations.

---

## Search Strategy

The system combines multiple retrieval techniques.

### Dense Retrieval

Semantic similarity using vector embeddings.

### Sparse Retrieval

PostgreSQL Full Text Search for exact identifiers, variable names, and symbols.

### Reciprocal Rank Fusion

Results from both retrieval methods are merged to improve ranking quality and reduce retrieval failures.

---

## Agent Workflow

The reasoning engine can perform multiple retrieval steps before generating an answer.

Available capabilities include:

* Repository summarization
* Context expansion
* Symbol tracing
* Architecture explanation
* Dependency discovery

The agent dynamically decides whether additional retrieval is required before responding.

---

## Engineering Highlights

### Intelligent Chunking

Instead of relying on language-specific AST parsers, the project uses robust regex-based boundary detection with recursive fallback splitting, allowing reliable indexing across multiple programming languages.

### Hybrid Retrieval

Combines semantic vector search with traditional keyword search for higher retrieval accuracy.

### Multi Tenant Design

Every repository is scoped to an authenticated user, ensuring complete data isolation.

### Rate Limit Protection

An asynchronous sliding window queue prevents API rate limit failures during ingestion and querying.

### Knowledge Cache

Repository summaries and onboarding documentation are generated once and reused for future conversations, reducing latency and token usage.

---

## Project Structure

```
frontend/
backend/
database/
embeddings/
retrieval/
agents/
utils/
```

---

## Future Improvements

* AST based language aware chunking
* Repository visualization
* Dependency graph generation
* Pull request analysis
* Code review assistant
* Repository comparison
* Local LLM support
* Incremental repository indexing

---

## Getting Started

Clone the repository.

```bash
git clone <repository-url>
```

Install dependencies.

```bash
pip install -r requirements.txt
```

Configure environment variables.

```bash
SUPABASE_URL=
SUPABASE_KEY=
GROQ_API_KEY=
GOOGLE_API_KEY=
```

Run the backend.

```bash
uvicorn app.main:app --reload
```

Run the frontend.

```bash
npm install
npm run dev
```

---

## Why This Project

This project demonstrates practical applications of modern AI systems beyond simple chatbot interfaces.

It combines retrieval augmented generation, vector search, agentic reasoning, asynchronous backend engineering, and scalable database design into a production-oriented platform capable of understanding and navigating large software repositories.

---

## License

MIT License
