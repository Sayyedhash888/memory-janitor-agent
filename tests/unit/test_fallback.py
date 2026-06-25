import json
import pytest
import asyncio
from unittest.mock import MagicMock, patch
from app.agent import load_instructions, ensure_valid_json, CompressedLog, DynamicModel
from google.adk.models.llm_request import LlmRequest
from google.genai import types

def test_load_instructions() -> None:
    # Verify we can load gemini.md
    gemini_inst = load_instructions("gemini.md")
    assert "specialized agent designed to clean" in gemini_inst

    # Verify we can load ollama.md
    ollama_inst = load_instructions("ollama.md")
    assert "strict data-processing agent" in ollama_inst

def test_ensure_valid_json_normalizer() -> None:
    # Mock schema properties representation
    schema = {
        "properties": {
            "summary": {"type": "string"},
            "critical_facts": {"type": "array", "items": {"type": "string"}},
            "code_structures": {"type": "array", "items": {"type": "string"}},
            "memory_graph": {"type": "string"}
        }
    }

    # Test Case 1: Ideal flat JSON
    text1 = json.dumps({
        "summary": "This is a summary",
        "critical_facts": ["fact 1", "fact 2"],
        "code_structures": ["class A:"],
        "memory_graph": '{"key": "value"}'
    })
    res1 = ensure_valid_json(text1, schema)
    data1 = json.loads(res1)
    assert data1["summary"] == "This is a summary"
    assert data1["critical_facts"] == ["fact 1", "fact 2"]
    assert data1["code_structures"] == ["class A:"]
    assert data1["memory_graph"] == '{"key": "value"}'

    # Test Case 2: Wrapped in 'graph_data' key
    text2 = json.dumps({
        "graph_data": {
            "summary": "Nested summary",
            "critical_facts": ["fact 3"],
            "code_structures": [],
            "memory_graph": "{}"
        }
    })
    res2 = ensure_valid_json(text2, schema)
    data2 = json.loads(res2)
    assert data2["summary"] == "Nested summary"
    assert data2["critical_facts"] == ["fact 3"]

    # Test Case 3: Missing fields (should get normalized defaults)
    text3 = json.dumps({
        "summary": "Only summary"
    })
    res3 = ensure_valid_json(text3, schema)
    data3 = json.loads(res3)
    assert data3["summary"] == "Only summary"
    assert data3["critical_facts"] == []
    assert data3["code_structures"] == []
    assert data3["memory_graph"] == ""

    # Test Case 4: Field type mismatch (critical_facts is string, should become list)
    text4 = json.dumps({
        "summary": "Mismatch",
        "critical_facts": "fact 4 string",
        "code_structures": None,
        "memory_graph": {"nested": "dict"}
    })
    res4 = ensure_valid_json(text4, schema)
    data4 = json.loads(res4)
    assert data4["critical_facts"] == ["fact 4 string"]
    assert data4["code_structures"] == []
    assert data4["memory_graph"] == '{"nested": "dict"}'

    # Test Case 5: DeepSeek nested memory_graph
    text5 = json.dumps({
        "memory_graph": {
            "summary": "DeepSeek nested summary",
            "critical_facts": ["nested fact 1"],
            "code_structures": ["class Nested:"],
            "memory_graph": {"actual_key": "actual_val"}
        }
    })
    res5 = ensure_valid_json(text5, schema)
    data5 = json.loads(res5)
    assert data5["summary"] == "DeepSeek nested summary"
    assert data5["critical_facts"] == ["nested fact 1"]
    assert data5["code_structures"] == ["class Nested:"]
    assert data5["memory_graph"] == '{"actual_key": "actual_val"}'

    # Test Case 6: Nested dictionary in memory_graph without nested memory_graph key
    text6 = json.dumps({
        "memory_graph": {
            "summary": "DeepSeek nested summary 2",
            "critical_facts": ["nested fact 2"],
            "graph_info": "some graph data"
        }
    })
    res6 = ensure_valid_json(text6, schema)
    data6 = json.loads(res6)
    assert data6["summary"] == "DeepSeek nested summary 2"
    assert data6["critical_facts"] == ["nested fact 2"]
    assert data6["memory_graph"] == '{"graph_info": "some graph data"}'


