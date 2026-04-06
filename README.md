# twitter-cleaner

Delete your entire Twitter/X history — tweets, replies, retweets, quotes, and likes — using your data archive and browser automation. No API key required.

## How it works

1. You download your Twitter data archive (or scrape your live profile) and point the tool at it.
2. The tool reads all tweet/like IDs and stores them in a local SQLite database.
3. A Playwright-controlled browser navigates to each item and deletes it.
4. Progress is saved after every deletion — you can stop and resume at any time.

---

## Setup

### Option A — quickstart script

```bash
python install.py
```

This creates a `.venv`, installs the package, and installs the Playwright browser automatically.

### Option B — manual

```bash
pip install -e .
playwright install chromium
```

### Configure credentials

Copy `.env.example` to `.env` and fill in your details:

```env
TWITTER_USERNAME=your_handle
TWITTER_PASSWORD=your_password
TWITTER_TOTP_SECRET=BASE32SECRET_IF_2FA_ENABLED   # optional
```

> The TOTP secret is the Base32 string you get when setting up an authenticator app (not the 6-digit code). Leave it blank if you don't use 2FA.

---

## Loading your Twitter history

You have two ways to load tweet/like IDs into the local database before deleting.

### Option A — parse a downloaded archive (recommended, gets full history)

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

Then parse it:

```bash
twitter-cleaner parse
```

By default this reads from `data/`. Pass `--archive-dir` to use a different location:

```bash
twitter-cleaner parse --archive-dir /path/to/archive/data
```

### Option B — scrape your live profile (limited to ~3200 tweets)

```bash
twitter-cleaner scrape
```

This scrolls your tweets and/or likes tabs in a browser and loads found IDs into the database. Twitter limits profile scraping to roughly your last 3200 tweets, so use the archive approach to get your full history.

Scrape only tweets or only likes:

```bash
twitter-cleaner scrape --no-likes    # tweets/replies only
twitter-cleaner scrape --no-tweets   # likes only
```

---

## Checking what was loaded

```bash
twitter-cleaner status
```

---

## Deleting your history

### Delete everything

```bash
twitter-cleaner delete
```

### Delete specific types

Use `--type` (repeatable) to target specific categories:

```bash
twitter-cleaner delete --type tweets     # tweets, replies, retweets, quotes
twitter-cleaner delete --type likes      # unlike all liked tweets
twitter-cleaner delete --type tweets --type likes
```

Available types: `tweets`, `replies`, `quotes`, `retweets`, `likes`

### Dry run (test without deleting)

```bash
twitter-cleaner delete --dry-run
```

The browser will open and navigate to each item but won't click Delete.

### Hide the browser (headless mode)

The browser is shown by default. To run headlessly in the background:

```bash
twitter-cleaner delete --headless
```

---

## Filtering — delete only certain posts

### By date

```bash
# Only delete posts from before 2023
twitter-cleaner delete --type tweets --before 2023-01-01

# Only delete posts from after 2020
twitter-cleaner delete --type tweets --after 2020-01-01

# Combine to target a date range
twitter-cleaner delete --type tweets --after 2020-01-01 --before 2023-01-01
```

### By content using an LLM

Use an LLM to classify each tweet and only delete the ones that match a description:

```bash
# Delete only tweets that look like angry or political posts
twitter-cleaner delete --type tweets \
  --filter "angry, political, or inflammatory posts" \
  --llm-provider openai \
  --llm-api-key sk-...

# Using Anthropic Claude instead
twitter-cleaner delete --type tweets \
  --filter "shitposts and low-effort jokes" \
  --llm-provider anthropic \
  --llm-api-key sk-ant-...

# Using OpenRouter (access to many models)
twitter-cleaner delete --type tweets \
  --filter "anything embarrassing" \
  --llm-provider openrouter \
  --llm-api-key sk-or-...
```

**Supported LLM providers:** `openai`, `anthropic`, `openrouter`

You can also set the API key via environment variable:
- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`
- OpenRouter: `OPENROUTER_API_KEY`

#### Specifying a model

```bash
twitter-cleaner delete --type tweets \
  --filter "low-effort jokes" \
  --llm-provider openai \
  --llm-model gpt-4o-mini
```

Defaults to a cheap model for each provider if `--llm-model` is omitted.

### Combining filters

```bash
# Delete only shitposts from before 2022
twitter-cleaner delete --type tweets \
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

The tool waits 3–6 seconds (randomised) between each deletion by default. Stealth mode (on by default) also adds periodic long pauses every ~50 actions to avoid rate-limiting.

Adjust delays:

```bash
twitter-cleaner delete --min-delay 5 --max-delay 10
```

Disable stealth mode pauses:

```bash
twitter-cleaner delete --no-stealth
```

---

## Notes

- **Session cookies** are saved to `.twitter_cleaner/session.json` so you only need to log in once per session expiry.
- The `.twitter_cleaner/` directory and `data/` directory are gitignored — your credentials and archive data won't be committed.
- LLM filtering sends tweet text to the API of your chosen provider. Don't use it if your tweets contain sensitive content you don't want leaving your machine — delete everything without filtering instead.
