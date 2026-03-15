import json
from dataclasses import dataclass, field
import textwrap, time, re

from config import client, ACTIVE_MODEL
from tools import ALL_TOOL_FUNCTIONS, ALL_SCHEMAS
from prompts import SINGLE_AGENT_PROMPT, PLANNER_PROMPT, SOLVER_PROMPT, VALIDATOR_PROMPT




@dataclass
class AgentResult:
    agent_name   : str
    answer       : str
    tools_called : list  = field(default_factory=list)   # tool names in order called
    raw_data     : dict  = field(default_factory=dict)   # tool name → raw tool output
    confidence   : float = 0.0                           # set by evaluator / critic
    issues_found : list  = field(default_factory=list)   # set by evaluator / critic
    reasoning    : str   = ""

    def summary(self):
        print(f"\n{'─'*54}")
        print(f"Agent      : {self.agent_name}")
        print(f"Tools used : {', '.join(self.tools_called) or 'none'}")
        print(f"Confidence : {self.confidence:.0%}")
        if self.issues_found:
            print(f"Issues     : {'; '.join(self.issues_found)}")
        print(f"Answer     :\n{textwrap.indent(self.answer[:500], '  ')}")



def format_conversation_history(conversation_history: list) -> str:
    """
    conversation_history format:
    [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."},
        ...
    ]
    """
    if not conversation_history:
        return "No prior conversation."

    lines = []
    for msg in conversation_history:
        role = msg["role"].upper()
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def run_specialist_agent(
    agent_name: str,
    system_prompt: str,
    task: str,
    tool_schemas: list,
    conversation_history: list | None = None,
    max_iters: int = 8,
    verbose: bool = True,
) -> AgentResult:
    """
    Core agentic loop with optional conversation history.
    """
    history_text = format_conversation_history(conversation_history or [])

    user_task = f"""
Conversation history:
{history_text}

Current user question:
{task}
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_task}
    ]

    tools_called = []
    raw_data = {}

    for _ in range(max_iters):
        response = client.chat.completions.create(
            model=ACTIVE_MODEL,
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            max_tokens=1000,
        )

        assistant_message = response.choices[0].message

        if assistant_message.tool_calls:
            messages.append({
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_message.tool_calls
                ],
            })

            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                if verbose:
                    print(f"\n🔧 {agent_name} called tool: {tool_name} with args: {tool_args}")

                tools_called.append(tool_name)

                if tool_name in ALL_TOOL_FUNCTIONS:
                    try:
                        tool_func = ALL_TOOL_FUNCTIONS[tool_name]
                        tool_result = tool_func(**tool_args)
                    except Exception as e:
                        tool_result = {"error": str(e)}
                else:
                    tool_result = {"error": f"Tool '{tool_name}' not found"}

                raw_data[f"{tool_name}_{len(raw_data)+1}"] = tool_result

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result),
                })
        else:
            return AgentResult(
                agent_name=agent_name,
                answer=assistant_message.content or "No answer produced.",
                tools_called=tools_called,
                raw_data=raw_data,
            )

    return AgentResult(
        agent_name=agent_name,
        answer="Max iterations reached before producing a final answer.",
        tools_called=tools_called,
        raw_data=raw_data,
    )



def run_baseline(question: str, conversation_history: list | None = None, verbose: bool = True) -> AgentResult:
    system_prompt = (
        "You are a careful and honest assistant answering stock-related questions. "
        "You do not have access to tools, APIs, databases, or live market data. "
        "Answer using only general knowledge and reasoning. "
        "Use the conversation history to resolve follow-up references such as 'that', 'it', or 'the two'. "
        "If you are unsure, say so clearly. Do not invent facts."
    )

    history_text = format_conversation_history(conversation_history or [])

    response = client.chat.completions.create(
        model=ACTIVE_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Conversation history:\n{history_text}\n\nCurrent user question:\n{question}"}
        ],
        max_tokens=1000,
    )

    answer = response.choices[0].message.content.strip() if response.choices[0].message.content else "I don't know."

    return AgentResult(
        agent_name="Baseline",
        answer=answer,
        tools_called=[]
    )


def run_single_agent(question: str, conversation_history: list | None = None, verbose: bool = True) -> AgentResult:
    return run_specialist_agent(
        agent_name="Single Agent",
        system_prompt=SINGLE_AGENT_PROMPT,
        task=question,
        tool_schemas=ALL_SCHEMAS,
        conversation_history=conversation_history,
        max_iters=8,
        verbose=verbose,
    )


def parse_validator_output(text: str) -> dict:
    result = {
        "valid": False,
        "issues": ["validator parse error"],
        "corrected_answer": text.strip() if text else "Validator did not return a valid answer."
    }

    if not text:
        return result

    valid_match = re.search(r"VALID:\s*(yes|no)", text, flags=re.IGNORECASE)
    issues_match = re.search(r"ISSUES:\s*(.*?)(?:\nCORRECTED_ANSWER:|\Z)", text, flags=re.IGNORECASE | re.DOTALL)
    corrected_match = re.search(r"CORRECTED_ANSWER:\s*(.*)", text, flags=re.IGNORECASE | re.DOTALL)

    if valid_match:
        result["valid"] = valid_match.group(1).strip().lower() == "yes"

    if issues_match:
        issues_text = issues_match.group(1).strip()
        result["issues"] = [] if issues_text.lower() == "none" else [issues_text]

    if corrected_match:
        result["corrected_answer"] = corrected_match.group(1).strip()

    return result


def run_planner(question: str, conversation_history: list | None = None, verbose: bool = True) -> AgentResult:
    return run_specialist_agent(
        agent_name="Planner",
        system_prompt=PLANNER_PROMPT,
        task=question,
        tool_schemas=[],
        conversation_history=conversation_history,
        max_iters=1,
        verbose=verbose,
    )

def run_solver(question: str, planner_output: str, conversation_history: list | None = None, verbose: bool = True) -> AgentResult:
    solver_task = f"""