@pytest.mark.asyncio
async def test_dynamic_model_fallback() -> None:
    # Mock Gemini (cloud) generator to raise an error
    async def mock_generate_content_async(*args, **kwargs):
        raise Exception("API Quota Exceeded")
        yield  # Make it a generator

    with patch("app.agent.Gemini") as mock_gemini_class, \
         patch("openai.OpenAI") as mock_openai_class:

        # Set up Gemini mock
        mock_gemini_instance = MagicMock()
        mock_gemini_instance.generate_content_async = mock_generate_content_async
        mock_gemini_class.return_value = mock_gemini_instance

        # Set up OpenAI mock
        mock_openai_instance = MagicMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "summary": "Ollama summary",
            "critical_facts": ["Ollama fact"],
            "code_structures": ["class Ollama:"],
            "memory_graph": "{}"
        })
        mock_choice.message.tool_calls = None
        mock_completion.choices = [mock_choice]
        mock_openai_instance.chat.completions.create.return_value = mock_completion
        mock_openai_class.return_value = mock_openai_instance

        # Instantiate DynamicModel with agent_name="janitor_agent"
        model = DynamicModel(model="gemini-2.5-flash", agent_name="janitor_agent")

        # Create a mock LlmRequest
        req = LlmRequest(
            contents=[types.Content(role="user", parts=[types.Part.from_text(text="test")])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "properties": {
                        "summary": {"type": "string"},
                        "critical_facts": {"type": "array", "items": {"type": "string"}},
                        "code_structures": {"type": "array", "items": {"type": "string"}},
                        "memory_graph": {"type": "string"}
                    }
                }
            )
        )

        # Run generator
        responses = []
        async for r in model.generate_content_async(req, stream=False):
            responses.append(r)

        # Assertions
        assert len(responses) == 1
        response_text = responses[0].content.parts[0].text
        data = json.loads(response_text)
        assert data["summary"] == "Ollama summary"
        assert data["critical_facts"] == ["Ollama fact"]

        # Verify instruction was updated to ollama.md
        assert "strict data-processing agent" in req.config.system_instruction


@pytest.mark.asyncio
async def test_dynamic_model_timeout() -> None:
    # Mock Gemini (cloud) generator to sleep and timeout
    async def mock_generate_content_async(*args, **kwargs):
        await asyncio.sleep(10.0)  # Will trigger the 5-second timeout
        yield  # Make it a generator

    with patch("app.agent.Gemini") as mock_gemini_class, \
         patch("openai.OpenAI") as mock_openai_class:

        mock_gemini_instance = MagicMock()
        mock_gemini_instance.generate_content_async = mock_generate_content_async
        mock_gemini_class.return_value = mock_gemini_instance

        mock_openai_instance = MagicMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "summary": "Timeout summary",
            "critical_facts": ["Timeout fact"],
            "code_structures": ["class Timeout:"],
            "memory_graph": "{}"
        })
        mock_choice.message.tool_calls = None
        mock_completion.choices = [mock_choice]
        mock_openai_instance.chat.completions.create.return_value = mock_completion
        mock_openai_class.return_value = mock_openai_instance

        model = DynamicModel(model="gemini-2.5-flash", agent_name="janitor_agent")

        req = LlmRequest(
            contents=[types.Content(role="user", parts=[types.Part.from_text(text="test")])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "properties": {
                        "summary": {"type": "string"},
                        "critical_facts": {"type": "array", "items": {"type": "string"}},
                        "code_structures": {"type": "array", "items": {"type": "string"}},
                        "memory_graph": {"type": "string"}
                    }
                }
            )
        )

        # Set a short timeout (e.g. 0.1s) for the test to run quickly,
        # by temporarily patching the timeout to 0.1s
        with patch("asyncio.timeout", lambda t: asyncio.timeout(0.1)):
            responses = []
            async for r in model.generate_content_async(req, stream=False):
                responses.append(r)

        assert len(responses) == 1
        response_text = responses[0].content.parts[0].text
        data = json.loads(response_text)
        assert data["summary"] == "Timeout summary"
        assert "strict data-processing agent" in req.config.system_instruction


