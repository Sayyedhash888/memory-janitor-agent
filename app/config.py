import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")  # Gemini API key only

@dataclass
class AgentConfig:
    # Reads model from environment GEMINI_MODEL. Default gemini-2.5-flash.
    model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    mcp_server_port: int = 8090
    max_iterations: int = 3
    pii_redaction_enabled: bool = True
    injection_detection_enabled: bool = True
    # HITL gate: both Auditor scores must be >= this threshold to auto-approve.
    # Set HITL_SCORE_THRESHOLD=9.5 in .env to guarantee the gate fires during demos.
    hitl_score_threshold: float = float(os.getenv("HITL_SCORE_THRESHOLD", "7.0"))

config = AgentConfig()
