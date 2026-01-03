#!/usr/bin/env python3
"""
Z.AI Coding CLI - An AI-powered coding assistant
Features: Read files, list directories, run commands, write files
Similar to Claude Code / Gemini CLI
"""

import requests
import json
import sys
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CURL_FILE = os.path.join(SCRIPT_DIR, "curl.txt")
WORKING_DIR = os.getcwd()

# ANSI Color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"

# System prompt that teaches the AI about available tools
SYSTEM_PROMPT = """You are an AI coding assistant with access to the user's file system and terminal.
You can help with coding tasks by reading files, writing code, running commands, and more.

## Available Tools
You can use these tools by outputting special commands in your response:

1. **Read a file:**
   ```tool
   {{"action": "read_file", "path": "path/to/file.py"}}
   ```

2. **List directory contents:**
   ```tool
   {{"action": "list_dir", "path": "path/to/directory"}}
   ```

3. **Run a terminal command:**
   ```tool
   {{"action": "run_command", "command": "python script.py"}}
   ```

4. **Write to a file:**
   ```tool
   {{"action": "write_file", "path": "path/to/file.py", "content": "file content here"}}
   ```

5. **Search for files:**
   ```tool
   {{"action": "search_files", "pattern": "*.py", "path": "."}}
   ```

## Guidelines
- Always explain what you're doing before using a tool
- Use relative paths when possible (relative to the working directory)
- For file writes, show the content you're writing
- Be careful with destructive commands
- After using a tool, wait for the result before continuing

Current working directory: {cwd}
Current date/time: {datetime}
"""

def read_curl_template():
    """Read the curl command template from the file."""
    with open(CURL_FILE, 'r', encoding='utf-8') as f:
        return f.read()

def parse_curl_for_api_info(curl_cmd: str) -> tuple:
    """Parse curl command and extract URL, headers, and base data structure."""
    # Normalize the curl command
    curl_cmd = curl_cmd.replace('\\\r\n', ' ').replace('\\\n', ' ')
    curl_cmd = curl_cmd.replace('\r\n', ' ').replace('\n', ' ')
    curl_cmd = ' '.join(curl_cmd.split())
    
    # Extract URL
    url_match = re.search(r"curl\s+'([^']+)'", curl_cmd)
    if not url_match:
        url_match = re.search(r'curl\s+"([^"]+)"', curl_cmd)
    if not url_match:
        raise ValueError("Could not parse URL from curl command")
    url = url_match.group(1)
    
    # Extract headers
    headers = {}
    header_pattern = r"-H\s+'([^']+)'"
    for match in re.finditer(header_pattern, curl_cmd):
        header = match.group(1)
        if ':' in header:
            key, value = header.split(':', 1)
            headers[key.strip()] = value.strip()
    
    # Extract cookies
    cookies_match = re.search(r"-b\s+'([^']+)'", curl_cmd)
    cookie_str = cookies_match.group(1) if cookies_match else ""
    if cookie_str:
        headers['Cookie'] = cookie_str
    
    # Extract original data payload
    data_match = re.search(r"--data-raw\s+'(\{.+\})'", curl_cmd)
    if not data_match:
        data_match = re.search(r'--data-raw\s+"(\{.+\})"', curl_cmd)
    
    base_data = {}
    if data_match:
        try:
            base_data = json.loads(data_match.group(1))
        except:
            pass
    
    return url, headers, base_data

def build_request_data(base_data: dict, messages: list) -> dict:
    """Build the request data with updated messages."""
    data = base_data.copy()
    data['messages'] = messages
    data['stream'] = True
    
    # Update features
    if 'features' not in data:
        data['features'] = {}
    data['features']['enable_thinking'] = True
    
    # Update timestamps
    now = datetime.now()
    if 'variables' not in data:
        data['variables'] = {}
    data['variables']['{{CURRENT_DATETIME}}'] = now.strftime("%Y-%m-%d %H:%M:%S")
    data['variables']['{{CURRENT_DATE}}'] = now.strftime("%Y-%m-%d")
    data['variables']['{{CURRENT_TIME}}'] = now.strftime("%H:%M:%S")
    data['variables']['{{CURRENT_WEEKDAY}}'] = now.strftime("%A")
    
    return data