@pytest.mark.asyncio
async def test_dynamic_model_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    # Set the model environment variable to deepseek
    monkeypatch.setenv("API_KEY", "openrouter-secret-key")
    monkeypatch.setenv("API_BASE_URL", "https://openrouter.ai/api/v1")

    from app.agent import DynamicModel
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types

    with patch("openai.OpenAI") as mock_openai_class:
        mock_openai_instance = MagicMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "summary": "Deepseek summary",
            "critical_facts": ["Deepseek fact"],
            "code_structures": [],
            "memory_graph": "{}"
        })
        mock_choice.message.tool_calls = None
        mock_completion.choices = [mock_choice]
        mock_openai_instance.chat.completions.create.return_value = mock_completion
        mock_openai_class.return_value = mock_openai_instance

        # Instantiate DynamicModel with a non-gemini model
        model = DynamicModel(model="deepseek/deepseek-chat", agent_name="janitor_agent")

        req = LlmRequest(
            contents=[types.Content(role="user", parts=[types.Part.from_text(text="test")])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "properties": {
                        "summary": {"type": "string"},
                        "critical_facts": {"type": "array", "items": {"type": "string"}},
                        "code_structures": {"type": "array", "items": {"type": "string"}},
                        "memory_graph": {"type": "string"}
                    }
                }
            )
        )

        responses = []
        async for r in model.generate_content_async(req, stream=False):
            responses.append(r)

        # Assertions
        assert len(responses) == 1
        response_text = responses[0].content.parts[0].text
        data = json.loads(response_text)
        assert data["summary"] == "Deepseek summary"

        # Verify OpenAI was initialized with OpenRouter's URL and API_KEY
        mock_openai_class.assert_called_once_with(
            base_url="https://openrouter.ai/api/v1",
            api_key="openrouter-secret-key"
        )


@pytest.mark.asyncio
async def test_dynamic_model_set_model_response_normalization() -> None:
    from app.agent import DynamicModel
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types

    with patch("openai.OpenAI") as mock_openai_class:
        mock_openai_instance = MagicMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = ""
        
        # Mock a tool call to set_model_response
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_set_response"
        mock_tool_call.function.name = "set_model_response"
        # Nested memory_graph, missing summary/critical_facts/code_structures
        mock_tool_call.function.arguments = json.dumps({
            "memory_graph": {
                "contact_email": "hello@world.com"
            }
        })
        mock_choice.message.tool_calls = [mock_tool_call]
        
        mock_completion.choices = [mock_choice]
        mock_openai_instance.chat.completions.create.return_value = mock_completion
        mock_openai_class.return_value = mock_openai_instance

        # Create a mock tool with name 'set_model_response' and output_schema
        mock_tool = MagicMock()
        mock_tool.name = "set_model_response"
        mock_tool.output_schema = CompressedLog

        model = DynamicModel(model="openai/gpt-4o-mini", agent_name="janitor_agent")

        req = LlmRequest(
            contents=[types.Content(role="user", parts=[types.Part.from_text(text="test")])],
            config=types.GenerateContentConfig(
                tools=[mock_tool]
            )
        )

        responses = []
        async for r in model.generate_content_async(req, stream=False):
            responses.append(r)

        # Assertions
        assert len(responses) == 1
        parts = responses[0].content.parts
        assert len(parts) == 1
        fc = parts[0].function_call
        assert fc is not None
        assert fc.name == "set_model_response"
        assert fc.args["summary"] == ""
        assert fc.args["critical_facts"] == []
        assert fc.args["code_structures"] == []
        assert json.loads(fc.args["memory_graph"]) == {"contact_email": "hello@world.com"}


