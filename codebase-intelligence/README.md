# Codebase Intelligence System

A production-grade RAG and architectural analysis system for GitHub repositories.

## Features
- **Triple-Mode Querying**:
  - `full_context`: Entire small repos in Gemini 1M window.
  - `rag`: Hybrid FAISS + BM25 + Flashrank reranking with Agentic tool-use.
  - `cached_summary`: Instant responses from pre-indexed Knowledge Transfer cache.
- **AST Parsing**: Multi-language support (Python, JS/TS, Java, Go, Rust) via Tree-sitter.
- **Agentic Debugging**: LLM can expand context, trace imports, and check git history autonomously.
- **Real-time UI**: Built with React, Tailwind, and Framer Motion.

## Tech Stack
- **Backend**: FastAPI, Groq (Llama 3.3), Gemini 2.0 Flash, SentenceTransformers, FAISS.
- **Frontend**: Vite, React, Zustand, Tailwind CSS.
- **Infrastructure**: Docker Compose.

## Setup

1. **Environment Variables**:
   Copy `.env.example` to `.env` and add your keys:
   ```bash
   GROQ_API_KEY=your_key
   GEMINI_API_KEY=your_key
   ```

2. **Run Backend**:
   ```bash
   docker-compose up --build
   ```

3. **Run Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## Benchmarking
Run the benchmark script to evaluate retrieval accuracy:
```bash
python backend/benchmark.py
```
