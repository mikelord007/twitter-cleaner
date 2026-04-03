# twitter-cleaner

Delete your entire Twitter/X history — tweets, replies, retweets, quotes, and likes — using your data archive and browser automation. No API key required.

## How it works

1. You download your Twitter data archive and point the tool at it.
2. The tool reads all tweet/like IDs and stores them in a local SQLite database.
3. A Playwright-controlled browser navigates to each item and deletes it.
4. Progress is saved after every deletion — you can stop and resume at any time.

---

## Setup

### 1. Install dependencies

```bash
pip install -e .
playwright install chromium
```

### 2. Configure credentials

Copy `.env.example` to `.env` and fill in your details:

```env
TWITTER_USERNAME=your_handle
TWITTER_PASSWORD=your_password
TWITTER_TOTP_SECRET=BASE32SECRET_IF_2FA_ENABLED   # optional
```

> The TOTP secret is the Base32 string you get when setting up an authenticator app (not the 6-digit code). Leave it blank if you don't use 2FA.

### 3. Download your Twitter archive

1. Go to **Settings → Your Account → Download an archive of your data**
2. Request the archive. Twitter will email you when it's ready (can take up to 24h).
3. Unzip the archive and copy the `data/` folder into this project directory:

```
twitter_del/
└── data/
    ├── tweets.js
    ├── like.js
    └── ...
```

---

## Usage

### Step 1 — Parse your archive

```bash
twitter-cleaner parse
```

This reads `tweets.js` and `like.js` and loads all IDs into the local database. Safe to re-run — it won't overwrite already-deleted items.

Check what was loaded:

```bash
twitter-cleaner status
```

### Step 2 — Delete everything

```bash
twitter-cleaner delete all
```

Or delete specific categories:

```bash
twitter-cleaner delete tweets   # tweets, replies, retweets, quotes
twitter-cleaner delete likes    # unlike all liked tweets
```

### Dry run (test without deleting)

```bash
twitter-cleaner delete all --dry-run
```

The browser will open and navigate to each item but won't click Delete.

### Show the browser (non-headless)

```bash
twitter-cleaner delete all --no-headless
```

Useful for debugging or watching progress.

---

## Filtering — delete only certain posts

### By date

```bash
# Only delete posts from before 2023
twitter-cleaner delete tweets --before 2023-01-01
```

### By content using an LLM

Use an LLM to classify each tweet and only delete the ones that match a description:

```bash
# Delete only tweets that look like angry or political posts
twitter-cleaner delete tweets \
  --filter "angry, political, or inflammatory posts" \
  --llm-provider openai \
  --llm-api-key sk-...

# Using Anthropic Claude instead
twitter-cleaner delete tweets \
  --filter "shitposts and low-effort jokes" \
  --llm-provider anthropic \
  --llm-api-key sk-ant-...
```

**Supported LLM providers:** `openai`, `anthropic`

You can also set the API key via environment variable:
- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`

### Combining filters

```bash
# Delete only shitposts from before 2022
twitter-cleaner delete tweets \
  --before 2022-01-01 \
  --filter "shitposts" \
  --llm-provider openai
```

---

## Resuming after interruption

Every run is automatically a resume. If you stop the process, re-run the same command and it will pick up where it left off. Already-deleted items are skipped automatically.

Tweets that no longer exist (already deleted manually, or deleted by Twitter) are marked as `skipped` — not failed.

---

## Managing the queue

```bash
# Show status
twitter-cleaner status

# Re-queue failed items for retry
twitter-cleaner reset --status failed

# Re-queue skipped items (if you want to retry unavailable ones)
twitter-cleaner reset --status skipped --type tweet
```

---

## Rate limiting

The tool waits 3–6 seconds (randomised) between each deletion by default. If it detects many consecutive failures (likely rate-limiting), it backs off automatically.

Adjust delays:

```bash
twitter-cleaner delete all --min-delay 5 --max-delay 10
```

---

## Notes

- **Session cookies** are saved to `.twitter_cleaner/session.json` so you only need to log in once per session expiry.
- The `.twitter_cleaner/` directory and `data/` directory are gitignored — your credentials and archive data won't be committed.
- LLM filtering sends tweet text to the API of your chosen provider. Don't use it if your tweets contain sensitive content you don't want leaving your machine — use keyword filtering (coming soon) instead, or just delete everything.