@pytest.mark.asyncio
async def test_dynamic_model_set_model_response_streaming_normalization() -> None:
    from app.agent import DynamicModel
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types

    with patch("openai.OpenAI") as mock_openai_class:
        mock_openai_instance = MagicMock()
        
        # Mock streaming chunks
        tc1 = MagicMock()
        tc1.index = 0
        tc1.id = "call_set_response"
        tc1.function.name = "set_model_response"
        tc1.function.arguments = '{"memory_graph": '
        
        mock_chunk_1 = MagicMock()
        mock_choice_1 = MagicMock()
        mock_delta_1 = MagicMock()
        mock_delta_1.content = None
        mock_delta_1.tool_calls = [tc1]
        mock_choice_1.delta = mock_delta_1
        mock_chunk_1.choices = [mock_choice_1]

        tc2 = MagicMock()
        tc2.index = 0
        tc2.id = None
        tc2.function.name = None
        tc2.function.arguments = '{"contact_email": "hello@world.com"}}'

        mock_chunk_2 = MagicMock()
        mock_choice_2 = MagicMock()
        mock_delta_2 = MagicMock()
        mock_delta_2.content = None
        mock_delta_2.tool_calls = [tc2]
        mock_choice_2.delta = mock_delta_2
        mock_chunk_2.choices = [mock_choice_2]

        mock_openai_instance.chat.completions.create.return_value = [mock_chunk_1, mock_chunk_2]
        mock_openai_class.return_value = mock_openai_instance

        # Create a mock tool with name 'set_model_response' and output_schema
        mock_tool = MagicMock()
        mock_tool.name = "set_model_response"
        mock_tool.output_schema = CompressedLog

        model = DynamicModel(model="openai/gpt-4o-mini", agent_name="janitor_agent")

        req = LlmRequest(
            contents=[types.Content(role="user", parts=[types.Part.from_text(text="test")])],
            config=types.GenerateContentConfig(
                tools=[mock_tool]
            )
        )

        responses = []
        async for r in model.generate_content_async(req, stream=True):
            responses.append(r)

        # The last response (turn_complete=True) should contain the normalized arguments
        final_response = responses[-1]
        assert final_response.turn_complete is True
        parts = final_response.content.parts
        assert len(parts) == 1
        fc = parts[0].function_call
        assert fc is not None
        assert fc.name == "set_model_response"
        assert fc.args["summary"] == ""
        assert fc.args["critical_facts"] == []
        assert fc.args["code_structures"] == []
        assert json.loads(fc.args["memory_graph"]) == {"contact_email": "hello@world.com"}


def test_normalize_llm_response_orchestrator_and_auditor() -> None:
    from app.agent import normalize_llm_response, AuditReport, OrchestratorOutput, CompressedLog
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    # Test Case 1: Auditor agent tool call normalization
    auditor_response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        id="call_audit",
                        name="set_model_response",
                        args={
                            "reasoning": "This is good reasoning",
                            # Missing context_retention_score, compression_ratio_score, status
                        }
                    )
                )
            ]
        ),
        partial=False,
        turn_complete=True
    )
    normalized_auditor = normalize_llm_response(auditor_response, "auditor_agent")
    fc_auditor = normalized_auditor.content.parts[0].function_call
    assert fc_auditor.args["reasoning"] == "This is good reasoning"
    assert fc_auditor.args["context_retention_score"] == 0.0
    assert fc_auditor.args["compression_ratio_score"] == 0.0
    assert fc_auditor.args["status"] == ""

    # Test Case 2: Orchestrator text response (JSON text) normalization
    orchestrator_response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    text=json.dumps({
                        "message": "Pipeline completed successfully.",
                        "final_status": "Approved",
                        # Nested compressed_log or audit_report missing fields
                        "compressed_log": {
                            "memory_graph": {
                                "contact_email": "test@domain.com"
                            }
                        },
                        "audit_report": {
                            "status": "Approved"
                        }
                    })
                )
            ]
        ),
        partial=False,
        turn_complete=True
    )
    normalized_orch = normalize_llm_response(orchestrator_response, "orchestrator")
    text_orch = normalized_orch.content.parts[0].text
    data_orch = json.loads(text_orch)
    assert data_orch["message"] == "Pipeline completed successfully."
    assert data_orch["final_status"] == "Approved"
    assert isinstance(data_orch["compressed_log"], dict)
    # The nested compressed_log.memory_graph should be serialized to a string
    assert isinstance(data_orch["compressed_log"]["memory_graph"], str)
    assert "test@domain.com" in data_orch["compressed_log"]["memory_graph"]
    # The other missing CompressedLog fields should be normalized to defaults
    assert data_orch["compressed_log"]["summary"] == ""
    assert data_orch["compressed_log"]["critical_facts"] == []