def build_messages(conversation_history: list, user_message: str) -> list:
    """Build the messages array for the API request."""
    system_content = SYSTEM_PROMPT.format(
        cwd=WORKING_DIR,
        datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    
    messages = [{"role": "system", "content": system_content}]
    
    for msg in conversation_history:
        messages.append(msg)
    
    messages.append({"role": "user", "content": user_message})
    
    return messages

# ============== TOOL IMPLEMENTATIONS ==============

def tool_read_file(path: str) -> str:
    """Read a file and return its contents."""
    try:
        full_path = os.path.join(WORKING_DIR, path) if not os.path.isabs(path) else path
        if not os.path.exists(full_path):
            return f"Error: File not found: {path}"
        if os.path.isdir(full_path):
            return f"Error: {path} is a directory, not a file"
        
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        if len(content) > 10000:
            content = content[:10000] + "\n... (truncated, file too large)"
        
        return f"Contents of {path}:\n```\n{content}\n```"
    except Exception as e:
        return f"Error reading file: {str(e)}"

def tool_list_dir(path: str = ".") -> str:
    """List directory contents."""
    try:
        full_path = os.path.join(WORKING_DIR, path) if not os.path.isabs(path) else path
        if not os.path.exists(full_path):
            return f"Error: Directory not found: {path}"
        if not os.path.isdir(full_path):
            return f"Error: {path} is not a directory"
        
        items = []
        for item in sorted(os.listdir(full_path)):
            item_path = os.path.join(full_path, item)
            if os.path.isdir(item_path):
                items.append(f"📁 {item}/")
            else:
                size = os.path.getsize(item_path)
                items.append(f"📄 {item} ({size} bytes)")
        
        return f"Contents of {path}:\n" + "\n".join(items[:50])
    except Exception as e:
        return f"Error listing directory: {str(e)}"

def tool_run_command(command: str) -> str:
    """Run a terminal command."""
    try:
        print(f"{Colors.YELLOW}⚡ Running: {command}{Colors.RESET}")
        
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=WORKING_DIR
        )
        
        output = ""
        if result.stdout:
            output += f"STDOUT:\n{result.stdout}"
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        
        output += f"\nExit code: {result.returncode}"
        
        if len(output) > 5000:
            output = output[:5000] + "\n... (truncated)"
        
        return output if output.strip() else "Command completed with no output"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds"
    except Exception as e:
        return f"Error running command: {str(e)}"

