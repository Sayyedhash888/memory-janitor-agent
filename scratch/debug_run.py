import json
import os
import sys
import asyncio
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Ensure app is in path
sys.path.append("d:/Vibe Codding/Project/adk-workspace/memory-janitor-agent")

# Set dummy environment variable
os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project"

from app.agent import root_agent

def main():
    session_service = InMemorySessionService()
    session = session_service.create_session_sync(user_id="test_user", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    input_data = {
        "log_content": "System: Initializing database connection.\nUser: Connect to db.\nAgent: Connected successfully.",
        "filepath": "Result/memory_graph.json"
    }

    message = types.Content(
        role="user", parts=[types.Part.from_text(text=json.dumps(input_data))]
    )

    print("Running memory janitor workflow...")
    events = list(
        runner.run(
            new_message=message,
            user_id="test_user",
            session_id=session.id,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        )
    )

    print(f"Workflow completed with {len(events)} events.")
    for e in events:
        print(f"Event output: {e.output}")

if __name__ == "__main__":
    main()
