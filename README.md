# FoxyFetch - Telegram YouTube Downloader Bot

## Description

FoxyFetch is a Python-based Telegram bot designed to download videos and audio from YouTube. Users can send a YouTube link, choose the desired quality (video resolution, best available, audio-only), or even convert the full video to a GIF. The bot features persistent logging of user interactions and download history using SQLite, and includes an administrative interface to view usage statistics.

## Features

*   **YouTube Video/Audio Download:** Download content directly from YouTube links.
*   **Quality Selection:** Choose from available video resolutions, best available video+audio, or audio-only (M4A format).
*   **GIF Conversion:** Convert the downloaded video into an animated GIF (uses ffmpeg).
*   **Database Logging:** Persistently logs user information, interactions (commands, messages, callbacks), and detailed download records (URL, quality, status, errors) into an SQLite database (`bot_data.db`).
*   **File Logging:** Creates rotating log files (`logs/bot.log`) for detailed operational monitoring and debugging, capped by size.
*   **Admin Statistics:** A `/stats` command (accessible only to predefined admin user IDs) provides an interactive menu to view bot usage statistics (users, interactions, downloads).
*   **Local Bot API Support:** Can be configured to use a local Telegram Bot API server for potentially higher upload limits.

## Setup and Installation

### Prerequisites

*   Python 3.10+
*   pip (Python package installer)
*   `ffmpeg`: Required for GIF conversion. Ensure it's installed and accessible in your system's PATH. (Installation varies by OS - e.g., `sudo apt update && sudo apt install ffmpeg` on Debian/Ubuntu, `brew install ffmpeg` on macOS).

### Installation Steps

1.  **Clone the repository:**
    ```bash
    git clone <repository_url> # Replace with your repo URL
    cd foxyfetch-bot # Or your repository directory name
    ```

2.  **Create and activate a virtual environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure the environment:**
    Create a file named `.env` in the project's root directory and add the necessary configuration variables. See the Configuration section below.

## Configuration (`.env` file)

Create a `.env` file in the project root with the following content:

```dotenv
# Required: Your Telegram Bot Token from BotFather
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE

# Required: Comma-separated list of Telegram User IDs who can access /stats
# Example: ADMIN_USER_IDS=123456789
# Example multiple: ADMIN_USER_IDS=123456789,987654321
ADMIN_USER_IDS=YOUR_ADMIN_USER_ID_HERE

# Optional: For using a Local Bot API Server
# LOCAL_BOT_API_SERVER_URL=http://localhost:8081
# TELEGRAM_API_ID=YOUR_API_ID # Required if using local server
# TELEGRAM_API_HASH=YOUR_API_HASH # Required if using local server
```

*   Replace `YOUR_BOT_TOKEN_HERE` with the token obtained from Telegram's @BotFather.
*   Replace `YOUR_ADMIN_USER_ID_HERE` with your Telegram user ID (and others, comma-separated, if needed). You can find your ID using bots like @userinfobot.
*   Uncomment and configure the `LOCAL_BOT_API_SERVER_URL`, `TELEGRAM_API_ID`, and `TELEGRAM_API_HASH` variables only if you intend to use a self-hosted Telegram Bot API server.

## Running the Bot

1.  Ensure your virtual environment is activated.
2.  Ensure your `.env` file is correctly configured.
3.  Run the main script:
    ```bash
    python main.py
    ```

The bot will start, initialize the database and logging, and begin polling for updates. The `logs/` directory and `bot_data.db` file will be created automatically if they don't exist.

## Usage

### Regular Users

1.  **Start the bot:** Send `/start` to the bot in Telegram.
2.  **Send a YouTube Link:** Send a message containing a valid YouTube URL (e.g., `https://www.youtube.com/watch?v=...` or `https://youtu.be/...`).
3.  **Select Quality:** The bot will reply with a message showing the video title and buttons for available download options (Best Quality, specific resolutions, Audio Only, Create GIF).
4.  **Wait:** The bot will show download/processing progress and then upload the resulting file (MP4 video, M4A audio, or GIF animation).

### Administrators

1.  **Access Statistics:** Send the `/stats` command to the bot.
2.  **Navigate:** Use the inline keyboard buttons to navigate through different statistics categories (Users, Interactions, Downloads, Overall Summary) and specific metrics.

## Project Structure

```
.
├── bot/                  # Main bot package
│   ├── __init__.py
│   ├── config.py         # Loads configuration from .env
│   ├── database.py       # SQLite database operations (aiosqlite)
│   ├── exceptions.py     # Custom exception classes
│   ├── external/         # Modules interacting with external tools (yt-dlp, ffmpeg)
│   ├── handlers/         # Telegram update handlers (commands, messages, callbacks)
│   ├── helpers.py        # Utility/helper functions (e.g., URL validation)
│   ├── presentation/     # User interface elements (e.g., keyboard layouts)
│   ├── services/         # Business logic coordinating external/db operations
│   └── utils/            # General utilities (e.g., decorators)
│
├── logs/                 # Directory for rotating log files
│   └── bot.log           # Main log file
│
├── bot_data.db           # SQLite database file (created automatically)
├── main.py               # Main application entry point
├── requirements.txt      # Python dependencies
├── .env                  # Environment variables (needs to be created)
└── README.md             # This file
```

## Key Dependencies

*   [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot): The core library for interacting with the Telegram Bot API.
*   [yt-dlp](https://github.com/yt-dlp/yt-dlp): For downloading video/audio content from YouTube.
*   [aiosqlite](https://github.com/omnilib/aiosqlite): Asynchronous interface for SQLite databases.
*   [python-dotenv](https://github.com/theskumar/python-dotenv): For loading environment variables from a `.env` file.