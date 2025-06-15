import requests
import time
import re
import os
import logging
import json
from urllib.parse import urlparse, unquote, parse_qs

# GeoIP library
try:
    import geoip2.database
    GEOIP_ENABLED = True
except ImportError:
    logging.warning("geoip2 library not found. Geolocation will be disabled.")
    GEOIP_ENABLED = False

# --- Configuration ---
# Get these from GitHub Secrets
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID') # Your channel ID (e.g., -100123456789)

# File paths relative to the script's execution location (repo root in GitHub Actions)
SUBSCRIPTION_FILE = 'data/subscriptions.txt'
ARCHIVE_FILE = 'data/archive.txt'
# Updated path for the GeoLite2 Country database
GEOIP_DATABASE_PATH = 'data/GeoLite2-Country.mmdb'

POST_DELAY_SECONDS = 600 # Delay between posts (e.g., 600 seconds = 10 minutes)
PROXIES_PER_POST = 9 # Number of proxies to include in each Telegram message
MAX_EXECUTION_TIME_SECONDS = 3300 # Maximum execution time in seconds (55 minutes)

# Threshold length for secret heuristic (secrets longer than this with trailing A's are skipped)
# Secrets shorter than this with trailing A's will have the A's trimmed.
# Adjusted based on user feedback and provided proxy list.
SECRET_HEURISTIC_LENGTH_THRESHOLD = 60 # Adjusted threshold

# Telegram Bot API base URL
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- GeoIP Setup ---
geoip_reader = None
if GEOIP_ENABLED:
    if os.path.exists(GEOIP_DATABASE_PATH):
        try:
            # Use geoip2.database.Reader for the Country database
            geoip_reader = geoip2.database.Reader(GEOIP_DATABASE_PATH)
            logging.info("GeoIP Country database loaded successfully.")
        except Exception as e:
            logging.error(f"Error loading GeoIP Country database: {e}")
            geoip_reader = None # Disable GeoIP if loading fails
            GEOIP_ENABLED = False
    else:
        logging.warning(f"GeoIP Country database not found at {GEOIP_DATABASE_PATH}. Geolocation will be disabled.")
        GEOIP_ENABLED = False


def get_geolocation(ip_address):
    """Looks up country geolocation for an IP address using the loaded GeoIP database."""
    if not GEOIP_ENABLED or not geoip_reader:
        return 'Unknown', '', '' # Return country name, empty emoji, empty code

    try:
        # Use the country method for the GeoLite2-Country database
        response = geoip_reader.country(ip_address)
        country_name = response.country.name if response.country else 'Unknown'
        country_code = response.country.iso_code if response.country else '' # Get the country code
        country_emoji = get_country_emoji(country_code) if country_code else ''
        return country_name, country_emoji, country_code # Return name, emoji, and code
    except geoip2.errors.AddressNotFoundError:
        logging.debug(f"Geolocation not found for IP: {ip_address}")
        return 'Unknown', '', ''
    except Exception as e:
        logging.error(f"Error during GeoIP lookup for {ip_address}: {e}")
        return 'Unknown', '', ''

def get_country_emoji(country_code):
    """Converts ISO 3166-1 alpha-2 country code to flag emoji."""
    if not country_code or len(country_code) != 2:
        return ''
    # Flag emojis are represented by two regional indicator symbols.
    # Regional indicator symbol letters are the Unicode characters from U+1F1E6 to U+1F1FF.
    # 'A' is U+1F1E6, 'B' is U+1F1E7, etc.
    # So, the emoji for a country code like 'US' is U+1F1FA U+1F1F8
    # (Regional Indicator Symbol Letter U + Regional Indicator Symbol Letter S)
    return ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in country_code.upper())

