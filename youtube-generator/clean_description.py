#!/usr/bin/env python3
import html2text
import sys
import re

def clean_description(raw_html):
    """Convert HTML description to clean text for YouTube."""
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.body_width = 0
    h.unicode_snob = True
    h.escape_snob = False
    h.ignore_images = True
    h.ignore_emphasis = False
    h.ignore_tables = True
    
    text = h.handle(raw_html)
    
    # Convert markdown links to preserve context: [text](url) -> text (url)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\1 (\2)', text)
    
    # Preserve paragraph structure - only normalize excessive newlines (3+)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Clean up bullet points while preserving structure
    text = re.sub(r'^[\s]*[-•]\s*', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\*\s*', '• ', text, flags=re.MULTILINE)
    
    # Only remove excessive markdown formatting, preserve basic emphasis
    text = re.sub(r'\*{3,}', '**', text)  # Reduce excessive asterisks
    text = re.sub(r'_{3,}', '__', text)   # Reduce excessive underscores
    text = re.sub(r'`{2,}', '`', text)    # Reduce excessive backticks
    
    # Clean up spacing around punctuation
    text = re.sub(r'\s+([,.!?;:])', r'\1', text)
    text = re.sub(r'([,.!?;:])\s+', r'\1 ', text)
    
    # Remove unnecessary backslashes (but preserve intentional ones)
    text = re.sub(r'\\([^nrt\\])', r'\1', text)
    
    # Clean up multiple spaces
    text = re.sub(r' {2,}', ' ', text)
    
    # Strip leading/trailing whitespace from each line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    
    # Remove any remaining HTML tags (just in case)
    text = re.sub(r'<[^>]+>', '', text)
    
    # Final cleanup - remove empty lines at start/end
    text = text.strip()
    
    # Truncate to 5000 characters at word boundary
    if len(text) > 5000:
        text = text[:4950]  # Leave some buffer
        # Find last complete sentence or paragraph
        last_period = text.rfind('.')
        last_newline = text.rfind('\n\n')
        cut_point = max(last_period + 1, last_newline) if last_period > -1 or last_newline > -1 else len(text)
        text = text[:cut_point].strip()
    
    return text

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python clean_description.py <input_file>", file=sys.stderr)
        sys.exit(1)
    
    input_file = sys.argv[1]
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_html = f.read()
        
        cleaned_text = clean_description(raw_html)
        print(cleaned_text)
    except Exception as e:
        print(f"Error processing description: {e}", file=sys.stderr)
        sys.exit(1)
