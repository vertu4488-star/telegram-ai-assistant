# 🤖 Telegram AI Assistant Bot (`telegram-ai-assistant`)

A production-ready, high-performance Telegram AI chatbot powered by **Google Gemini** (using the official `google-genai` SDK) and **aiogram 3.x**. Features persistent conversation memory, bilingual English/Khmer support, smart rate limiting, admin controls, and Docker containerization.

---

## 🌟 Key Features

- **⚡ Latest Gemini Models**: Built with the official `google-genai` SDK, defaulting to `gemini-3.7-flash` for blazing-fast and intelligent responses.
- **🇰🇭 🇬🇧 Bilingual Intelligence**: Automatically detects whether the user is typing in **Khmer (ភាសាខ្មែរ)** or **English** and responds naturally in the same language.
- **🧠 Multi-Turn Memory**: Keeps recent messages in context using async **SQLAlchemy 2.0** and SQLite. Context length is fully configurable.
- **🛡️ Production-Grade Resilience**: Built-in timeout controls, exponential backoff retries on transient errors (429/500/503), safe Markdown fallback, and message splitting for long responses (>4000 chars).
- **⏱️ Per-User Rate Limiting**: Protects against spam and accidental API exhaustion with configurable sliding-window rate limiting.
- **👑 Admin Dashboard & Broadcast**: Built-in `/stats` metrics (total users, message volume, 24h active users) and `/broadcast` announcements.
- **🔒 Privacy & Security First**: Zero plaintext secrets logged or exposed; `.env` configuration; secure token masking in string representations and logs.
- **🐳 Multi-Platform Deployment**: Ready for Docker, Docker Compose, Railway, Render, and VPS.

---

## 📋 Requirements

