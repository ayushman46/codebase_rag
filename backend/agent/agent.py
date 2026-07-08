import json
import tiktoken
from groq import AsyncGroq
from config import settings, groq_rate_limiter
from agent.tools import get_tools_schema, execute_tool

client = AsyncGroq(api_key=settings.groq_api_key)
enc = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(enc.encode(text))

async def run_agent_loop(repo_id: str, question: str, initial_context: str):
    system_prompt = (
        "You are an expert software engineer analyzing a codebase.\\n"
        "You have access to tools to search for symbols or read full files.\\n"
        "If you don't know the answer, use your tools to find it.\\n"
        "Cite the file paths you reference in your final answer."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Context:\\n{initial_context}\\n\\nQuestion: {question}"}
    ]
    
    tool_trace = []
    
    for iteration in range(3):
        # Token Budget Check (~6000 max context allowed by versatile model safely)
        budget = 6000
        current_tokens = sum(count_tokens(m.get('content', '') or '') for m in messages)
        
        # Drop oldest tool results if over budget
        while current_tokens > budget and len(messages) > 3:
            # Try to pop the first tool message
            for i in range(2, len(messages)-1):
                if messages[i]['role'] == 'tool' or messages[i].get('tool_calls'):
                    removed = messages.pop(i)
                    current_tokens -= count_tokens(removed.get('content', '') or '')
                    break
            else:
                break

        await groq_rate_limiter.acquire()
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=get_tools_schema(),
            tool_choice="auto",
            temperature=0.1
        )
        
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_unset=True))
        
        if not msg.tool_calls:
            return msg.content, tool_trace
            
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            tool_name = tool_call.function.name
            
            result = execute_tool(repo_id, tool_name, args)
            
            tool_trace.append({
                "tool": tool_name,
                "input": args,
                "result_summary": result[:200] + "..." if len(result) > 200 else result
            })
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": result
            })
            
    # Final desperate generation if loop maxes out
    messages.append({"role": "user", "content": "Please provide your final answer based on what you found so far."})
    await groq_rate_limiter.acquire()
    response = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.1
    )
    return response.choices[0].message.content, tool_trace
