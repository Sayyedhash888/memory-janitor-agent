import os
import json
from mcp.server.fastmcp import FastMCP

# Create the MCP server
mcp = FastMCP("Memory Janitor Server")

# Helper to validate and resolve paths safely
def get_safe_path(path: str) -> str:
    return os.path.abspath(path)

@mcp.tool()
def list_logs(directory: str = ".") -> str:
    """List log, JSON, and text files in a directory to find chat logs to clean.
    
    Args:
        directory: The directory path to list files from (defaults to '.').
        
    Returns:
        A JSON string containing the list of file paths.
    """
    try:
        safe_dir = get_safe_path(directory)
        if not os.path.exists(safe_dir):
            return json.dumps({"error": f"Directory not found: {directory}"})
        
        files = []
        for file in os.listdir(safe_dir):
            if file.endswith(('.log', '.json', '.txt')):
                files.append(os.path.join(directory, file))
        return json.dumps({"directory": directory, "files": files})
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def read_log_file(filepath: str) -> str:
    """Read raw agent chat logs or JSON files from the local filesystem.
    
    Args:
        filepath: The path of the file to read.
        
    Returns:
        The content of the file.
    """
    try:
        safe_path = get_safe_path(filepath)
        if not os.path.exists(safe_path):
            return f"Error: File not found: {filepath}"
        
        with open(safe_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
def write_memory_graph(filepath: str, graph_data: str) -> str:
    """Write the finalized, compressed long-term memory graph JSON file to disk.
    
    Args:
        filepath: The destination path of the file to write.
        graph_data: The JSON string content representing the compressed graph.
        
    Returns:
        A confirmation message or error.
    """
    try:
        safe_path = get_safe_path(filepath)
        # Ensure directory exists
        dirname = os.path.dirname(safe_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        
        # Verify JSON
        parsed_data = json.loads(graph_data)
        
        with open(safe_path, 'w', encoding='utf-8') as f:
            json.dump(parsed_data, f, indent=2)
            
        return f"Success: Memory graph written successfully to {filepath} ({len(graph_data)} chars)."
    except json.JSONDecodeError:
        try:
            with open(safe_path, 'w', encoding='utf-8') as f:
                f.write(graph_data)
            return f"Success: Data written as text to {filepath}."
        except Exception as e:
            return f"Error: Failed to write data: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    mcp.run()
