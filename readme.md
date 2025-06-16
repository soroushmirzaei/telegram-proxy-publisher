# Telegram Proxy Publisher

This project is an automated Python script designed to fetch Telegram proxy links from specified subscription URLs, parse their details, perform country-level geolocation using a local GeoIP database, filter out duplicates, and post the new, parsed proxies to a designated Telegram channel. The script is designed to run periodically using GitHub Actions and includes features to manage execution time and format posts with inline buttons

## Features

- **Fetch Telegram Proxy Links:** Downloads content from multiple subscription URLs provided in `data/subscriptions.txt` and extracts lines that are valid Telegram proxy links (`https://t.me/proxy?...` or `tg://proxy?...`).
- **Parse Telegram Links:** Capable of parsing `tg://proxy?` and `https://t.me/proxy?` links, extracting the server (IP), port, and secret parameters. Handles links even if the secret value is empty.
- **Geolocation (Offline - Country Only):** Uses a local GeoLite2 Country database (`data/GeoLite2-Country.mmdb`) downloaded from a public GitHub repository to determine the country of the proxy server's IP address without relying on external APIs during runtime.
- **Archive & Deduplicate:** Maintains a `data/archive.txt` file to store raw proxy links that have already been successfully posted, preventing duplicate posts to the Telegram channel. The archive is persisted between runs via GitHub Actions commits.
- **Chunked Posting with Delay:** Posts new proxies to Telegram in chunks of 9 (or fewer for the last group), with a configurable delay between posting each chunk to avoid flooding the channel.
- **Formatted Posts with Emojis and Buttons:** Posts are formatted with emojis (🔒, 🔑, 🌎), include the IP:Port and Country, the raw proxy link in monospace for easy copying, and a row of "Connect" inline buttons (arranged 3x3 if possible) that use the raw link as their URL. The channel handle `@NexuProxy` is added at the end of each post.
- **Execution Timeout:** The script monitors its total execution time and will stop processing and posting if it exceeds a predefined limit (default 55 minutes) to prevent exceeding GitHub Actions job limits. Proxies not posted due to the timeout will not be added to the archive for that run.
- **Telegram Integration (Direct API with requests):** Uses the `requests` library to make direct calls to the Telegram Bot API (`sendMessage` method) for reliable message sending.
- **GitHub Actions Automation:** Includes workflow files (`.github/workflows/push.yml` and `.github/workflows/schedule.yml`) to run the script automatically on push events, manually via `workflow_dispatch`, and on a schedule (e.g., hourly). The workflows handle dependency installation, GeoIP database download, and archive file persistence.

## Limitations

- This script is specifically designed for Telegram proxy links (`tg://proxy?` and `https://t.me/proxy?`) and will ignore other proxy formats (like HTTP, SOCKS, Vmess, Vless, Trojan, SS) found in subscription sources.
- The script does not perform live connectivity checks for Telegram proxies using standard methods, as this requires specific client implementations. Proxies are considered valid and posted if they are successfully parsed from the subscription links and are not in the archive.
- Geolocation is limited to country-level information based on the GeoLite2 Country database. City-level data is not used. The accuracy of the geolocation depends on the GeoLite2 database.
- The "Connect" inline buttons use the raw `tg://` link as their URL. While this is the standard way to provide clickable proxy links in Telegram, their functionality can vary depending on the user's Telegram client and operating system.

## Directory Structure

```
telegram-proxy-publisher/
├── .github/
│ └── workflows/
│ ├── push.yml # Workflow for push and manual triggers
│ └── schedule.yml # Workflow for scheduled triggers
├── src/
│ ├── init.py # Empty file to make src a Python package
│ └── proxy_poster.py # The main Python script
├── data/
│ ├── subscriptions.txt # Your list of proxy subscription URLs
│ └── archive.txt # Archive of previously posted raw links
│ └── GeoLite2-Country.mmdb # GeoIP database (downloaded by workflow)
├── requirements.txt # Lists Python dependencies (requests, geoip2)
└── README.md # This README file
```

## Setup

1. **Create a GitHub Repository:** If you don't already have one, create a new public or private repository on GitHub.
2. **Clone the Repository:** Clone the repository to your local machine.
    ```
    git clone github.com/soroushmirzaei/telegram-proxy-publisher
    cd telegram-proxy-publisher
    ```
3. **Create Directories and Files:** Create the necessary directories and empty files as shown in the Directory Structure above.
    ```
    mkdir .github .github/workflows src data
    touch src/__init__.py data/subscriptions.txt data/archive.txt requirements.txt README.md
    ```
4. **Add Code and Content:**
    - Copy the content of `proxy_poster.py` (from the latest version provided) into `src/proxy_poster.py`.
    - Copy the content of `requirements.txt` (from the latest version provided) into `requirements.txt`.
    - Copy the content of `push.yml` (from the latest version provided) into `.github/workflows/push.yml`.
    - Copy the content of `schedule.yml` (from the latest version provided) into `.github/workflows/schedule.yml`.
    - Copy the content of this `README.md` into your `README.md` file.
    - Edit `data/subscriptions.txt` and add your proxy subscription URLs, one URL per line. These URLs should ideally provide lists of Telegram proxy links.
        ```
        https://example.com/telegram/proxy/links.txt
        http://another-source.net/tgproxies
        ```
