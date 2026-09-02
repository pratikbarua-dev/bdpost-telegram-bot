# Bangladesh Post & AliExpress Dual Tracking Telegram Bot

A Telegram bot to track Bangladesh Post parcels as well as AliExpress (Cainiao) shipments with automated handover upon arrival in Bangladesh.

---

## 🌟 Features

- **AliExpress + Bangladesh Post Dual Tracking**:
  - Automatically queries Cainiao's global tracking endpoint for international legs.
  - Automatically switches to Bangladesh Post once the parcel reaches Bangladesh/local sorting office (`Arrived at post office`, `DHAKA AIRPORT SORTING OFFICE`, etc.).
  - Disables Cainiao requests after handover to save resources while keeping continuous shipment history.
- **Domestic & International Bangladesh Post Tracking**: Seamlessly handles both international (`search1.php`) and domestic Bangladesh-to-Bangladesh (`search2.php`) tracking.
- **Interactive Button-Based Interface**: Intuitive persistent reply menus, inline action buttons (`Refresh`, `Stop`, `Back to Home`), and guided prompts.
- **Multi-tracking Support**: Track or query status for multiple parcels at once (e.g. `/track NUM1 NUM2` or `NUM1, NUM2`).
- **Real-time Tracking**: Check current parcel status with quick buttons or `/status <tracking_number...>`.
- **Automated Notifications**: Real-time notifications for both Cainiao international milestones and Bangladesh Post local events.
- **Auto-Stop on Delivery**: Once a parcel is delivered, notifications are finalized and tracking is automatically completed.
- **Smart Event Deduplication**: Deterministic SHA-256 event hashing prevents duplicate notifications across both providers.
- **Keep-Alive Ping Endpoint**: Includes a `/ping` and `/health` HTTP server to keep free cloud instances (e.g. Render) alive 24/7 with external uptime pingers.

---

## 📋 Technology Stack

- **Python 3.12+**
- **python-telegram-bot[job-queue]**
- **aiohttp** (Lightweight health & keep-alive ping web server)
- **httpx**
- **beautifulsoup4**
- **SQLite**
- **python-dotenv**

---

## 🚀 Local Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/pratikbarua-dev/bdpost-telegram-bot.git
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
   Copy `.env.example` to `.env`:
   ```env
   BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
   POLL_INTERVAL=1800
   DATABASE_PATH=bdpost.db
   PORT=10000
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

## ☁️ Deployment on Render (Free Web Service)

1. Go to [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** and select **Web Service**.
3. Connect your GitHub repository `bdpost-telegram-bot`.
4. Configure the service settings:
   - **Name**: `bdpost-telegram-bot`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
5. Under **Environment Variables**, add:
   - `BOT_TOKEN`: `Your Telegram Bot Token`
   - `POLL_INTERVAL`: `1800`
   - `DATABASE_PATH`: `bdpost.db`
   - `PYTHON_VERSION`: `3.12.0`
6. Click **Deploy Web Service**.

### 🔄 Keep Active 24/7 (Free Tier Sleep Prevention)
Render free web services spin down after 15 minutes of inactivity. To keep your bot active continuously:
1. Copy your Render service URL (e.g. `https://bdpost-telegram-bot.onrender.com`).
2. Go to a free monitor like [UptimeRobot](https://uptimerobot.com/) or [cron-job.org](https://cron-job.org/).
3. Add an HTTP monitor to ping your endpoint every 5–10 minutes:
   ```text
   https://bdpost-telegram-bot.onrender.com/ping
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