def process_secret_with_heuristic(secret):
    """
    Applies a heuristic to process secrets based on trailing 'A's and length.
    - If secret ends with 'A's and is shorter than threshold, trims 'A's.
    - If secret ends with 'A's and is longer than or equal to threshold, returns None (skip).
    - Otherwise, returns the original secret.
    """
    if not secret:
        return secret # Return empty secret as is

    # Find the index of the first non-'A' character from the end
    last_non_a_index = len(secret) - 1
    while last_non_a_index >= 0 and secret[last_non_a_index] == 'A':
        last_non_a_index -= 1

    # If the secret consists only of 'A's or is empty after trimming
    if last_non_a_index < 0:
        # If the original secret was just A's, it's likely invalid anyway, treat as corrupted
        logging.debug(f"Secret '{secret}' consists only of A's. Deemed corrupted and skipped.")
        return None

    trimmed_secret = secret[:last_non_a_index + 1]
    trailing_as_count = len(secret) - len(trimmed_secret)

    # If there were trailing 'A's
    if trailing_as_count > 0:
        logging.debug(f"Secret '{secret}' has {trailing_as_count} trailing A's. Trimmed part: '{secret[last_non_a_index+1:]}'")
        # Apply the length heuristic based on the *original* secret length
        if len(secret) >= SECRET_HEURISTIC_LENGTH_THRESHOLD:
            logging.warning(f"Original secret '{secret}' is long ({len(secret)} chars) and has trailing A's. Deemed corrupted and skipped.")
            return None # Skip long secrets with trailing A's
        else:
            logging.info(f"Original secret '{secret}' is short ({len(secret)} chars) and has trailing A's. Using trimmed secret: '{trimmed_secret}'")
            return trimmed_secret # Use trimmed secret for shorter ones

    # If no trailing 'A's, return the original secret
    return secret


# --- Helper Functions ---

def get_proxies_from_links(file_path):
    """Reads subscription links from a file and fetches raw proxy strings."""
    raw_proxies = []
    try:
        with open(file_path, 'r') as f:
            links = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        logging.error(f"Subscription file not found at {file_path}")
        return raw_proxies

    logging.info(f"Fetching proxies from {len(links)} subscription links...")
    for link in links:
        try:
            response = requests.get(link, timeout=15) # Timeout for fetching the link
            response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
            content = response.text

            # Assuming subscription links provide lists of tg:// or https://t.me/proxy links
            # Split content by lines and filter for relevant links
            proxy_links_from_link = [
                line.strip() for line in content.splitlines()
                if line.strip().startswith('tg://proxy?') or line.strip().startswith('https://t.me/proxy?')
            ]
            logging.info(f"Fetched {len(proxy_links_from_link)} Telegram proxy links from {link}")
            raw_proxies.extend(proxy_links_from_link)

        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching proxies from {link}: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred while processing {link}: {e}")

    # Filter out empty strings and potential headers/comments
    raw_proxies = [p.strip() for p in raw_proxies if p.strip() and not p.strip().startswith('#')]
    logging.info(f"Total raw Telegram proxy links fetched: {len(raw_proxies)}")
    return raw_proxies


def parse_telegram_proxy_link(proxy_link):
    """
    Parses a Telegram proxy link (tg://proxy? or https://t.me/proxy?).
    Extracts server, port, and secret. Processes secret using heuristic.
    Returns a dictionary with parsed details, including 'raw' with the processed secret,
    or None if parsing/processing fails or heuristic skips the proxy.
    """
    parsed = {'original_raw': proxy_link, 'type': 'Telegram'} # Store original raw link

    try:
        # Convert https://t.me/proxy? to tg://proxy? for consistent parsing
        if proxy_link.startswith('https://t.me/proxy?'):
            link_to_parse = 'tg://proxy?' + proxy_link.split('?', 1)[1]
        elif proxy_link.startswith('tg://proxy?'):
            link_to_parse = proxy_link
        else:
            logging.warning(f"Unsupported link format for parsing: {proxy_link}")
            return None

        parsed_url = urlparse(link_to_parse)
        query_params = parse_qs(parsed_url.query)

        server = query_params.get('server', [None])[0]
        port = query_params.get('port', [None])[0]
        secret = query_params.get('secret', [None])[0]

        # --- Basic Parameter Check ---
        # Check if server or port parameter is missing (None)
        if server is None or port is None:
            logging.warning(f"Missing server or port parameter in link: {proxy_link}")
            return None

        # --- Process Secret using Heuristic ---
        # If secret parameter is missing (None), process_secret_with_heuristic handles it.
        processed_secret = process_secret_with_heuristic(secret)

        # If process_secret_with_heuristic returned None, skip this proxy
        if processed_secret is None:
             logging.warning(f"Secret processing heuristic resulted in skipping link: {proxy_link}")
             return None

        parsed['ip'] = server
        parsed['port'] = port
        parsed['secret'] = processed_secret # Use the processed secret

        # Get Geolocation (Country name, emoji, and code)
        country_name, country_emoji, country_code = get_geolocation(parsed['ip'])
        parsed['country'] = country_name
        parsed['country_emoji'] = country_emoji
        parsed['country_code'] = country_code # Store the country code

        # --- Rebuild raw link with processed secret ---
        # This is crucial so the raw link used for the hyperlink and button
        # contains the potentially trimmed secret.
        if processed_secret is not None: # Should not be None if we reached here, but good practice
             parsed['raw'] = f"tg://proxy?server={parsed['ip']}&port={parsed['port']}&secret={processed_secret}"
             # If there's a tag, include it in the rebuilt link
             if 'tag' in query_params and query_params['tag'][0] is not None:
                  parsed['raw'] += f"&tag={query_params['tag'][0]}"


        logging.debug(f"Parsed Telegram proxy link: {parsed}")
        return parsed

    except Exception as e:
        logging.error(f"Error parsing Telegram proxy link {proxy_link}: {e}")
        return None