def test_normalize_flat_to_nested() -> None:
    from app.agent import normalize_dict, OrchestratorOutput

    flat_data = {
        "summary": "Flat summary",
        "critical_facts": ["fact A"],
        "code_structures": ["def func(): pass"],
        "memory_graph": {"email": "hello@world.com"},
        "context_retention_score": 9.5,
        "compression_ratio_score": 8.0,
        "reasoning": "Excellent job",
        "status": "Approved",
        "message": "Orchestrator response message"
    }

    normalized = normalize_dict(flat_data, OrchestratorOutput)

    # Verify nested structure was extracted
    assert normalized["compressed_log"]["summary"] == "Flat summary"
    assert normalized["compressed_log"]["critical_facts"] == ["fact A"]
    assert normalized["compressed_log"]["code_structures"] == ["def func(): pass"]
    # memory_graph should be serialized as a JSON string
    assert "email" in normalized["compressed_log"]["memory_graph"]

    assert normalized["audit_report"]["context_retention_score"] == 9.5
    assert normalized["audit_report"]["compression_ratio_score"] == 8.0
    assert normalized["audit_report"]["reasoning"] == "Excellent job"
    assert normalized["audit_report"]["status"] == "Approved"

    assert normalized["final_status"] == "Approved"  # mapped from status
    assert normalized["message"] == "Orchestrator response message"


def test_save_memory_auto_increment(tmp_path) -> None:
    from app.agent import save_memory
    from google.adk.agents.context import Context
    import os
    import json
    from unittest.mock import MagicMock, patch

    # Create dummy Result folder and file inside tmp_path
    result_dir = tmp_path / "Result"
    result_dir.mkdir()
    
    # original file
    original_file = result_dir / "memory_graph.json"
    original_file.write_text("{}", encoding="utf-8")
    
    # second conflict
    conflict1 = result_dir / "memory_graph1.json"
    conflict1.write_text("{}", encoding="utf-8")

    # Mock context with target path set to Result/memory_graph.json
    ctx = MagicMock(spec=Context)
    ctx.state = {"filepath": "Result/memory_graph.json"}
    ctx.resume_inputs = {}

    node_input = {
        "compressed_log": {
            "memory_graph": '{"data": "new memory"}'
        }
    }

    # Patch os.path.dirname and os.path.abspath so that result_dir points to our tmp_path/Result
    with patch("app.agent.os.path.abspath") as mock_abs:
        mock_abs.return_value = str(tmp_path / "app" / "agent.py")
        
        res = save_memory(ctx, node_input)
        
        # It should save to memory_graph2.json since memory_graph.json and memory_graph1.json exist
        expected_path = result_dir / "memory_graph2.json"
        assert expected_path.exists()
        assert json.loads(expected_path.read_text(encoding="utf-8")) == {"data": "new memory"}
        assert "Successfully saved" in res


def test_normalize_subagent_tool_calls() -> None:
    from app.agent import normalize_llm_response
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    import json

    # Test Case 1: janitor_agent with legacy 'request' argument
    janitor_response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        id="call_janitor",
                        name="janitor_agent",
                        args={
                            "request": "messy log content"
                        }
                    )
                )
            ]
        ),
        partial=False,
        turn_complete=True
    )
    normalized = normalize_llm_response(janitor_response, "orchestrator")
    fc = normalized.content.parts[0].function_call
    assert fc.args["log_content"] == "messy log content"

    # Test Case 2: auditor_agent with legacy 'request' argument representing JSON string
    auditor_response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        id="call_auditor",
                        name="auditor_agent",
                        args={
                            "request": '{"original_log": "orig log", "compressed_graph": "comp graph"}'
                        }
                    )
                )
            ]
        ),
        partial=False,
        turn_complete=True
    )
    normalized = normalize_llm_response(auditor_response, "orchestrator")
    fc = normalized.content.parts[0].function_call
    assert fc.args["original_log"] == "orig log"
    assert fc.args["compressed_graph"] == "comp graph"






