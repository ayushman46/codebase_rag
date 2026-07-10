import asyncio
import json
from typing import List, Dict
import google.generativeai as genai
from groq import AsyncGroq
from config import settings, gemini_rate_limiter, groq_rate_limiter

genai.configure(api_key=settings.gemini_api_key)
gemini_model = genai.GenerativeModel('gemini-2.0-flash')
groq_client = AsyncGroq(api_key=settings.groq_api_key)

async def generate_with_gemini(prompt: str) -> str:
    for attempt in range(3):
        try:
            await gemini_rate_limiter.acquire()
            response = await gemini_model.generate_content_async(prompt)
            return response.text
        except Exception as e:
            if attempt == 2:
                print(f"Gemini generation error after retries: {e}")
                return ""
            await asyncio.sleep(2 ** attempt)

async def generate_with_groq(prompt: str) -> str:
    for attempt in range(3):
        try:
            await groq_rate_limiter.acquire()
            response = await groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3000,
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt == 2:
                print(f"Groq generation error after retries: {e}")
                return ""
            await asyncio.sleep(2 ** attempt)

async def build_kt_cache(supabase_client, repo_id: str, chunks: List[Dict]):
    print(f"Building KT Cache for repo_id {repo_id}")
    
    # Group by file
    files_to_chunks = {}
    for c in chunks:
        path = c['file_path']
        if path not in files_to_chunks:
            files_to_chunks[path] = []
        files_to_chunks[path].append(c['content'])

    semaphore = asyncio.Semaphore(3)
    
    async def summarize_file(file_path: str, file_chunks: List[str]):
        async with semaphore:
            content_preview = "\\n".join(file_chunks)[:3000]
            prompt = (
                f"As the original creator of this file, explain its specific responsibility in the system.\\n"
                f"File Path: {file_path}\\n"
                f"Content Preview:\\n{content_preview}\\n\\n"
                f"Provide a technical 2-paragraph summary."
            )
            res = await generate_with_gemini(prompt)
            return file_path, res

    # Limit to top 20 primary code files to avoid massive delays/costs
    import os
    valid_extensions = {'.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.c', '.cpp', '.h', '.rb', '.php', '.cs', '.sql'}
    
    filtered_files = []
    for path, file_chunks in files_to_chunks.items():
        ext = os.path.splitext(path)[1].lower()
        is_test = any(x in path.lower() for x in ['test', 'spec', 'setupTests'])
        if ext in valid_extensions and not is_test:
            # Sort by total content size to prioritize largest modules
            total_size = sum(len(x) for x in file_chunks)
            filtered_files.append((path, total_size, file_chunks))
            
    filtered_files.sort(key=lambda x: x[1], reverse=True)
    selected_files = filtered_files[:20]
    
    tasks = [summarize_file(path, file_chunks) for path, _, file_chunks in selected_files]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    file_summaries = {}
    for r in results:
        if isinstance(r, tuple):
            file_summaries[r[0]] = r[1]
            
    # Tech Stack
    print("Recognizing Tech Stack...")
    all_content = "\\n".join([c['content'][:500] for c in chunks[:50]]) # Sample for tech stack
    tech_stack_prompt = (
        f"Based on these snippets from a codebase, identify the EXACT tech stack (languages, frameworks, libraries, databases).\n"
        f"Snippets:\n{all_content}\n\n"
        f'Provide a JSON array of strings of the core technologies. Example: ["React", "Node.js"]'
    )
    tech_stack_raw = await generate_with_groq(tech_stack_prompt)
    
    # Try parsing JSON tech stack
    import re
    tech_stack = []
    try:
        match = re.search(r'\\[.*\\]', tech_stack_raw.replace('\\n', ''))
        if match:
            tech_stack = json.loads(match.group(0))
        else:
            tech_stack = [tech_stack_raw]
    except Exception:
        tech_stack = [tech_stack_raw]

    # Synthesis
    print("Synthesizing Onboarding Manual...")
    manual_prompt = (
        f"YOU ARE THE ORIGINAL CREATOR of this project. You are writing a 'Transition Manual' for a new senior engineer taking over your role.\\n\\n"
        f"PROJECT CONTEXT:\\n"
        f"Tech Stack: {tech_stack}\\n"
        f"Key Module Summaries: {json.dumps(list(file_summaries.values())[:10])}\\n\\n"
        f"REQUIREMENTS:\\n"
        f"1. Explain the high-level architecture.\\n"
        f"2. Explain the core business logic flow.\\n"
        f"3. Be technical, authoritative, and exhaustive."
    )
    onboarding_manual = await generate_with_groq(manual_prompt)
    
    # Save to Supabase
    supabase_client.table('kt_cache').insert({
        "repo_id": repo_id,
        "tech_stack": tech_stack,
        "onboarding_manual": onboarding_manual,
        "file_summaries": file_summaries
    }).execute()
    
    print("KT Cache built and saved.")