def check_proxy(proxy_details):
    """
    For Telegram proxies, we cannot perform a standard connectivity check
    with requests. This function primarily confirms parsing was successful.
    """
    if proxy_details and proxy_details.get('type') == 'Telegram':
        # Mark as successfully parsed, but not connectivity checked
        proxy_details['status'] = 'parsed'
        proxy_details['latency'] = -1 # Not applicable
        return proxy_details
    else:
        # Should not happen if get_proxies_from_links and parse_telegram_proxy_link work correctly
        return None


def load_archive(file_path):
    """Loads previously posted *processed* proxies from the archive file."""
    archived_proxies = set()
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                # Load the processed raw links that were previously saved
                archived_proxies = {line.strip() for line in f if line.strip()}
            logging.info(f"Loaded {len(archived_proxies)} processed proxies from archive.")
        except Exception as e:
            logging.error(f"Error loading archive file {file_path}: {e}")
    else:
        logging.info("Archive file not found. Starting with an empty archive.")
    return archived_proxies

def save_archive(file_path, new_processed_proxies):
    """Appends newly posted *processed* proxies to the archive file."""
    if not new_processed_proxies:
        return

    try:
        with open(file_path, 'a') as f:
            # Save the processed raw links
            for proxy_string in new_processed_proxies:
                f.write(proxy_string + '\n')
        logging.info(f"Saved {len(new_processed_proxies)} new processed proxies to archive.")
    except Exception as e:
        logging.error(f"Error saving to archive file {file_path}: {e}")

def escape_markdown_v2(text):
    """Escapes MarkdownV2 special characters."""
    # See https://core.telegram.org/bots/api#markdownv2-style
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', str(text))