5. **Set up Telegram Bot:**
    - Create a new Bot on Telegram by talking to the official [@BotFather](https://t.me/BotFather). Obtain your HTTP API Token.
    - Add your newly created Bot as an administrator to your Telegram Channel. Ensure the bot has permission to Post messages.
    - Get your Telegram Channel ID. The easiest way to find this is to forward any message from your channel to a bot like [@JsonDumpBot](https://t.me/JsonDumpBot) and look for the `chat.id` value in the JSON response. Channel IDs for public channels typically start with `-100`.
6. **Configure GitHub Secrets:** Sensitive information like your Telegram Bot Token and Channel ID should be stored securely as GitHub Secrets.
    - Go to your GitHub repository on the web.
    - Navigate to **Settings -> Secrets and variables -> Actions**.
    - Click on **New repository secret**.
    - Create a secret named `TELEGRAM_BOT_TOKEN` and paste your Telegram Bot's HTTP API Token as the value.
    - Click **Add secret**.
    - Click on **New repository secret** again.
    - Create a secret named `TELEGRAM_CHANNEL_ID` and paste your Telegram Channel ID as the value (e.g., `-100123456789`).
    - Click **Add secret**.
7. **Ensure GitHub Actions Workflow Permissions:** The workflow needs permission to write to the repository to commit the updated `data/archive.txt` file.
    - Go to your GitHub repository on the web.
    - Navigate to **Settings -> Code and automation -> Actions -> General**.
    - Scroll down to **Workflow permissions** and ensure **Read and write permissions** is selected.
    - Click **Save**.
8. **Commit and Push:** Commit all the created and modified files to your GitHub repository and push them to the main branch.
    ```
    git add .
    git commit -m "Initial project setup and files"
    git push origin main
    ```

## Usage

- The project is configured to run automatically via GitHub Actions based on the schedules defined in the workflow files (`.github/workflows/schedule.yml`). The default schedule is 30 minutes past every hour.
- You can also manually trigger the **Execute On Push** workflow from the "Actions" tab in your GitHub repository:
    - Go to the **Actions** tab.
    - Select the **Execute On Push** workflow from the list on the left.
    - Click the **Run workflow** button on the right.
- When a workflow runs, the script will perform the following steps:
    - Download the GeoLite2 Country database (`data/GeoLite2-Country.mmdb`).
    - Fetch content from the URLs listed in `data/subscriptions.txt` and extract valid Telegram proxy links.
    - Load the existing archive of previously posted links from `data/archive.txt`.
    - Identify new, unique Telegram proxy links that are not in the archive.
    - Parse the details (IP, Port, Secret) and perform country-level geolocation lookup for these new links.
    - Post the new, parsed proxies to your Telegram channel in chunks of 9, with a delay between chunks. Each post will include the formatted details, the raw link in monospace, and inline "Connect" buttons.
    - Monitor its execution time and stop early if it exceeds the `MAX_EXECUTION_TIME_SECONDS` limit.
    - Update the `data/archive.txt` file by adding the raw links of the proxies that were successfully posted during the run.
    - The workflow will then commit the updated `data/archive.txt` back to the repository.

## Configuration

You can modify the script's behavior by editing the configuration variables at the top of `src/proxy_poster.py`:

- `POST_DELAY_SECONDS`: Adjust the delay between posting each chunk of proxies (in seconds).
- `PROXIES_PER_POST`: Change the number of proxies included in each Telegram message (default is 9 for a 3x3 button grid).
- `MAX_EXECUTION_TIME_SECONDS`: Adjust the maximum allowed script execution time in seconds (default is 3300 seconds, or 55 minutes).
- `GEOIP_DATABASE_PATH`: Change the expected path for the GeoLite2 database file if you place it elsewhere.

You can also modify the schedule by editing the cron expression in `.github/workflows/schedule.yml`.

## Troubleshooting

- **Proxies not posting:**
    - Check the GitHub Actions workflow logs for errors. Look for messages indicating failed API calls or issues within the script.
    - Ensure your `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` secrets are correct and that the bot has permission to post in the channel.
    - Check the `Found X successfully parsed Telegram proxies to potentially post.` log message. If X is 0, no new unique proxies were found after fetching and filtering the archive.
    - Verify the format of links in your `data/subscriptions.txt`. The script specifically looks for `tg://proxy?` or `https://t.me/proxy?` links.
- **Missing server, port, or secret in link warnings:** These warnings indicate that links from your subscription sources are incomplete. The script skips these links. You can ignore the warnings or find better subscription sources.
- **Error loading GeoIP Country database:** Ensure the GitHub Actions workflow successfully downloads the `GeoLite2-Country.mmdb` file to the `data/` directory. Check the download step logs in the workflow run.
- **Script timing out:** If the script consistently hits the `Execution time approaching limit` warning, you might have a very large number of new proxies to process. You can increase `MAX_EXECUTION_TIME_SECONDS` (within GitHub Actions limits) or reduce `PROXIES_PER_POST` or `POST_DELAY_SECONDS` (though reducing the delay might lead to Telegram API flood limits).

## Future Enhancements

- Add more sophisticated parsing for variations in Telegram proxy links if encountered.
- Implement more detailed error handling and potentially send error notifications to an admin chat.
- Consider caching the GeoIP database download in GitHub Actions to speed up runs (more advanced workflow configuration).
- Explore alternative methods for checking the live status of Telegram proxies if necessary (requires external tools or libraries).

## License

This project is open-source and available under the MIT License.
