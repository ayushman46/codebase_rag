# Codebase Intelligence System

The Codebase Intelligence System is a production grade platform designed for engineers to analyze and query large software repositories using natural language. This system combines advanced retrieval strategies with agentic reasoning to provide deep insights into complex codebases.

## Core Capabilities

1. Multi Strategy Query Routing
The system intelligently classifies every query into one of three optimized modes.
Full Context Mode handles small repositories by processing the entire codebase within a large context window.
RAG Mode uses a hybrid search approach for precise function level questions.
Cached Summary Mode provides instant answers for high level architectural overviews using precomputed knowledge.

2. High Fidelity Code Parsing
Unlike traditional RAG systems that split text at arbitrary limits, this system utilizes Tree Sitter AST parsing. It extracts complete functions and classes to ensure that code chunks maintain logical boundaries and structural integrity across multiple programming languages.

3. Agentic Debugging Loop
When initial context is insufficient, an autonomous agent loop can expand its search. The agent has the ability to trace import chains, fetch complete file contents, and analyze git history to resolve complex queries.

4. Performance Optimized Retrieval
The platform combines dense vector search via FAISS and sparse keyword search via BM25. A cross encoder reranker ensures sub 100ms precision by fusion scoring and ranking results before they reach the language model.

## Technical Architecture

Backend
The backend is built with FastAPI and Python 3.11. It uses an asynchronous architecture to handle LLM calls and file operations efficiently.

Frontend
The frontend is a modern React application. It features real time indexing progress, syntax highlighted code citations, and interactive agent traces.

Language Models
The system leverages Groq for fast query classification and agent loops. Google Gemini handles large context window operations and repository summarization.

Storage
The system uses a file based storage approach for FAISS indexes, BM25 pickles, and precomputed metadata. This eliminates the need for complex database configurations.

## Getting Started

1. Environment Configuration
Create a .env file in the root directory. Add your API keys for Groq and Gemini as specified in the example configuration.

2. Backend Setup
The backend can be deployed using Docker. Run the docker compose up command to build and start the primary services.

3. Frontend Setup
Navigate to the frontend directory. Install the necessary dependencies and start the development server using standard package management commands.

4. Verification
A benchmark script is included to run automated accuracy tests against real world repositories. Use this to verify the system performance.

## Supported Languages

The system provides specialized support for the following languages
Python
JavaScript
TypeScript
Java
Go
Rust
Markdown and configuration files are also supported through a unified indexing pipeline.
