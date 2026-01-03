import requests
import re
import urllib.parse
import json
from bs4 import BeautifulSoup
import sys
import os
import time
import random

def stream_print(text, delay=0.01):
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()

# Configuration
CURL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "curl")
DEBUG_FILE_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_response.json")
DEBUG_FILE_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_response.html")

def parse_curl_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading curl file: {e}")
        return None, None, None

    # URL
    url_match = re.search(r"curl '([^']+)'", content)
    if not url_match:
        print("Could not find URL in curl file.")
        return None, None, None
    url = url_match.group(1)

    # Headers
    headers = {}
    header_matches = re.finditer(r"-H '([^']+)'", content)
    for match in header_matches:
        parts = match.group(1).split(':', 1)
        if len(parts) == 2:
            headers[parts[0].strip()] = parts[1].strip()

    # Cookies
    cookies = {}
    cookie_flag_match = re.search(r"-b '([^']+)'", content)
    if cookie_flag_match:
        cookie_str = cookie_flag_match.group(1)
        for part in cookie_str.split(';'):
            if '=' in part:
                k, v = part.split('=', 1)
                cookies[k.strip()] = v.strip()
    
    return url, headers, cookies

def search_json_refer(data, found_htmls):
    if isinstance(data, str):
        if "<div" in data or "<span" in data or "<b" in data:
            found_htmls.append(data)
    elif isinstance(data, list):
        for item in data:
            search_json_refer(item, found_htmls)
    elif isinstance(data, dict):
        for key, value in data.items():
            search_json_refer(value, found_htmls)

def chatbot():
    print("Initializing Chatbot...")
    url_template, headers, cookies = parse_curl_file(CURL_FILE)
    if not url_template:
        print("Failed to load configuration.")
        return

    print("Chatbot Ready. Type 'exit' to quit.")
    
    # Identify the query placeholder in the URL
    query_placeholder = "q=Who+are+you+and+how+are+you+going%3F"
    if query_placeholder not in url_template:
        # Try simplified version
        query_placeholder = "q=Who+are+you+and+how+are+you+going"
        if query_placeholder not in url_template:
            print("Warning: Specific query placeholder not found in URL template. Using regex fallback.")
            query_placeholder = None

    while True:
        try:
            query = input("\nYou: ")
        except EOFError:
            break
            
        if query.lower().strip() in ['exit', 'quit']:
            break
        
        if not query.strip():
            continue

        print("Thinking...", end='\r')

        # Construct new URL using string replacement to preserve other parameters exactly
        encoded_query = urllib.parse.quote(query)
        if query_placeholder:
            new_url = url_template.replace(query_placeholder, f"q={encoded_query}")
        else:
            new_url = re.sub(r"q=[^&]+", f"q={encoded_query}", url_template)

        try:
            # We must use a session to persist cookies if needed, but here cookies are passed explicitly
            response = requests.get(new_url, headers=headers, cookies=cookies)
            
            if response.status_code != 200:
                print(f"Error: {response.status_code}")
                # print(response.text[:200])
                continue
                
            text_data = response.text

            # Debug dump raw
            with open("last_response_raw.txt", 'w', encoding='utf-8') as f:
                f.write(text_data)

            print(f"Response length: {len(text_data)}")

            if text_data.startswith(")]}'"):
                text_data = text_data[4:].strip()
            
            try:
                # Handle possible multiple JSON objects concatenated
                # folif sometimes returns multiple JSONs. We iterate.
                # But usually standard load works if it's one block.
                # If fail, try to split.
                
                try:
                    json_data = json.loads(text_data)
                    
                    # Debug dump
                    with open(DEBUG_FILE_JSON, 'w', encoding='utf-8') as f:
                         json.dump(json_data, f, indent=2)
                    
                    html_snippets = []
                    search_json_refer(json_data, html_snippets)

                except json.JSONDecodeError:
                    # If simple JSON load fails, check if it's raw HTML or line-delimited JSON
                    html_snippets = []
                    
                    if text_data.strip().startswith("<"):
                        # It is raw HTML
                        html_snippets.append(text_data)
                    else:
                        # Try to load line by line if stream of JSON
                        for line in text_data.split('\n'):
                            if line.strip():
                                try:
                                    j = json.loads(line)
                                    # This might be a list or dict
                                    # We need to search it for html strings
                                    temp_snippets = []
                                    search_json_refer(j, temp_snippets)
                                    html_snippets.extend(temp_snippets)
                                except:
                                    pass
                
                if not html_snippets:
                    print("No HTML content found in response keys.")
                    # Fallback: if text_data is large, maybe it's just text?
                    # Check length
                    if len(text_data) > 1000:
                         # Treat as HTML anyway just in case
                         html_snippets.append(text_data)
                    else:
                        continue

                # Dump HTML for debugging
                with open(DEBUG_FILE_HTML, 'w', encoding='utf-8') as f:
                    f.write("\n\n<!-- CUT -->\n\n".join(html_snippets))

                print(" " * 20, end='\r') 
                print("--- AI Response ---")
                
                combined_html = "".join(html_snippets)
                soup = BeautifulSoup(combined_html, 'html.parser')
                
                # Remove generic junk
                for tag in soup(['script', 'style', 'svg', 'button', 'input']):
                    tag.decompose()

                # Extraction strategy:
                # 1. Look for known containers for AI Overview
                #    e.g. classes starting with 'g' or specific attributes
                # 2. If valid conversational text is found, print it.
                
                # Heuristic: Remove navigation text which is often short links
                # We want paragraphs.
                
                for p in soup.find_all(['p', 'div', 'span']):
                    text = p.get_text(strip=True)
                    # Simple filter to show "substantial" text
                    if len(text) > 60:
                        # Avoid duplicating if parent already covered it (naive check)
                        # We print and let the user see.
                        # Check against common noise
                        if "See more" in text or "Menu" in text: continue
                        
                        # Use a poor man's dedup
                        # (Not implemented to keep it simple)
                        pass

                # Global text extraction
                text_content = soup.get_text(separator='\n', strip=True)
                
                # Split and filter text
                lines = text_content.split('\n')
                seen_lines = set()
                
                print("--- AI Response ---")
                final_output_lines = []
                for line in lines:
                    line = line.strip()
                    if len(line) < 20: continue # Skip short headers/labels
                    if line in seen_lines: continue
                    if "http" in line and "google" in line: continue # Skip URLs
                    
                    seen_lines.add(line)
                    stream_print(line)
                
                # Sources Extraction
                print("\n--- Sources ---")
                sources = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    # Naive filtering for external links
                    if href.startswith("/url?q="):
                        href = href.split("/url?q=")[1].split("&")[0]
                        href = urllib.parse.unquote(href)
                    
                    if href.startswith("/search"): continue
                    if "google.com" in href: continue
                    if href.startswith("/") and not href.startswith("//"): continue
                    
                    title = a.get_text(strip=True)
                    if len(title) > 5:
                        sources.append(f"- {title}: {href}")
                
                # Dedup
                unique_sources = []
                seen_urls = set()
                for s in sources:
                    url = s.split(": ")[-1]
                    if url not in seen_urls:
                        unique_sources.append(s)
                        seen_urls.add(url)
                
                if unique_sources:
                    for s in unique_sources[:10]: # Limit to 10
                        stream_print(s, delay=0.005)
                else:
                    print("(No specific sources found)")

                print("\n-------------------")

            except Exception as e:
                print(f"Response processing error: {e}")
        
        except Exception as e:
            print(f"Request Error: {e}")

if __name__ == "__main__":
    chatbot()
