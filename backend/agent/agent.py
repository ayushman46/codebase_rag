import json
import tiktoken
from groq import AsyncGroq
from config import settings, groq_rate_limiter
from agent.tools import get_tools_schema, execute_tool

client = AsyncGroq(api_key=settings.groq_api_key)
enc = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(enc.encode(text))

async def run_agent_loop(supabase_client, repo_id: str, question: str, initial_context: str):
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
        await groq_rate_limiter.acquire()
        try:
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=get_tools_schema(),
                tool_choice="auto",
                temperature=0.1
            )
        except Exception as e:
            print(f"Agent loop error: {e}")
            return build_fallback_answer(question, initial_context), tool_trace
        
        msg = response.choices[0].message
        
        # Serialize the assistant message manually to maintain clean API schema mapping
        assistant_message = {
            "role": "assistant",
            "content": msg.content
        }
        if msg.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in msg.tool_calls
            ]
        messages.append(assistant_message)
        
        if not msg.tool_calls:
            return msg.content, tool_trace
            
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            tool_name = tool_call.function.name
            
            result = execute_tool(supabase_client, repo_id, tool_name, args)
            
            # Defensively truncate large outputs to stay well within rate/token boundaries
            max_chars = 3000
            if len(result) > max_chars:
                result = result[:max_chars] + f"\n\n... [Content truncated to {max_chars} characters to prevent token limits]"
            
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
    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.1
        )
        return response.choices[0].message.content, tool_trace
    except Exception as e:
        print(f"Agent finalization error: {e}")
        return build_fallback_answer(question, initial_context), tool_trace


def build_fallback_answer(question: str, initial_context: str) -> str:
    snippets = [segment.strip() for segment in initial_context.split("\n\n") if segment.strip()]
    top_snippets = snippets[:6]
    summary = "\n\n".join(top_snippets)
    return (
        "I could not reach the LLM provider, so here is the retrieved code context "
        f"that best matches your question:\n\nQuestion: {question}\n\n{summary}"
    )
