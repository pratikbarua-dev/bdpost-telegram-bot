# Bangladesh Post Telegram Tracking Bot

A Telegram bot to track Bangladesh Post parcels with automated background polling and real-time status update notifications.

---

## 🌟 Features

- **Multi-tracking Support**: Track or query status for multiple parcels at once (e.g. `/track NUM1 NUM2` or `/track NUM1, NUM2`).
- **Real-time Tracking**: Check current parcel status with `/status <tracking_number...>`.
- **Automated Notifications**: Subscribe with `/track <tracking_number...>` to receive notifications whenever a new event appears.
- **Smart Event Deduplication**: SHA-256 event hashing prevents duplicate notifications.
- **Efficient Background Polling**: Aggregates unique tracking numbers so that multiple subscribers do not cause duplicate upstream requests to Bangladesh Post.
- **List & Manage Subscriptions**: View active parcels with `/my` and unsubscribe with `/stop <tracking_number...>` or `/stop all`.

---

## 📋 Technology Stack

- **Python 3.12+**
- **python-telegram-bot[job-queue]**
- **httpx**
- **beautifulsoup4**
- **SQLite**
- **python-dotenv**

---

## 🚀 Local Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd bdpost-telegram-bot
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Copy or edit `.env`:
   ```env
   BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
   POLL_INTERVAL=1800
   DATABASE_PATH=bdpost.db
   ```

5. **Run the bot:**
   ```bash
   python bot.py
   ```

---

## 🧪 Running Tests

Run unit tests with:
```bash
python -m unittest discover -s tests
```

---

## ☁️ Deployment on PythonAnywhere

1. **Upload/Clone project** to `/home/USERNAME/bdpost-telegram-bot/`.
2. **Create a virtual environment** in PythonAnywhere Bash console:
   ```bash
   mkvirtualenv --python=/usr/bin/python3.12 bdpost-bot
   pip install -r requirements.txt
   ```
3. **Configure `.env`** with your Telegram Bot token.
4. **Set up Always-on Task** in PythonAnywhere Dashboard:
   - Command: `/home/USERNAME/.virtualenvs/bdpost-bot/bin/python /home/USERNAME/bdpost-telegram-bot/bot.py`
5. **Monitor logs** from the Always-on task log tab.