PLANNER_OUTPUT:
{planner_output}

Solve the current user question using the planner output and the conversation history.
""".strip()

    return run_specialist_agent(
        agent_name="Solver",
        system_prompt=SOLVER_PROMPT,
        task=solver_task + f"\n\nCurrent user question:\n{question}",
        tool_schemas=ALL_SCHEMAS,
        conversation_history=conversation_history,
        max_iters=8,
        verbose=verbose,
    )

def run_validator(question: str, planner_result: AgentResult, solver_result: AgentResult,
                  conversation_history: list | None = None, verbose: bool = True) -> AgentResult:
    history_text = format_conversation_history(conversation_history or [])

    validator_task = f"""
Conversation history:
{history_text}

QUESTION:
{question}

PLANNER_OUTPUT:
{planner_result.answer}

DRAFT_ANSWER:
{solver_result.answer}

TOOLS_CALLED:
{solver_result.tools_called}

RAW_TOOL_OUTPUTS:
{json.dumps(solver_result.raw_data, indent=2)}
""".strip()

    raw_validator_result = run_specialist_agent(
        agent_name="Validator",
        system_prompt=VALIDATOR_PROMPT,
        task=validator_task,
        tool_schemas=[],
        conversation_history=[],
        max_iters=1,
        verbose=verbose,
    )

    parsed = parse_validator_output(raw_validator_result.answer)

    if parsed["valid"] and not parsed["issues"]:
        confidence = 0.95
    elif parsed["valid"]:
        confidence = 0.85
    elif parsed["issues"] and "parse error" not in parsed["issues"][0].lower():
        confidence = 0.70
    else:
        confidence = 0.50

    return AgentResult(
        agent_name="Validator",
        answer=parsed["corrected_answer"],
        tools_called=[],
        raw_data={},
        confidence=confidence,
        issues_found=parsed["issues"],
        reasoning=raw_validator_result.answer,
    )


def run_multi_agent(question: str, conversation_history: list | None = None, verbose: bool = True) -> dict:
    start = time.time()

    planner_result = run_planner(question, conversation_history=conversation_history, verbose=verbose)
    planner_result.confidence = 0.80

    solver_result = run_solver(
        question=question,
        planner_output=planner_result.answer,
        conversation_history=conversation_history,
        verbose=verbose,
    )
    solver_result.confidence = 0.85 if solver_result.tools_called else 0.65

    validator_result = run_validator(
        question=question,
        planner_result=planner_result,
        solver_result=solver_result,
        conversation_history=conversation_history,
        verbose=verbose,
    )

    elapsed = time.time() - start

    return {
        "final_answer": validator_result.answer,
        "agent_results": [planner_result, solver_result, validator_result],
        "elapsed_sec": elapsed,
        "architecture": "pipeline-3stage",
    }