def tool_write_file(path: str, content: str) -> str:
    """Write content to a file."""
    try:
        full_path = os.path.join(WORKING_DIR, path) if not os.path.isabs(path) else path
        
        parent_dir = os.path.dirname(full_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        
        print(f"{Colors.YELLOW}📝 Writing to: {path}{Colors.RESET}")
        
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return f"Successfully wrote {len(content)} characters to {path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

def tool_search_files(pattern: str, path: str = ".") -> str:
    """Search for files matching a pattern."""
    try:
        full_path = os.path.join(WORKING_DIR, path) if not os.path.isabs(path) else path
        
        matches = []
        for root, dirs, files in os.walk(full_path):
            dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__', '.venv', 'venv']]
            
            for filename in files:
                if Path(filename).match(pattern):
                    rel_path = os.path.relpath(os.path.join(root, filename), WORKING_DIR)
                    matches.append(rel_path)
            
            if len(matches) >= 50:
                break
        
        if matches:
            return f"Found {len(matches)} files matching '{pattern}':\n" + "\n".join(matches[:50])
        else:
            return f"No files found matching '{pattern}'"
    except Exception as e:
        return f"Error searching files: {str(e)}"

def execute_tool(tool_data: dict) -> str:
    """Execute a tool based on the action."""
    action = tool_data.get('action', '')
    
    if action == 'read_file':
        return tool_read_file(tool_data.get('path', ''))
    elif action == 'list_dir':
        return tool_list_dir(tool_data.get('path', '.'))
    elif action == 'run_command':
        return tool_run_command(tool_data.get('command', ''))
    elif action == 'write_file':
        return tool_write_file(tool_data.get('path', ''), tool_data.get('content', ''))
    elif action == 'search_files':
        return tool_search_files(tool_data.get('pattern', '*'), tool_data.get('path', '.'))
    else:
        return f"Unknown action: {action}"

def extract_and_execute_tools(response_text: str) -> list:
    """Extract tool calls from AI response and execute them."""
    tool_results = []
    
    # Try different patterns for tool blocks
    patterns = [
        r'```(?:tool|tools|json|code)?\s*\n?(.*?)\n?```',
        r'({"\s*action\s*":.*?})'  # Fallback: look for JSON object directly
    ]
    
    matches = []
    for pattern in patterns:
        found = re.findall(pattern, response_text, re.DOTALL)
        # Filter for valid JSON objects that look like tools
        valid_matches = []
        for text in found:
            if '"action"' in text:
                valid_matches.append(text)
        
        if valid_matches:
            matches.extend(valid_matches)
            # If we found matches with a stricter pattern, we might want to stop
            # But overlapping matches could be an issue. 
            # Simple strategy: if we found code blocks, rely on them.
            if pattern.startswith('```'):
                break
    
    for match in matches:
        try:
            # Clean up the JSON string - sometimes AI adds comments or distinct quotes
            json_str = match.strip()
            tool_data = json.loads(json_str)
            
            print(f"\n{Colors.CYAN}🔧 Executing tool: {tool_data.get('action', 'unknown')}{Colors.RESET}")
            result = execute_tool(tool_data)
            tool_results.append({
                'tool': tool_data,
                'result': result
            })
            print(f"{Colors.GREEN}✅ Tool result:{Colors.RESET}")
            result_preview = result[:500] + ('...' if len(result) > 500 else '')
            print(f"{Colors.DIM}{result_preview}{Colors.RESET}")
            
        except json.JSONDecodeError as e:
            print(f"\n{Colors.RED}❌ Failed to parse tool call:{Colors.RESET}")
            print(f"{Colors.DIM}{match}{Colors.RESET}")
            tool_results.append({
                'tool': {'action': 'parse_error'},
                'result': f"Error parsing tool JSON: {e}. Raw content: {match}"
            })
    
    return tool_results

def stream_response(url: str, headers: dict, data: dict) -> tuple:
    """Stream the response in real-time."""
    try:
        response = requests.post(
            url,
            headers=headers,
            json=data,  # Use json= instead of data= for proper encoding
            timeout=120,
            stream=True
        )
        
        if response.status_code != 200:
            print(f"{Colors.RED}❌ Error: API returned status {response.status_code}{Colors.RESET}")
            try:
                print(f"{Colors.DIM}{response.text[:500]}{Colors.RESET}")
            except:
                pass
            return '', []
        
        current_phase = None
        thinking_content = []
        response_content = []
        printed_header = {'thinking': False, 'response': False}
        buffer = ""
        
        for chunk in response.iter_content(chunk_size=1, decode_unicode=True):
            if chunk is None:
                continue
            
            buffer += chunk
            
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                
                if not line or not line.startswith('data:'):
                    continue
                
                json_str = line[5:].strip()
                if json_str == '[DONE]' or not json_str:
                    continue
                
                try:
                    data_obj = json.loads(json_str)
                    
                    if data_obj.get('type') == 'chat:completion':
                        content_data = data_obj.get('data', {})
                        delta_content = content_data.get('delta_content', '')
                        phase = content_data.get('phase', '')
                        
                        if delta_content:
                            if phase != current_phase:
                                if current_phase is not None:
                                    print()
                                current_phase = phase
                            
                            if phase == 'thinking':
                                if not printed_header['thinking']:
                                    print(f"\n{Colors.CYAN}🧠 AI THINKING:{Colors.RESET}")
                                    print("─" * 50)
                                    printed_header['thinking'] = True
                                
                                sys.stdout.write(f"{Colors.GRAY}{delta_content}{Colors.RESET}")
                                sys.stdout.flush()
                                thinking_content.append(delta_content)
                            else:
                                if not printed_header['response']:
                                    if printed_header['thinking']:
                                        print("\n")
                                    print(f"{Colors.GREEN}💬 AI RESPONSE:{Colors.RESET}")
                                    print("─" * 50)
                                    printed_header['response'] = True
                                
                                sys.stdout.write(delta_content)
                                sys.stdout.flush()
                                response_content.append(delta_content)
                                
                except json.JSONDecodeError:
                    continue
        
        print()
        full_response = ''.join(response_content)
        return full_response, extract_and_execute_tools(full_response)
        
    except Exception as e:
        print(f"{Colors.RED}❌ Error: {str(e)}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        return '', []

def print_banner(base_data=None):
    """Print the CLI banner."""
    # ASCII Art for "CAI CLI ZAI"
    banner = f"""{Colors.CYAN}
   ___________    ____  ______    ____   ______  ___    ____
  / ____/   |  /  _/  / ____/   /  _/  /_  __/ /   |  /  _/
 / /   / /| |  / /   / /        / /     / /   / /| |  / /  
/ /___/ ___ |_/ /   / /___    _/ /     / /   / ___ |_/ /   
\\____/_/  |_/___/   \\____/   /___/    /_/   /_/  |_/___/   
    {Colors.RESET}"""
    
    print(banner)
    
    print(f"{Colors.BOLD}{Colors.MAGENTA}  🤖 AI Coding Assistant {Colors.RESET} | {Colors.DIM}Powered by Z.AI (GLM-4.7){Colors.RESET}")
    print(f"  {Colors.DIM}────────────────────────────────────────────────────────{Colors.RESET}")
    
    if base_data:
        # Extract some session info if available
        user_name = base_data.get('variables', {}).get('{{USER_NAME}}', 'Unknown')
        timezone = base_data.get('variables', {}).get('{{CURRENT_TIMEZONE}}', 'Unknown')
        print(f"  👤 User: {Colors.BLUE}{user_name}{Colors.RESET}")
        print(f"  🌍 Zone: {Colors.YELLOW}{timezone}{Colors.RESET}")
    
    print(f"  📂 Path: {Colors.WHITE}{WORKING_DIR}{Colors.RESET}")
    print(f"  {Colors.DIM}────────────────────────────────────────────────────────{Colors.RESET}")
    print(f"""
  {Colors.YELLOW}Commands:{Colors.RESET}
    {Colors.WHITE}/cd <path>{Colors.DIM}   Change directory{Colors.RESET}
    {Colors.WHITE}/ls{Colors.DIM}          List files{Colors.RESET}
    {Colors.WHITE}/clear{Colors.DIM}       Clear context{Colors.RESET}
    {Colors.WHITE}/exit{Colors.DIM}        Quit{Colors.RESET}
""")

def main():
    """Main CLI loop."""
    global WORKING_DIR
    
    # Parse curl config first to get user info
    base_data = None
    url = None
    headers = None
    
    if os.path.exists(CURL_FILE):
        try:
            curl_template = read_curl_template()
            url, headers, base_data = parse_curl_for_api_info(curl_template)
        except Exception as e:
            print(f"{Colors.RED}❌ Error parsing curl.txt: {e}{Colors.RESET}")
            # Continue anyway to show basic banner if possible
    
    print_banner(base_data)
    
    if not url:
        print(f"{Colors.RED}❌ detailed API config missing. Please check {CURL_FILE}{Colors.RESET}")
        return
    
    print(f"{Colors.GREEN}✅ API configured successfully{Colors.RESET}\n")
    
    conversation_history = []
    
    while True:
        try:
            cwd_short = os.path.basename(WORKING_DIR) or WORKING_DIR
            prompt = f"{Colors.BLUE}[{cwd_short}] >{Colors.RESET} "
            user_input = input(prompt).strip()
            
            if not user_input:
                continue
            
            # Handle built-in commands
            if user_input.startswith('/'):
                parts = user_input.split(maxsplit=1)
                cmd = parts[0].lower()
                
                if cmd in ['/exit', '/quit', '/q']:
                    print(f"{Colors.MAGENTA}👋 Goodbye!{Colors.RESET}")
                    break
                elif cmd == '/cd':
                    if len(parts) > 1:
                        new_path = os.path.expanduser(parts[1])
                        if not os.path.isabs(new_path):
                            new_path = os.path.join(WORKING_DIR, new_path)
                        if os.path.isdir(new_path):
                            WORKING_DIR = os.path.abspath(new_path)
                            print(f"{Colors.GREEN}Changed to: {WORKING_DIR}{Colors.RESET}")
                        else:
                            print(f"{Colors.RED}Directory not found: {new_path}{Colors.RESET}")
                    else:
                        print(f"Usage: /cd <path>")
                elif cmd == '/pwd':
                    print(f"{Colors.WHITE}{WORKING_DIR}{Colors.RESET}")
                elif cmd == '/ls':
                    print(tool_list_dir('.'))
                elif cmd == '/clear':
                    conversation_history = []
                    print(f"{Colors.GREEN}Conversation cleared.{Colors.RESET}")
                else:
                    print(f"{Colors.YELLOW}Unknown command: {cmd}{Colors.RESET}")
                continue
            
            # Build messages and request data
            messages = build_messages(conversation_history, user_input)
            request_data = build_request_data(base_data, messages)
            
            # Stream the response
            full_response, tool_results = stream_response(url, headers, request_data)
            
            if full_response:
                conversation_history.append({"role": "user", "content": user_input})
                conversation_history.append({"role": "assistant", "content": full_response})
                
                # If tools were executed, add results and continue
                if tool_results:
                    tool_feedback = "\n\nTool execution results:\n"
                    for tr in tool_results:
                        tool_feedback += f"- {tr['tool'].get('action', 'unknown')}: {tr['result']}\n"
                    
                    conversation_history.append({"role": "user", "content": tool_feedback})
                    
                    print(f"\n{Colors.CYAN}🔄 AI is processing tool results...{Colors.RESET}")
                    
                    followup_messages = conversation_history.copy()
                    followup_data = build_request_data(base_data, followup_messages)
                    followup_response, _ = stream_response(url, headers, followup_data)
                    
                    if followup_response:
                        conversation_history.append({"role": "assistant", "content": followup_response})
            
            print()
            
            # Keep history manageable
            if len(conversation_history) > 20:
                conversation_history = conversation_history[-20:]
                
        except KeyboardInterrupt:
            print(f"\n{Colors.MAGENTA}👋 Goodbye!{Colors.RESET}")
            break
        except Exception as e:
            print(f"{Colors.RED}❌ Error: {e}{Colors.RESET}")
            import traceback
            traceback.print_exc()
            continue

if __name__ == "__main__":
    main()
