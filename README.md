# InstaAutopost — Daily India News on Instagram

Automatically posts a daily "India News Highlights" card to Instagram at
**8:00 AM IST** using GitHub Actions and the official Instagram Graph API.

## How it works

1. **GitHub Actions** wakes up daily at 8:00 AM IST (also runnable manually).
2. `src/generate.py` pulls top headlines from Times of India, The Hindu,
   NDTV, and Indian Express RSS feeds, renders a 1080×1350 news card with
   Pillow, and writes a caption.
3. The image is committed to `posts/` so Instagram can fetch it from a
   public `raw.githubusercontent.com` URL (the API requires a public URL).
4. `src/publish.py` creates a media container and publishes it via the
   Instagram Graph API.

## One-time setup

### 1. Instagram account

Switch your account to a **Professional** account (Business or Creator):
Instagram app → Settings → Account type and tools → Switch to professional
account. This is free and required — personal accounts cannot use the API.

### 2. Meta developer app

1. Go to <https://developers.facebook.com> → **My Apps** → **Create App**.
2. Choose the **"Instagram"** use case (Instagram API with Instagram Login).
3. In the app dashboard, open **Instagram → API setup with Instagram login**.
4. Add your Instagram account under **Generate access tokens**, log in, and
   grant permissions (make sure `instagram_business_content_publish` is
   included).
5. Copy the **access token** shown — this is a long-lived token (60 days).
6. Note your **Instagram user ID** (shown next to your account in the same
   screen, or call `https://graph.instagram.com/me?fields=user_id,username&access_token=TOKEN`).

### 3. GitHub repository

1. Create a **public** repo on GitHub (public is required so
   `raw.githubusercontent.com` image URLs work) and push this project to it.
2. In the repo: **Settings → Secrets and variables → Actions**, add:
   - `IG_USER_ID` — your Instagram user ID
   - `IG_ACCESS_TOKEN` — the long-lived access token
3. (Optional, for automatic token renewal) add `GH_PAT` — a GitHub personal
   access token with permission to write repo secrets. The monthly
   `refresh-token.yml` workflow then keeps `IG_ACCESS_TOKEN` fresh forever.
   Without it, regenerate the token manually every ~60 days.

### 4. Test it

Run the workflow manually: **Actions → Daily Instagram news post → Run
workflow**. Check your Instagram feed.

## Local testing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/generate.py        # writes posts/YYYY-MM-DD.jpg + .txt
open posts/*.jpg              # preview the card
```

Publishing locally also works if you export `IG_USER_ID`, `IG_ACCESS_TOKEN`,
and `GITHUB_REPOSITORY=owner/repo` — but the image must already be pushed.

## Customizing

- **Posting time**: edit the cron in `.github/workflows/daily-post.yml`
  (cron is in UTC; IST = UTC+5:30).
- **News sources / count**: edit `FEEDS` in `src/news.py`.
- **Card design**: colors, fonts, and layout live in `src/card.py`.
- **Caption & hashtags**: `HASHTAGS` and `build_caption()` in `src/generate.py`.