- **Python**: 3.11 or higher
- **Telegram Account**: To create a bot via [@BotFather](https://t.me/BotFather)
- **Google AI Studio Account**: To obtain a free [Gemini API Key](https://aistudio.google.com/)

---

## 🚀 Quick Start Guide

### Step 1: Create a Telegram Bot with BotFather
1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts to choose a name and username.
3. BotFather will provide an **HTTP API Token** (e.g. `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`). Copy this token.

### Step 2: Obtain your Google Gemini API Key
1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Sign in and click **Get API Key**.
3. Create a new API key and copy it.

### Step 3: Clone and Setup Environment
```bash
# Navigate to the project directory
cd telegram-ai-assistant

# Create a virtual environment (recommended)
python -m venv venv

# Activate the virtual environment
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# On Linux / macOS:
source venv/bin/activate

# Install dependencies
python -m pip install -r requirements.txt
```

### Step 4: Configure `.env`
Create a `.env` file in the root directory by copying `.env.example`:

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Open `.env` and fill in your credentials:

```ini
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
GEMINI_API_KEY=AIzaSyYourSecretKeyHere
GEMINI_MODEL=gemini-3.7-flash
DATABASE_URL=sqlite+aiosqlite:///./bot.db
ADMIN_USER_ID=123456789
MAX_HISTORY_MESSAGES=20
RATE_LIMIT_MESSAGES_PER_MINUTE=10
REQUEST_TIMEOUT_SECONDS=30
```

> **How to find your Telegram User ID for `ADMIN_USER_ID`:**
> Send `/start` to [@userinfobot](https://t.me/userinfobot) on Telegram to get your numeric ID.

### Step 5: Run the Bot Locally
```bash
python run.py
```
or:
```bash
python -m app.main
```

When started, you will see:
```text
2026-09-08 22:15:00 [INFO] app.main (main.py:55): Bot started successfully! (Model: gemini-3.7-flash, Max History: 20)
```

---

## 🧪 Running Automated Tests

Run the full pytest suite with:

```bash
python -m pytest -v
```

All tests run against an in-memory SQLite database and mock Gemini API calls. No live tokens or external networks are required during testing.

---

## 📂 Project Architecture

```
telegram-ai-assistant/
│
├── app/
│   ├── __init__.py
│   ├── main.py               # Bot entry point, middlewares, and lifecycle
│   ├── config.py             # Pydantic Settings & environment validation
│   ├── logging_config.py     # Structured logging & secret masking filter
│   │
│   ├── bot/                  # Telegram Bot layer (aiogram 3)
│   │   ├── __init__.py
│   │   ├── commands.py       # Telegram UI menu commands registration
│   │   ├── handlers.py       # Message, callback, and command handlers
│   │   ├── keyboards.py      # Inline and reply keyboard layouts
│   │   └── middlewares.py    # Rate limiter & user auto-registration
│   │
│   ├── ai/                   # AI integration layer (Google GenAI SDK)
│   │   ├── __init__.py
│   │   ├── gemini.py         # Async Gemini service with retries & timeouts
│   │   ├── prompts.py        # System instructions & personality rules
│   │   └── conversation.py   # Database to Gemini Content conversion
│   │
│   ├── database/             # Database access layer (SQLAlchemy Async)
│   │   ├── __init__.py
│   │   ├── models.py         # Declarative models (User, Message)
│   │   ├── database.py       # Engine, sessionmaker, and init_db()
│   │   └── repository.py     # Repositories for Users and Messages
│   │
│   └── services/             # Business logic layer
│       ├── __init__.py
│       ├── user_service.py   # User management & admin statistics
│       └── message_service.py# Conversation history management
│
├── tests/                    # Test suite
│   ├── __init__.py
│   ├── conftest.py           # In-memory async SQLite fixtures
│   ├── test_config.py        # Settings & token masking tests
│   ├── test_database.py      # CRUD, message history, and stats tests
│   ├── test_ai.py            # AI mocking, prompts, and error recovery tests
│   └── test_bot.py           # Message splitting, rate limiter, and admin tests
│
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore for DB, virtualenvs, and secrets
├── requirements.txt          # Python dependencies
├── Dockerfile                # Docker container definition
├── docker-compose.yml        # Docker Compose service definition
├── README.md                 # Complete documentation
└── run.py                    # Root execution script
```

---

## 💬 Available Commands

### User Commands
| Command | Description |
| :--- | :--- |
| `/start` | Welcome message, capabilities overview, and quick-action menu |
| `/help` | Detailed guide on how to interact with the assistant |
| `/newchat` | Clears conversation context in memory to start a fresh topic |
| `/memory` | Checks conversation memory status and current stored context turns |
| `/settings` | Displays user profile info, active Gemini model, and rate limits |
| `/about` | Technical details, framework versions, and model information |

### Admin Commands (Restricted to `ADMIN_USER_ID`)
| Command | Description |
| :--- | :--- |
| `/stats` | View real-time user count, total message turns, and 24h active users |
| `/broadcast <message>` | Safely broadcast an announcement to all registered bot users |

---

## 🧠 How Conversation Memory Works

1. **Incoming Turn**: When a user sends a message, it is stored in the `messages` table with `role = "user"`.
2. **Context Window**: The bot loads the last `MAX_HISTORY_MESSAGES` (default 20) chronologically.
3. **Gemini Content Assembly**: Messages are structured into `types.Content` turns (`role="user"` / `role="model"`) and paired with the strict `system_instruction`.
4. **AI Generation**: Gemini receives the entire conversation context to provide relevant multi-turn follow-ups.
5. **Response Storage**: The AI response is saved with `role = "assistant"`.
6. **Reset Anytime**: If a user switches topics, running `/newchat` purges their conversation history from the database.

---

## 🤖 How to Change Gemini Model

You can switch the AI model simply by updating `GEMINI_MODEL` in your `.env`:

```ini
# Default recommended fast model:
GEMINI_MODEL=gemini-3.7-flash

# For complex reasoning and deep technical questions:
GEMINI_MODEL=gemini-2.5-pro

# For ultra high-throughput / low latency:
GEMINI_MODEL=gemini-3.5-flash-lite
```

Restart the bot after changing `.env`.

---

## 🚢 Deployment Options

### Option 1: Docker & Docker Compose (Recommended for VPS)
```bash
# 1. Ensure .env is created and configured
cp .env.example .env

# 2. Build and start the container in background
docker compose up -d --build

# 3. View logs
docker compose logs -f
```

### Option 2: Deploying to Railway
1. Fork or push your repository to GitHub.
2. Log in to [Railway.app](https://railway.app/) and click **New Project** → **Deploy from GitHub repo**.
3. Under **Variables**, add:
   - `TELEGRAM_BOT_TOKEN`
   - `GEMINI_API_KEY`
   - `GEMINI_MODEL`
   - `ADMIN_USER_ID`
4. Railway will automatically detect the `Dockerfile` and start polling.

### Option 3: Deploying to Render
1. Create a **Background Worker** on [Render.com](https://render.com/).
2. Connect your GitHub repository.
3. Set **Runtime** to `Python 3`.
4. Set **Build Command**: `pip install -r requirements.txt`
5. Set **Start Command**: `python run.py`
6. Add your environment variables in the **Environment** tab.

---

## 🛠️ Troubleshooting

### 1. `TELEGRAM_BOT_TOKEN is missing!`
- **Solution**: Check that your `.env` file is named exactly `.env` (not `.env.txt`) and contains a valid `TELEGRAM_BOT_TOKEN`.

### 2. `Resource Exhausted (429)` or Rate Limiting
- **Solution**: The bot will automatically retry with exponential backoff. If your Google API quota is exceeded, consider upgrading your Google AI Studio plan or increasing request intervals.

### 3. Markdown Parse Errors
- **Solution**: The bot is equipped with an automated fallback. If a complex character sequence fails Telegram's Markdown parser, the message is automatically resent as clean plain text without dropping content.

### 4. Database Lock in SQLite
- **Solution**: The bot uses `aiosqlite` with connection pooling and commit contexts. For extremely high concurrency (>10,000 active users), simply change `DATABASE_URL` in `.env` to PostgreSQL (e.g. `postgresql+asyncpg://user:pass@host/dbname`).

---

## 📜 License
This project is open-source and available under the MIT License.
