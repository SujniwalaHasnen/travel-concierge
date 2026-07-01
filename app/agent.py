# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
import json
import sys
import datetime
from typing import AsyncGenerator

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.models import Gemini
from google.adk.workflow import Workflow, START
from google.adk.tools import AgentTool
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.genai import types

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from app.config import config

# Set Vertex AI usage to False to ensure Gemini API Key works
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

# Initialize Model
shared_model = Gemini(model=config.model)

# Define MCP connection params to local server
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER_PATH = os.path.join(CURRENT_DIR, "mcp_server.py")

mcp_connection = StdioConnectionParams(
    server_params=StdioServerParameters(
        command="uv",
        args=["run", "python", MCP_SERVER_PATH],
    )
)
mcp_toolset = McpToolset(connection_params=mcp_connection)

# Define sub-agents
travel_planner = LlmAgent(
    name="travel_planner",
    model=shared_model,
    instruction="""You are an expert travel planner sub-agent.
Your goal is to create a detailed day-by-day travel itinerary and suggest flight/hotel options based on the user's destination, dates, budget, and preferences.
Use the MCP tools: 'get_destination_weather' to check the weather and 'search_flights_hotels' to compare flight and hotel options.
Keep the itinerary clean, realistic, and highly structured. Always return a detailed text markdown itinerary.""",
    description="Generates daily travel itineraries, flight/hotel comparison, and weather insights.",
    tools=[mcp_toolset]
)

visa_assistant = LlmAgent(
    name="visa_assistant",
    model=shared_model,
    instruction="""You are an expert visa and document sub-agent.
Your goal is to provide a complete document checklist, visa requirements, passport validity rules, and application deadlines for the trip.
Use the MCP tool: 'check_visa_requirements' to get requirements and documentation details based on passport country and destination.
Verify requirements based on the destination and the user's passport (default passport country: India, unless specified).
Keep deadlines clear and list exactly what documents are needed.""",
    description="Provides visa requirements, document checklists, and application deadlines.",
    tools=[mcp_toolset]
)

orchestrator = LlmAgent(
    name="orchestrator",
    model=shared_model,
    instruction="""You are the main Travel Concierge Orchestrator.
Your job is to coordinate travel planning by delegating specific tasks to your sub-agents:
1. Use 'travel_planner' to generate a day-by-day itinerary, suggest flights/hotels, and check the weather.
2. Use 'visa_assistant' to check visa requirements and compile the required document checklist.

Analyze the user's request. Identify the destination, dates, budget, and preferences.
Delegate to both sub-agents. You MUST call both travel_planner and visa_assistant to gather all necessary details.
Once you receive their reports, synthesize them into a beautiful, comprehensive travel package containing:
- Destination, dates, budget summary.
- The detailed day-by-day itinerary from travel_planner.
- Flights/hotels comparison and weather overview.
- The visa/document checklist and deadlines from visa_assistant.

Current query/context: {user_query}
""",
    tools=[AgentTool(travel_planner), AgentTool(visa_assistant)],
)

# Utility function to extract text from content
def extract_text(content) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if hasattr(content, "parts") and content.parts:
        parts_text = []
        for p in content.parts:
            if hasattr(p, "text") and p.text:
                parts_text.append(p.text)
        return "".join(parts_text)
    if hasattr(content, "text"):
        return str(content.text)
    return str(content)

# Security Helpers

INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "system prompt",
    "override",
    "jailbreak",
    "bypass security",
    "do anything now",
    "dan mode"
]

BLACKLISTED_DESTINATIONS = ["north korea", "syria", "yemen"]
MAX_BUDGET = 50000

def detect_injection(text: str) -> bool:
    lowered = text.lower()
    for kw in INJECTION_KEYWORDS:
        if kw in lowered:
            return True
    return False

def scrub_pii(text: str) -> tuple[str, list[str]]:
    scrubbed = text
    scrubbed_types = []
    
    # Email Regex
    email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    if email_pattern.search(scrubbed):
        scrubbed = email_pattern.sub("[REDACTED_EMAIL]", scrubbed)
        scrubbed_types.append("Email")
        
    # Phone Regex
    phone_pattern = re.compile(r'\b(?:\+?\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b')
    if phone_pattern.search(scrubbed):
        scrubbed = phone_pattern.sub("[REDACTED_PHONE]", scrubbed)
        scrubbed_types.append("Phone Number")
        
    # Passport Regex (alphanumeric string of length 8 or 9)
    passport_pattern = re.compile(r'\b[A-Z0-9]{8,9}\b')
    if passport_pattern.search(scrubbed):
        scrubbed = passport_pattern.sub("[REDACTED_PASSPORT]", scrubbed)
        scrubbed_types.append("Passport Number")
        
    return scrubbed, scrubbed_types

