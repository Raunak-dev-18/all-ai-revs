#!/usr/bin/env python3
"""
Gemini Chatbot - A simple terminal chatbot using the Gemini API
Parses curl.txt and uses Python requests to make the API call
"""

import requests
import json
import re
import sys
import urllib.parse
import os
import time

# Path to curl.txt file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CURL_FILE = os.path.join(SCRIPT_DIR, "curl.txt")
DEBUG_FILE = os.path.join(SCRIPT_DIR, "last_response.txt")

def parse_curl_file():
    """Parse the curl.txt file to extract URL, headers, cookies, and data template"""
    with open(CURL_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove line continuations and join
    content = content.replace('\\\r\n', ' ').replace('\\\n', ' ')
    
    # Extract URL
    url_match = re.search(r"curl\s+'([^']+)'", content)
    if not url_match:
        raise ValueError("Could not find URL in curl file")
    url = url_match.group(1)
    
    # Extract headers
    headers = {}
    header_matches = re.finditer(r"-H\s+'([^:]+):\s*([^']+)'", content)
    for match in header_matches:
        headers[match.group(1)] = match.group(2)
    
    # Extract cookies
    cookies = {}
    cookie_match = re.search(r"-b\s+'([^']+)'", content)
    if cookie_match:
        cookie_str = cookie_match.group(1)
        for part in cookie_str.split(';'):
            if '=' in part:
                key, value = part.strip().split('=', 1)
                cookies[key] = value
    
    # Extract data-raw (the POST body)
    data_match = re.search(r"--data-raw\s+\$'([^']+)'", content)
    if not data_match:
        data_match = re.search(r"--data-raw\s+'([^']+)'", content)
    
    data_template = ""
    if data_match:
        data_template = data_match.group(1)
        # Unescape the $'...' string
        data_template = data_template.replace('\\u0021', '!')
    
    return url, headers, cookies, data_template

def build_request_data(data_template, query):
    """Replace the query in the data template"""
    # The original query is "Hey Who are you"
    original_query = "Hey Who are you"
    
    # Replace the original query with the new one
    new_data = data_template.replace(original_query, query)
    
    return new_data

def stream_print(text, delay=0.008):
    """Print text with a streaming effect"""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()

def extract_response_text(raw_response):
    """
    Extract the AI response, thinking, and sources from the raw API response.
    The response is a streaming format with multiple JSON chunks.
    Each chunk builds on the previous one with more complete text.
    """
    response_text = ""
    thinking_text = ""
    sources = []
    
    if not raw_response:
        return response_text, thinking_text, sources
    
    # Save for debugging
    with open(DEBUG_FILE, 'w', encoding='utf-8') as f:
        f.write(raw_response)
    
    # Remove the )]}' prefix if present
    if raw_response.startswith(")]}'"):
        raw_response = raw_response[4:]
    
    # The response format contains lines like:
    # 331
    # [[json_content]]
    # The number is the byte count of the following JSON
    
    lines = raw_response.strip().split('\n')
    
    full_response = ""
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Skip numeric-only lines (byte count indicators)
        if line.isdigit():
            continue
        
        # Try to parse lines that look like JSON arrays
        if line.startswith('[['):
            try:
                data = json.loads(line)
                # The structure is: [["wrb.fr", null, "escaped_json_string"]]
                if data and isinstance(data, list) and len(data) > 0:
                    inner = data[0]
                    if isinstance(inner, list) and len(inner) >= 3:
                        # The third element is a JSON string that needs to be parsed
                        json_str = inner[2]
                        if json_str and isinstance(json_str, str):
                            try:
                                inner_data = json.loads(json_str)
                                # Navigate to find the response text
                                # Structure: [null, [ids], null, null, [[response_id, [text], ...]], ...]
                                if inner_data and len(inner_data) > 4:
                                    responses = inner_data[4]
                                    if responses and isinstance(responses, list) and len(responses) > 0:
                                        response_item = responses[0]
                                        if response_item and len(response_item) >= 2:
                                            text_array = response_item[1]
                                            if text_array and isinstance(text_array, list) and len(text_array) > 0:
                                                candidate_text = text_array[0]
                                                if isinstance(candidate_text, str) and len(candidate_text) > len(full_response):
                                                    full_response = candidate_text
                            except json.JSONDecodeError:
                                pass
            except json.JSONDecodeError:
                pass
    
    response_text = full_response
    
    # Try regex fallback if structured parsing didn't work
    if not response_text:
        # Pattern to find the main response text in the streaming format
        # Look for the pattern: ["response_id",["TEXT"],...
        pattern = r'\[\"rc_[a-f0-9]+\",\[\"([^\"]+)\"'
        matches = re.findall(pattern, raw_response)
        if matches:
            # Get the longest match (should be the complete response)
            response_text = max(matches, key=len)
    
    # Extract URLs as sources
    url_pattern = r'https?://[^\s\"\\\]<>]+'
    url_matches = re.findall(url_pattern, raw_response)
    for url in url_matches:
        # Filter out Google internal URLs
        if 'google.com' not in url and 'gstatic' not in url and url not in sources:
            sources.append(url)
    
    return response_text, thinking_text, sources[:10]

def format_response(text):
    """Clean and format the response text"""
    if not text:
        return ""
    
    # Unescape common sequences
    text = text.replace('\\n', '\n')
    text = text.replace('\\t', '  ')
    text = text.replace('\\"', '"')
    text = text.replace("\\'", "'")
    text = text.replace('\\\\', '\\')
    
    # Convert markdown bold **text** to text (for terminal)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\033[1m\1\033[0m', text)
    
    # Clean up unicode escapes
    def replace_unicode(match):
        try:
            return chr(int(match.group(1), 16))
        except:
            return match.group(0)
    text = re.sub(r'\\u([0-9a-fA-F]{4})', replace_unicode, text)
    
    return text.strip()

def main():
    """Main chatbot loop"""
    print("\n" + "=" * 50)
    print("  🤖 Gemini Chatbot")
    print("  Type 'exit' or 'quit' to end")
    print("=" * 50 + "\n")
    
    # Parse curl file
    try:
        url, headers, cookies, data_template = parse_curl_file()
        print("✅ Configuration loaded successfully\n")
    except FileNotFoundError:
        print(f"❌ Error: curl.txt not found at {CURL_FILE}")
        return
    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        return
    
    # Create session for persistent cookies
    session = requests.Session()
    session.cookies.update(cookies)
    
    while True:
        try:
            # Get user input
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['exit', 'quit', 'bye', 'q']:
                print("\n👋 Goodbye!")
                break
            
            print("\n🤔 Thinking...\n")
            
            # Build request data with new query
            request_data = build_request_data(data_template, user_input)
            
            # Make the POST request
            try:
                response = session.post(
                    url,
                    headers=headers,
                    data=request_data,
                    timeout=30
                )
                
                if response.status_code != 200:
                    print(f"❌ Error: HTTP {response.status_code}")
                    print(f"Response: {response.text[:200]}")
                    continue
                
                raw_response = response.text
                
            except requests.exceptions.Timeout:
                print("❌ Request timed out. Please try again.")
                continue
            except requests.exceptions.RequestException as e:
                print(f"❌ Request error: {e}")
                continue
            
            # Extract response components
            response_text, thinking_text, sources = extract_response_text(raw_response)
            
            # Display the response
            print("─" * 50)
            print("🤖 Gemini:")
            print("─" * 50)
            
            formatted = format_response(response_text)
            if formatted:
                stream_print(formatted)
            else:
                print("(Could not parse response - check last_response.txt)")
            
            # Show thinking if available
            if thinking_text:
                print("\n💭 Thinking:")
                print("-" * 30)
                print(format_response(thinking_text))
            
            # Show sources if available
            if sources:
                print("\n📚 Sources:")
                print("-" * 30)
                for i, source in enumerate(sources[:5], 1):
                    print(f"  {i}. {source}")
            
            print()
            
        except KeyboardInterrupt:
            print("\n\n👋 Interrupted. Goodbye!")
            break
        except EOFError:
            print("\n\n👋 Goodbye!")
            break

if __name__ == "__main__":
    main()
