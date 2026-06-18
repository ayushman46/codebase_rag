import json
from groq import AsyncGroq
from config import settings, groq_rate_limiter
from .tools import TOOLS_SCHEMA, expand_context, trace_imports, git_blame

client = AsyncGroq(api_key=settings.groq_api_key)

async def run_agent_loop(repo_name: str, question: str, initial_context: str) -> tuple[str, list]:
    await groq_rate_limiter.acquire()
    
    # HARD CAP on initial context to prevent instant 413 Payload Too Large from Groq
    if len(initial_context) > 15000:
        initial_context = initial_context[:15000] + "\n... [CONTEXT TRUNCATED TO FIT API LIMITS] ..."
        
    system_prompt = (
        "You are an Elite Senior Software Engineer performing a deep-dive technical analysis of a codebase. "
        "Your mission is to provide exhaustive, expert-level technical explanations in prose. "
        "NEVER provide raw code blocks or just a list of imports unless explicitly asked for code.\n\n"
        "GUIDELINES:\n"
        "1. PROSE FOCUS: Explain implementation details, logic flow, and purpose using English. Avoid showing code snippets unless they are absolutely essential to the explanation.\n"
        "2. EXHAUSTIVE ANALYSIS: Analyze the provided code chunks with extreme detail. Look at how modules interact and what the business logic achieves.\n"
        "3. MANDATORY EXPLORATION: If the context is insufficient, use your tools. Do not guess.\n"
        "4. DEEP TECH DETAIL: Explain the 'how' and 'why'. Use citations like [File: path/to/file.py].\n"
        "5. RELEVANCY: Stay strictly focused on the user's query. If they ask to 'explain', provide a conceptual and technical summary, not a code dump."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Initial Context from Vector Search:\n{initial_context}\n\nQuestion: {question}"}
    ]
    
    tool_calls_trace = []
    
    for i in range(3): # Max 3 tool call iterations
        try:
            # Aggressively shrink history to fit Groq's 12k TPM limit
            # Total context must be around 6000-8000 chars to be safe
            total_chars = 0
            for m in messages:
                if isinstance(m, dict):
                    total_chars += len(m.get("content", ""))
                else: # ChatCompletionMessage object
                    total_chars += len(m.content or "")
            
            if total_chars > 8000:
                # Keep system prompt and only the very last user/tool interaction
                messages = [messages[0]] + messages[-2:]
                print(f"Aggressive truncation: reduced from {total_chars} chars.")

            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                max_tokens=1000,
                temperature=0.1
            )
        except Exception as e:
            if "reduce the length" in str(e).lower() or "413" in str(e):
                print("Payload too large for Groq, truncating further...")
                # We must shrink the actual content strings because dropping messages wasn't enough
                for idx, m in enumerate(messages):
                    if isinstance(m, dict) and m.get("role") != "system":
                        content = str(m.get("content", ""))
                        if len(content) > 3000:
                            messages[idx]["content"] = content[:3000] + "\n... [EMERGENCY TRUNCATION] ..."
                continue 
            
            print(f"Groq API Error: {e}")
            if i == 0: raise e
            break
        
        response_message = response.choices[0].message
        
        if not response_message.tool_calls:
            return response_message.content, tool_calls_trace
            
        messages.append(response_message)
        
        for tool_call in response_message.tool_calls:
            function_name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": "Error: Invalid JSON arguments."
                })
                continue
            
            tool_trace = {
                "tool": function_name,
                "input": args,
                "result_summary": ""
            }
            
            result = ""
            if function_name == "expand_context":
                result = expand_context(repo_name, args.get("filepath", ""))
            elif function_name == "trace_imports":
                result = trace_imports(repo_name, args.get("symbol", ""), args.get("from_file", ""))
            elif function_name == "git_blame":
                result = git_blame(repo_name, args.get("filepath", ""))
            else:
                result = f"Error: Tool {function_name} not found."
                
            # Truncate tool results heavily for Groq free tier
            if len(result) > 3000:
                result = result[:3000] + "\n... [TRUNCATED] ..."

            tool_trace["result_summary"] = result[:50] + "..."
            tool_calls_trace.append(tool_trace)
            
            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": result
            })
            
    # If we hit max iterations, force an answer without tools
    response = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=2000
    )
    
    return response.choices[0].message.content, tool_calls_trace