def check_domain_rules(text: str) -> tuple[bool, str]:
    lowered = text.lower()
    for country in BLACKLISTED_DESTINATIONS:
        if country in lowered:
            return False, f"Destination '{country}' is in a blacklisted travel advisory zone."
            
    budget_match = re.search(r'(?:budget|cost)\s*(?:of|is|around)?\s*\$?\s*(\d{5,8})', lowered)
    if budget_match:
        budget_val = int(budget_match.group(1))
        if budget_val > MAX_BUDGET:
            return False, f"Requested budget ${budget_val} exceeds the travel policy limit of ${MAX_BUDGET}."
            
    return True, ""

def write_audit_log(severity: str, event_type: str, query: str, details: dict):
    log_entry = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "severity": severity,
        "event_type": event_type,
        "query_scrubbed": query,
        "details": details
    }
    sys.stderr.write(json.dumps(log_entry) + "\n")
    sys.stderr.flush()

# Workflow Function Nodes

def security_checkpoint(ctx: Context, node_input: types.Content) -> Event:
    """Security Checkpoint Node. Evaluates prompts for injection and scrubs PII."""
    query_text = extract_text(node_input)
    
    # 1. Prompt Injection Check
    if detect_injection(query_text):
        write_audit_log(
            severity="CRITICAL",
            event_type="PROMPT_INJECTION_DETECTED",
            query="[REDACTED due to injection risk]",
            details={"original_length": len(query_text)}
        )
        return Event(output="Prompt injection attempt detected.", route="SECURITY_EVENT")
        
    # 2. PII Scrubbing
    scrubbed_query, pii_types = scrub_pii(query_text)
    if pii_types:
        write_audit_log(
            severity="WARNING",
            event_type="PII_REDACTED",
            query=scrubbed_query,
            details={"redacted_types": pii_types}
        )
    
    # 3. Domain Rules Check
    passed_rules, rule_error = check_domain_rules(scrubbed_query)
    if not passed_rules:
        write_audit_log(
            severity="WARNING",
            event_type="DOMAIN_RULE_VIOLATION",
            query=scrubbed_query,
            details={"violation": rule_error}
        )
        return Event(output=rule_error, route="SECURITY_EVENT")
        
    # All checks passed!
    write_audit_log(
        severity="INFO",
        event_type="CLEAN_REQUEST",
        query=scrubbed_query,
        details={"pii_scrubbed": len(pii_types) > 0}
    )
    
    # Update state with the scrubbed query
    ctx.state["user_query"] = scrubbed_query
    ctx.state["review_count"] = ctx.state.get("review_count", 0)
    
    return Event(output=scrubbed_query, route="CLEAN")

def security_error(node_input: str):
    """Fallback node for security violations."""
    msg = f"Security block: {node_input}"
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=msg)]))
    yield Event(output=msg)

async def review_itinerary(ctx: Context, node_input: str) -> AsyncGenerator[Event | RequestInput, None]:
    """Human-in-the-loop review node. Pauses execution for user approval."""
    orchestrator_text = extract_text(node_input)
    ctx.state["itinerary_proposal"] = orchestrator_text
    
    review_id = f"review_trip_{ctx.state.get('review_count', 0)}"
    
    if not ctx.resume_inputs or review_id not in ctx.resume_inputs:
        msg = (
            f"Here is your proposed travel plan:\n\n{orchestrator_text}\n\n"
            f"Do you approve this plan, or would you like to make revisions?\n"
            f"(Reply with 'approve' to finalize, or describe your desired changes)."
        )
        yield RequestInput(
            interrupt_id=review_id,
            message=msg
        )
        return
        
    user_feedback = ctx.resume_inputs[review_id]
    ctx.state["review_count"] = ctx.state.get("review_count", 0) + 1
    
    if "approve" in user_feedback.lower() or "yes" in user_feedback.lower():
        yield Event(output=orchestrator_text, route="approve")
    else:
        # User requested revisions: update user_query and route back to orchestrator
        ctx.state["user_query"] = f"Revision requested: {user_feedback}. Update the itinerary. Previous itinerary: {orchestrator_text}"
        yield Event(output=user_feedback, route="revise")

def final_output(node_input: str):
    """Finalizes output and displays it to the user."""
    msg = f"Trip itinerary finalized! 🎉\n\n{node_input}"
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=msg)]))
    yield Event(output=node_input)

# Define edges
edges = [
    (START, security_checkpoint),
    (security_checkpoint, {"SECURITY_EVENT": security_error, "CLEAN": orchestrator}),
    (orchestrator, review_itinerary),
    (review_itinerary, {"revise": orchestrator, "approve": final_output}),
]

# Root Workflow Agent
root_agent = Workflow(
    name="travel_concierge",
    edges=edges,
)

# App Container
app = App(
    name="app",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
)
