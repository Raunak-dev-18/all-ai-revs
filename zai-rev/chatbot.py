#!/usr/bin/env python3
"""
Z.AI Terminal Chatbot (Real-time Streaming)
A simple terminal chatbot that uses the Z.AI API to generate responses.
Streams AI response and thinking in real-time as they arrive.
"""

import requests
import json
import sys
import os
import re
from datetime import datetime, timezone

# Path to the original curl file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CURL_FILE = os.path.join(SCRIPT_DIR, "curl.txt")


def read_curl_template():
    """Read the curl command template from the file."""
    with open(CURL_FILE, 'r', encoding='utf-8') as f:
        return f.read()


def inject_query(curl_template: str, query: str) -> str:
    """Inject the user's query into the curl template."""
    # Escape special characters for JSON
    escaped_query = json.dumps(query)[1:-1]  # Remove quotes from json.dumps
    
    # Replace the query in the messages array
    pattern = r'("messages":\[\{"role":"user","content":")([^"]*?)("\}\])'
    replacement = rf'\g<1>{escaped_query}\g<3>'
    modified_curl = re.sub(pattern, replacement, curl_template)
    return modified_curl


def parse_curl_command(curl_cmd: str) -> tuple:
    """Parse curl command and extract URL, headers, cookies, and data."""
    # Normalize line breaks and backslashes
    curl_cmd = curl_cmd.replace('\\\r\n', ' ').replace('\\\n', ' ').replace('\\', '')
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
    
    # Extract data - handle the JSON payload at the end
    data_match = re.search(r"--data-raw\s+'(\{.+\})'", curl_cmd)
    if not data_match:
        data_match = re.search(r'--data-raw\s+"(\{.+\})"', curl_cmd)
    data = data_match.group(1) if data_match else ""
    
    return url, headers, data


def print_colored(text: str, color_code: str, end='\n'):
    """Print colored text."""
    print(f"\033[{color_code}m{text}\033[0m", end=end, flush=True)


def print_separator(char='─', length=60):
    """Print a separator line."""
    print(char * length)


