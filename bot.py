
import os
import sys
import json
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from tabulate import tabulate
from openai import AzureOpenAI

# --------------------------
# Load environment
# --------------------------
load_dotenv()

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = "2024-12-01-preview"
AZURE_OPENAI_DEPLOYMENT = "gpt-5.2-chat-3"


PIPELINE_XLSX = "pipeline_jobs_report.xlsx"
# SHEET_NAME = os.getenv("SHEET_NAME") or None  # None -> first sheet


if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
    print("❌ Missing Azure OpenAI configuration in .env (endpoint/key/deployment).")
    sys.exit(1)

# --------------------------
# Azure OpenAI client
# --------------------------
client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version=AZURE_OPENAI_API_VERSION,
)

# --------------------------
# Load pipeline.xlsx
# --------------------------
def load_pipeline_df() -> pd.DataFrame:
    """
    Reads the Excel file into a DataFrame.
    Assumes columns like: Job ID, Job Name, Stage, Status, Duration (sec), Failure Reason, Ref, Commit SHA, etc.
    """
    df = pd.read_excel(PIPELINE_XLSX, engine="openpyxl")
    # Normalize column names for tool functions
    df.columns = [c.strip() for c in df.columns] #removes the extra spces
    return df

DF = load_pipeline_df()

# --------------------------
# Tool functions (operate on DF)
# --------------------------
def list_failed_jobs(limit: int = 10) -> Dict[str, Any]:
    """Return top N failed jobs with key columns."""
    failed = DF[DF["Status"].str.lower() == "failed"] if "Status" in DF.columns else DF
    cols = [c for c in ["Job ID", "Job Name", "Stage", "Status", "Duration (sec)", "Failure Reason", "Ref", "Job Triggered By (name)", "Commit SHA"] if c in DF.columns]
    out = failed[cols].head(limit) #limit rows (head(limit))
    return {"rows": out.to_dict(orient="records"), "count": int(out.shape[0])}

def job_details(job_id: str) -> Dict[str, Any]:
    """Return a specific job by Job ID."""
    if "Job ID" not in DF.columns:
        return {"error": "Column 'Job ID' not found."}
    row = DF[DF["Job ID"].astype(str) == str(job_id)]
    if row.empty:
        return {"error": f"No job found with Job ID={job_id}"}
    return {"row": row.to_dict(orient="records")[0]} #DF to Dict Example: [{"JobID": 123, "Status": "Running"}]

def filter_jobs(ref: Optional[str] = None, stage: Optional[str] = None, status: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """Filter jobs by Ref (branch/tag), Stage, Status; returns top N rows."""
    df = DF.copy()
    if ref and "Ref (Branch/Tag)" in df.columns:
        df = df[df["Ref (Branch/Tag)"].astype(str).str.contains(str(ref), case=False, na=False)]
    if stage and "Stage" in df.columns:
        df = df[df["Stage"].astype(str).str.contains(str(stage), case=False, na=False)]
    if status and "Status" in df.columns:
        df = df[df["Status"].astype(str).str.contains(str(status), case=False, na=False)]
    cols = [c for c in ["Job ID", "Job Name", "Stage", "Status", "Duration (sec)", "Failure Reason", "Ref (Branch/Tag)", "Commit SHA"] if c in df.columns]
    out = df[cols].head(limit)
    return {"rows": out.to_dict(orient="records"), "count": int(out.shape[0])}
    #This filters are like AND condtion. based on multiple inputs it will filter and give the output.
    
def failure_breakdown() -> Dict[str, Any]:
    """Group by Failure Reason and count rows."""
    if "Failure Reason" not in DF.columns:
        return {"error": "Column 'Failure Reason' not found."}
    grp = DF.groupby("Failure Reason").size().reset_index(name="count").sort_values("count", ascending=False)
    return {"rows": grp.to_dict(orient="records"), "count": int(grp.shape[0])}

# --------------------------
# Tool definitions (JSON schema for function calling)
# --------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_failed_jobs",
            "description": "Return top N failed pipeline jobs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max number of rows to return", "default": 10}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "job_details",
            "description": "Return details for a specific Job ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID to look up"},
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "filter_jobs",
            "description": "Filter jobs by branch/tag (Ref), stage, and status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "Branch or tag substring"},
                    "stage": {"type": "string", "description": "Stage substring"},
                    "status": {"type": "string", "description": "Status substring"},
                    "limit": {"type": "integer", "description": "Max number of rows to return", "default": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "failure_breakdown",
            "description": "Show counts per failure reason across the spreadsheet.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# Map tool names to Python functions
AVAILABLE_FUNCS = {
    "list_failed_jobs": list_failed_jobs,
    "job_details": job_details,
    "filter_jobs": filter_jobs,
    "failure_breakdown": failure_breakdown,
}

SYSTEM_PROMPT = (
    "You are a CI/CD analytics assistant for pipeline jobs. "
    "Use the provided tools/functions to query the spreadsheet when needed. "
    "When returning tabular results, be concise. Summarize key insights. "
    "If the spreadsheet lacks data to answer fully, say what else is needed."
)

def pretty_rows(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "(no rows)"
    headers = list(rows[0].keys())
    table = tabulate(rows, headers=headers, tablefmt="github")
    return table

def run_agent():
    print("✅ Agent ready. Ask me about your pipeline (e.g., 'show last 10 failed jobs', 'details for Job ID 12345', 'filter by branch feature/login')")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        user_input = input("\nYou > ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Bye! 👋")
            break

        messages.append({"role": "user", "content": user_input})

        # First call: let the model decide whether to call a tool
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        
        assistant_msg = resp.choices[0].message
        tool_calls = getattr(assistant_msg, "tool_calls", None)


        if tool_calls:
            # Handle each tool call; append its result as a "tool" message
            messages.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [tc.model_dump() for tc in tool_calls],  # preserve ids & function payload
            })

            for tc in tool_calls:
                func_name = tc.function.name
                func_args_json = tc.function.arguments or "{}"
                try:
                    func_args = json.loads(func_args_json)
                except json.JSONDecodeError:
                    func_args = {}

                py_func = AVAILABLE_FUNCS.get(func_name)
                result = {}
                try:
                    result = py_func(**func_args) if py_func else {"error": f"unknown function {func_name}"}
                except Exception as e:
                    result = {"error": str(e)}

                # Append the tool result back to the conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": func_name,
                    "content": json.dumps(result),
                })

            # Second call: get the final answer that uses the tool outputs
            final = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=messages,
            )
            answer = final.choices[0].message.content
            # Try to beautify if the assistant responds with embedded tables
            try:
                parsed = json.loads(messages[-1]["content"])
                if "rows" in parsed:
                    print(pretty_rows(parsed["rows"]))
                    print("\n" + (answer or ""))
                else:
                    print(answer or "")
            except Exception:
                print(answer or "")
        else:
            # No tool needed; just print the assistant's reply
            # print(choice.message.content or "")
            
            messages.append({"role": "assistant", "content": assistant_msg.content or ""})
            print(assistant_msg.content or "🤖 (no response)")



if __name__ == "__main__":
    run_agent()
