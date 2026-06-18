import os
import json
import asyncio
import pickle
from typing import List, Dict
import google.generativeai as genai
from groq import AsyncGroq
from config import settings, gemini_rate_limiter, groq_rate_limiter
from .chunker import CodeChunk

genai.configure(api_key=settings.gemini_api_key)
gemini_model = genai.GenerativeModel('gemini-2.0-flash')
groq_client = AsyncGroq(api_key=settings.groq_api_key)

async def generate_with_gemini(prompt: str) -> str:
    await gemini_rate_limiter.acquire()
    await asyncio.sleep(2) 
    try:
        response = await gemini_model.generate_content_async(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini generation error: {e}")
        return ""

async def generate_with_groq(prompt: str) -> str:
    await groq_rate_limiter.acquire()
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.1
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Groq generation error: {e}")
        return ""

async def build_kt_cache(repo_name: str, chunks: List[CodeChunk]):
    cache_path = f"./indexes/{repo_name}/kt_cache.json"
    graph_path = f"./indexes/{repo_name}/graph.pkl"
    
    # Load Knowledge Graph if it exists
    graph_summary = "Knowledge Graph not available."
    if os.path.exists(graph_path):
        try:
            with open(graph_path, 'rb') as f:
                G = pickle.load(f)
                graph_summary = f"Codebase Graph: {len(G.nodes)} nodes, {len(G.edges)} edges representing file structure, imports, and calls."
        except: pass

    semaphore = asyncio.Semaphore(3)
    
    async def bounded_gemini(prompt: str):
        async with semaphore:
            return await generate_with_gemini(prompt)

    # 1. Group chunks by file
    files_to_chunks = {}
    for c in chunks:
        if c.file_path not in files_to_chunks:
            files_to_chunks[c.file_path] = []
        files_to_chunks[c.file_path].append(c)

    # STAGE 1: Bottom-Up File Summaries (Gemini)
    print(f"Summarizing {len(files_to_chunks)} files...")
    file_tasks = []
    file_paths = list(files_to_chunks.keys())[:60] # Cap for prototype
    for file_path in file_paths:
        file_chunks = files_to_chunks[file_path]
        symbols = [c.name for c in file_chunks if c.name != "unknown"]
        calls = []
        for c in file_chunks: calls.extend(c.calls)
        
        prompt = (
            f"As the original creator of this file, explain its specific responsibility in the system.\n"
            f"File Path: {file_path}\n"
            f"Key Symbols (Classes/Functions): {', '.join(symbols[:30])}\n"
            f"Internal Calls: {', '.join(list(set(calls))[:30])}\n"
            f"Context: {graph_summary}\n\n"
            f"Provide a technical 2-paragraph summary."
        )
        file_tasks.append(bounded_gemini(prompt))
    
    file_results = await asyncio.gather(*file_tasks)
    file_summaries = dict(zip(file_paths, file_results))

    # STAGE 2: Pattern Recognition (Groq - High Speed)
    print("Recognizing Tech Stack and Routes...")
    all_symbols = [c.name for c in chunks if c.name != "unknown"]
    all_imports = []
    for c in chunks: all_imports.extend(c.imports)
    
    tech_stack_prompt = (
        f"Based on these imports and symbols from a codebase, identify the EXACT tech stack (languages, frameworks, libraries, databases).\n"
        f"Imports: {', '.join(list(set(all_imports))[:100])}\n"
        f"Symbols: {', '.join(list(set(all_symbols))[:100])}\n\n"
        f"Provide a concise bulleted list of the core technologies."
    )
    tech_stack = await generate_with_groq(tech_stack_prompt)

    routes_prompt = (
        f"Scan these symbols and identify potential API routes or entry points.\n"
        f"Symbols: {', '.join(list(set(all_symbols))[:200])}\n\n"
        f"List the detected routes and their likely purpose."
    )
    routes = await generate_with_groq(routes_prompt)

    # STAGE 3: Top-Down Synthesis (The "Onboarding Manual")
    print("Synthesizing Onboarding Manual...")
    manual_prompt = (
        f"YOU ARE THE ORIGINAL CREATOR of this project. You are writing a 'Transition Manual' for a new senior engineer taking over your role.\n\n"
        f"PROJECT CONTEXT:\n"
        f"Tech Stack: {tech_stack}\n"
        f"API Routes/Entry Points: {routes}\n"
        f"Knowledge Graph Status: {graph_summary}\n"
        f"Key Module Summaries: {json.dumps(list(file_summaries.values())[:10])}\n\n"
        f"REQUIREMENTS:\n"
        f"1. Explain the high-level architecture and WHY these technologies were chosen.\n"
        f"2. Explain the core business logic flow (how data moves through the system).\n"
        f"3. Explain the relationship between key variables and modules.\n"
        f"4. Provide a 'Developer's Guide' section for maintaining the code.\n"
        f"5. Be technical, authoritative, and exhaustive. Do not be brief."
    )
    onboarding_manual = await generate_with_groq(manual_prompt)

    kt_cache = {
        "file_summaries": file_summaries,
        "tech_stack": tech_stack,
        "routes": routes,
        "onboarding_manual": onboarding_manual,
        "architecture_doc": onboarding_manual, # Backwards compatibility
        "db_schema": "Included in manual.",
        "all_endpoints": [routes],
        "graph_stats": graph_summary
    }
    
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(kt_cache, f, indent=2)
    print(f"Indexing complete for {repo_name}.")