def stream_response(query: str):
    """Stream the response in real-time character by character."""
    try:
        # Read and prepare the curl command
        curl_template = read_curl_template()
        curl_cmd = inject_query(curl_template, query)
        url, headers, data = parse_curl_command(curl_cmd)
        
        # Make streaming request with smaller chunk size for real-time feel
        response = requests.post(
            url,
            headers=headers,
            data=data.encode('utf-8'),
            timeout=120,
            stream=True
        )
        
        if response.status_code != 200:
            print_colored(f"❌ Error: API returned status {response.status_code}", "91")
            try:
                print(response.text[:500])
            except:
                pass
            return {'thinking': '', 'response': '', 'sources': []}
        
        # State tracking
        current_phase = None
        thinking_content = []
        response_content = []
        sources = []
        printed_header = {'thinking': False, 'response': False}
        buffer = ""
        
        # Process stream byte by byte for true real-time streaming
        for chunk in response.iter_content(chunk_size=1, decode_unicode=True):
            if chunk is None:
                continue
            
            buffer += chunk
            
            # Look for complete SSE data lines
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
                    
                    # Handle chat completion
                    if data_obj.get('type') == 'chat:completion':
                        content_data = data_obj.get('data', {})
                        delta_content = content_data.get('delta_content', '')
                        phase = content_data.get('phase', '')
                        
                        if delta_content:
                            # Check if phase changed
                            if phase != current_phase:
                                if current_phase is not None:
                                    print()  # New line when switching phases
                                current_phase = phase
                            
                            if phase == 'thinking':
                                # Print thinking header once
                                if not printed_header['thinking']:
                                    print()
                                    print_colored("🧠 AI THINKING:", "96")
                                    print_separator('─', 50)
                                    printed_header['thinking'] = True
                                
                                # Print thinking in dim color - REAL TIME
                                sys.stdout.write(f"\033[90m{delta_content}\033[0m")
                                sys.stdout.flush()
                                thinking_content.append(delta_content)
                            else:
                                # Print response header once
                                if not printed_header['response']:
                                    if printed_header['thinking']:
                                        print("\n")  # Extra line after thinking
                                    print_colored("💬 AI RESPONSE:", "92")
                                    print_separator('─', 50)
                                    printed_header['response'] = True
                                
                                # Print response - REAL TIME
                                sys.stdout.write(delta_content)
                                sys.stdout.flush()
                                response_content.append(delta_content)
                    
                    # Handle sources
                    elif data_obj.get('type') == 'sources' or 'sources' in data_obj:
                        source_data = data_obj.get('sources', data_obj.get('data', {}).get('sources', []))
                        if isinstance(source_data, list):
                            sources.extend(source_data)
                    
                    # Handle search results
                    elif data_obj.get('type') == 'search_results':
                        results = data_obj.get('data', {}).get('results', [])
                        for result in results:
                            sources.append({
                                'title': result.get('title', ''),
                                'url': result.get('url', ''),
                                'snippet': result.get('snippet', '')
                            })
                    
                    # Handle web search
                    elif data_obj.get('type') == 'chat:web_search':
                        web_data = data_obj.get('data', {})
                        if 'references' in web_data:
                            for ref in web_data['references']:
                                sources.append({
                                    'title': ref.get('title', ''),
                                    'url': ref.get('url', ''),
                                    'snippet': ref.get('snippet', '')
                                })
                                
                except json.JSONDecodeError:
                    continue
        
        print()  # Final newline
        
        return {
            'thinking': ''.join(thinking_content),
            'response': ''.join(response_content),
            'sources': sources
        }
        
    except requests.Timeout:
        print_colored("\n❌ Request timed out", "91")
        return {'thinking': '', 'response': '', 'sources': []}
    except Exception as e:
        print_colored(f"\n❌ Error: {str(e)}", "91")
        import traceback
        traceback.print_exc()
        return {'thinking': '', 'response': '', 'sources': []}


def display_sources(sources: list):
    """Display sources after streaming is complete."""
    if not sources:
        return
    
    print()
    print_colored("📚 SOURCES:", "93")
    print_separator('─', 50)
    
    seen_urls = set()
    count = 0
    for source in sources:
        if isinstance(source, dict):
            url = source.get('url', '')
            if url in seen_urls:
                continue
            seen_urls.add(url)
            count += 1
            title = source.get('title', 'No title')
            print(f"  {count}. {title}")
            if url:
                print(f"     🔗 {url}")
        else:
            count += 1
            print(f"  {count}. {source}")
    print()


def main():
    """Main chatbot loop."""
    print_separator('═', 60)
    print_colored("  🤖 Z.AI Terminal Chatbot", "95")
    print_colored("  Real-time Streaming Mode", "96")
    print_colored("  Type 'quit' or 'exit' to end", "90")
    print_separator('═', 60)
    print()
    
    # Check if curl.txt exists
    if not os.path.exists(CURL_FILE):
        print_colored(f"❌ Error: curl.txt not found at {CURL_FILE}", "91")
        return
    
    while True:
        try:
            # Get user input
            user_input = input("\033[94m📝 You: \033[0m").strip()
            
            # Check for exit commands
            if user_input.lower() in ['quit', 'exit', 'q', 'bye']:
                print_colored("\n👋 Goodbye!", "95")
                break
            
            # Skip empty inputs
            if not user_input:
                print_colored("Please enter a message.", "93")
                continue
            
            # Stream the response in real-time
            result = stream_response(user_input)
            
            # Display sources after streaming
            display_sources(result['sources'])
            
        except KeyboardInterrupt:
            print_colored("\n\n👋 Goodbye!", "95")
            break
        except Exception as e:
            print_colored(f"\n❌ Error: {e}", "91")
            continue


if __name__ == "__main__":
    main()