def post_proxies_chunk_to_telegram(chat_id, proxies_chunk):
    """Formats and posts a chunk of Telegram proxies to the Telegram channel."""
    if not proxies_chunk:
        return False

    message_lines = []
    inline_buttons = []

    # Build the message text and collect button data for each proxy in the chunk
    for i, proxy_details in enumerate(proxies_chunk):
        # --- Message Text Format ---
        # 🔒 Address & Port: [IP]:[Port] (proxy Link)
        ip_port_text = f"{proxy_details.get('ip', 'N/A')}:{proxy_details.get('port', 'N/A')}"
        # Use the potentially modified raw link for the hyperlink
        raw_link = proxy_details.get('raw', '')

        # Escape MarkdownV2 characters in the IP:Port text and the URL itself
        ip_port_text_escaped = escape_markdown_v2(ip_port_text)
        raw_link_escaped = escape_markdown_v2(raw_link) # Escape URL for MarkdownV2 link

        address_line = f"🔒 Address & Port: [{ip_port_text_escaped}]({raw_link_escaped})" if raw_link else f"🔒 Address & Port: {ip_port_text_escaped}"
        message_lines.append(address_line)

        # 🌎 Country: 🇩🇪 Germany
        country_name = proxy_details.get('country', 'Unknown')
        country_emoji = proxy_details.get('country_emoji', '')
        country_line = f"🌎 Country: {country_emoji} {escape_markdown_v2(country_name)}" if country_name != 'Unknown' else f"🌎 Country: {escape_markdown_v2(country_name)}"
        message_lines.append(country_line)

        # Add a blank line between proxies if not the last one
        if i < len(proxies_chunk) - 1:
            message_lines.append("")

        # --- Prepare data for simple "Connect" inline button ---
        button_text = "Connect"
        # Use the potentially modified raw link for the button URL
        button_url = proxy_details.get('raw', '')

        if button_url:
             inline_buttons.append({'text': button_text, 'url': button_url})


    # Add the channel handle at the end of the message text
    message_lines.append("\n@NexuProxy")


    message_text = "\n".join(message_lines)

    # Create the inline keyboard markup
    reply_markup = None
    if inline_buttons:
        # --- Button Layout: 3x3 Grid ---
        inline_keyboard = []
        row = []
        for i, button in enumerate(inline_buttons):
            row.append(button)
            # Start a new row after every 3 buttons, or if it's the last button
            if (i + 1) % 3 == 0 or (i + 1) == len(inline_buttons):
                inline_keyboard.append(row)
                row = [] # Start a new row list

        reply_markup = json.dumps({'inline_keyboard': inline_keyboard})


    # --- Send message using requests ---
    send_message_url = f'{TELEGRAM_API_URL}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': message_text,
        'parse_mode': 'MarkdownV2',
        'reply_markup': reply_markup # Add the inline keyboard
    }

    # Remove reply_markup if it's None to avoid sending the parameter
    if reply_markup is None:
        del payload['reply_markup']


    logging.info(f"Attempting to post a chunk of {len(proxies_chunk)} proxies to chat ID {chat_id}...")
    try:
        response = requests.post(send_message_url, json=payload)
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        logging.info(f"Successfully posted a chunk of {len(proxies_chunk)} proxies to Telegram. Status Code: {response.status_code}")
        logging.debug(f"Telegram API response: {response.text}") # Log full response for debugging
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Error posting chunk of proxies to Telegram: {e}")
        if hasattr(e, 'response') and e.response is not None:
             logging.error(f"Telegram API error response status code: {e.response.status_code}")
             logging.error(f"Telegram API error response body: {e.response.text}")
             try:
                 error_response = e.response.json()
                 if 'error_code' in error_response and error_response['error_code'] == 429: # Too Many Requests (Flood)
                      logging.warning("Flood control exceeded. Waiting longer before next post.")
                      time.sleep(60) # Wait an extra minute on flood error
             except:
                 pass # Ignore JSON parsing errors if response is not JSON

        return False
    except Exception as e:
        logging.error(f"An unexpected error occurred during Telegram post: {e}")
        return False


# --- Main Execution ---

