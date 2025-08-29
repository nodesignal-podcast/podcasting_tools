import sys
import requests
import html2text
import xml.etree.ElementTree as ET

# --- Configuration ---
RSS_URL = "https://serve.podhome.fm/rss/e8df0b13-47de-544a-99b7-ec7cbd960a16"
DESCRIPTION_MAX_LENGTH = 4800
DISCLAIMER = (
    "Jeden Samstag sendet Nodesignal eine neue Folge mit Gesprächen und Interviews über Bitcoin hinaus in die Welt.\n\n"
    "Reines Signal, keine Störgeräusche, keine Werbung.\n"
    "Focus on the signal, not on the noise!\n\n"
    "www.nodesignal.space"
)

def get_episode_info(rss_content, episode_number):
    root = ET.fromstring(rss_content)
    channel = root.find('channel')
    items = channel.findall('item')
    if episode_number < 1 or episode_number > len(items):
        raise ValueError(f"Episode number {episode_number} not found in RSS feed.")
    item = items[episode_number - 1]
    title = item.findtext('title', default='')
    description = item.findtext('description', default='')
    return title, description

def clean_description(raw_html):
    import re
    import html2text

    h = html2text.HTML2Text()
    h.ignore_links = False
    h.body_width = 0
    h.unicode_snob = True
    h.escape_snob = False
    h.ignore_images = True
    h.ignore_emphasis = False
    h.ignore_tables = True

    # Convert HTML to text
    text = h.handle(raw_html)

    # Convert markdown links to: text: url
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\1: \2', text)

    # Place all URLs on their own line
    text = re.sub(r'(https?://\S+)', r'\n\1\n', text)

    # Remove any remaining markdown formatting
    text = re.sub(r'[\*_`]', '', text)

    # Ensure bullet lists use '* ', '- ', or '+ ' at the start of lines
    text = re.sub(r'^[\s\-•]+', '* ', text, flags=re.MULTILINE)

    # Use double newlines for paragraphs
    text = re.sub(r'\n{2,}', '\n\n', text)

    # Remove unnecessary backslashes
    text = text.replace('\\', '')

    # Strip leading/trailing whitespace
    text = text.strip()

    # Truncate to 5000 characters
    if len(text) > 5000:
        text = text[:5000].rsplit('\n', 1)[0]

    return text

def main():
    episode_number = 1
    if len(sys.argv) > 1:
        try:
            episode_number = int(sys.argv[1])
        except ValueError:
            print("Invalid episode number. Must be an integer.", file=sys.stderr)
            sys.exit(1)

    try:
        response = requests.get(RSS_URL)
        response.raise_for_status()
        rss_content = response.text
    except Exception as e:
        print(f"Error fetching RSS feed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        title, raw_description = get_episode_info(rss_content, episode_number)
    except Exception as e:
        print(f"Error extracting episode info: {e}", file=sys.stderr)
        sys.exit(1)

    if not raw_description:
        print(f"No description found for episode {episode_number}.", file=sys.stderr)
        sys.exit(1)

    cleaned = clean_description(raw_description)
    final_description = f"{cleaned}\n\n{DISCLAIMER}"
    print(final_description)

if __name__ == "__main__":
    main()