def main():
    # Record the start time of execution
    start_time = time.time()

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        logging.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID environment variables not set.")
        logging.error("Please set these as GitHub Secrets.")
        return

    # 1. Get raw Telegram proxy links from subscription links
    raw_telegram_proxy_links = get_proxies_from_links(SUBSCRIPTION_FILE)

    if not raw_telegram_proxy_links:
        logging.info("No raw Telegram proxy links fetched. Exiting.")
        return

    # 2. Load archive of previously posted *processed* proxies
    archived_processed_proxies = load_archive(ARCHIVE_FILE)
    logging.info(f"Loaded {len(archived_processed_proxies)} processed proxies from archive.")


    # 3. Parse and process all fetched links, and filter against the archive (based on processed link)
    logging.info("Parsing and processing fetched Telegram proxy links...")
    proxies_to_post = []
    processed_links_encountered = set() # Use a set to track processed links encountered in this run

    for original_raw_link in raw_telegram_proxy_links:
        # Check if parsing this link would exceed the time limit
        elapsed_time = time.time() - start_time
        if elapsed_time + 5 > MAX_EXECUTION_TIME_SECONDS: # Add a buffer (e.g., 5 seconds)
             logging.warning(f"Execution time approaching limit ({MAX_EXECUTION_TIME_SECONDS}s) during parsing. Skipping remaining links.")
             break # Stop parsing if time is running out

        # Parse and process the link (secret heuristic applied, parsed['raw'] updated)
        proxy_details = parse_telegram_proxy_link(original_raw_link)

        # If parsing and processing was successful
        if proxy_details:
            processed_raw_link = proxy_details['raw']

            # Check if this processed link has already been encountered in this run (deduplication within current fetch)
            if processed_raw_link in processed_links_encountered:
                 logging.debug(f"Skipping duplicate processed link encountered in this run: {processed_raw_link}")
                 continue # Skip to the next link

            # Check if this processed link is already in the archive (deduplication against history)
            if processed_raw_link in archived_processed_proxies:
                logging.debug(f"Skipping processed link already found in archive: {processed_raw_link}")
                # Add the processed link to the set encountered in this run, even if archived,
                # to handle cases where the same processed link appears multiple times in the source.
                processed_links_encountered.add(processed_raw_link)
                continue # Skip to the next link


            # If the processed link is new (not encountered in this run or in archive)
            logging.debug(f"Found new processed link to potentially post: {processed_raw_link}")
            processed_proxy = check_proxy(proxy_details) # This just sets status to 'parsed'
            if processed_proxy:
                 proxies_to_post.append(processed_proxy)
                 # Add the processed link to the set encountered in this run
                 processed_links_encountered.add(processed_raw_link)


    logging.info(f"Found {len(proxies_to_post)} new, unique, and valid proxies to potentially post after filtering.")


    if not proxies_to_post:
        logging.info("No new proxies to post after filtering. Exiting.")
        # If no new proxies, still save the archive in case any new processed links were encountered
        # that weren't in the archive (though they wouldn't be posted).
        # However, the most reliable approach is to only archive links that were successfully posted.
        # Let's stick to archiving only successfully posted links.
        return

    # 4. Chunk and post proxies_to_post to Telegram with delay
    logging.info(f"Starting posting process for {len(proxies_to_post)} proxies in chunks of {PROXIES_PER_POST} with a delay of {POST_DELAY_SECONDS} seconds between chunks...")

    posted_chunks_count = 0
    proxies_actually_posted_processed_links = [] # Keep track of *processed* raw links that were successfully posted

    # Iterate through proxies_to_post in chunks
    for i in range(0, len(proxies_to_post), PROXIES_PER_POST):
        chunk = proxies_to_post[i:i + PROXIES_PER_POST]
        logging.info(f"Processing chunk starting with proxy {i+1} (containing {len(chunk)} proxies).")

        # Calculate time needed for this post and the subsequent delay
        time_needed_for_post = 5 # Estimate time for API call (can vary)
        if (i + PROXIES_PER_POST) < len(proxies_to_post):
             time_needed_for_post += POST_DELAY_SECONDS # Add delay if not the last chunk

        # Check if posting this chunk and waiting would exceed the time limit
        elapsed_time = time.time() - start_time
        if elapsed_time + time_needed_for_post > MAX_EXECUTION_TIME_SECONDS:
            logging.warning(f"Execution time approaching limit ({MAX_EXECUTION_TIME_SECONDS}s) during posting. Skipping remaining posts.")
            break # Stop posting if time is running out

        success = post_proxies_chunk_to_telegram(TELEGRAM_CHANNEL_ID, chunk)

        if success:
            posted_chunks_count += 1
            # Add the *processed* raw links from the proxies in this chunk to the list of actually posted links
            proxies_actually_posted_processed_links.extend([p['raw'] for p in chunk])
            # Wait before posting the next chunk, unless it's the last one
            if (i + PROXIES_PER_POST) < len(proxies_to_post):
                logging.info(f"Waiting {POST_DELAY_SECONDS} seconds before next chunk...")
                time.sleep(POST_DELAY_SECONDS)
        else:
            logging.warning(f"Failed to post chunk starting with proxy {i+1}. Skipping wait and moving to next chunk.")
            # If posting fails, we might not want to wait the full delay.
            # Flood error handling is inside post_proxies_chunk_to_telegram.


    logging.info(f"Finished posting process. {posted_chunks_count} chunks were successfully posted.")
    logging.info(f"Total proxies successfully posted: {len(proxies_actually_posted_processed_links)}")


    # 5. Save the *processed* raw proxies that were *actually posted* to the archive
    # This ensures we don't archive proxies that were skipped due to the timeout or parsing issues.
    save_archive(ARCHIVE_FILE, proxies_actually_posted_processed_links)
    logging.info(f"Archived {len(proxies_actually_posted_processed_links)} processed proxies that were successfully posted.")


    # Close the GeoIP database reader when the script finishes
    if geoip_reader:
        geoip_reader.close()

if __name__ == "__main__":
    main()
