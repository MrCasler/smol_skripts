# Content Downloader

A simple script to download videos and media from **YouTube, Instagram, TikTok, and X.com (Twitter)**.

## Features

- 🎬 Download videos from YouTube, Instagram, TikTok, and X.com
- 📸 Download Instagram posts, reels, stories, and IGTV videos
- 🗂️ Automatically organizes downloads by platform
- 🔍 Auto-detects platform from URL
- 📱 Simple command-line interface

## Setup

### 1. Install yt-dlp

**Using Homebrew (recommended for macOS):**
```bash
brew install yt-dlp
```

**Or using pip:**
```bash
pip install yt-dlp
```

### 2. Make the script executable (optional)

```bash
chmod +x download_content.py
```

## Usage

### Run the script:

```bash
python3 download_content.py
```

Or if you made it executable:

```bash
./download_content.py
```

### Follow the prompts:

1. The script will ask for a URL
2. Paste your link from YouTube, Instagram, TikTok, or X.com
3. The content will be automatically downloaded to the `downloads/` folder

**Note:** For Instagram downloads, you'll need to use `download_with_cookies.py` and be logged into Instagram in your browser.

## Download Organization

Downloads are automatically organized by platform:

```
smol_skripts/
├── download_content.py
└── downloads/
    ├── youtube/     # YouTube videos
    ├── instagram/   # Instagram posts, reels, stories, IGTV
    ├── tiktok/      # TikTok videos
    └── x/           # X.com (Twitter) media
```

## Examples

### YouTube Video
```
URL: https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

### Instagram Post/Reel
```
URL: https://www.instagram.com/p/ABC123xyz/
URL: https://www.instagram.com/reel/ABC123xyz/
```
**Note:** Use `download_with_cookies.py` for Instagram - you must be logged in!

### TikTok Video
```
URL: https://www.tiktok.com/@user/video/1234567890
```

### X.com Post
```
URL: https://x.com/user/status/1234567890
```

## Alternative: Cookie-Based Downloader

**Required for Instagram!** Also use this if you encounter SSL errors or downloads fail (especially for TikTok and X.com):

```bash
python3 download_with_cookies.py
```

This script uses your browser's cookies to authenticate, which works better for some platforms.

**Requirements:**
- You must be logged into the platform in Brave, Chrome, or Safari
- The script will automatically try browsers in order: Brave → Chrome → Safari
- **Instagram downloads require this method** - Instagram needs authentication

## Troubleshooting

### "yt-dlp is not installed" error

Make sure yt-dlp is installed:
```bash
yt-dlp --version
```

If not installed, use one of the installation methods above.

### TikTok SSL Certificate Error

If you see `SSL: CERTIFICATE_VERIFY_FAILED`:

1. **Update yt-dlp:**
   ```bash
   brew upgrade yt-dlp
   ```

2. **Use the cookie version:**
   ```bash
   python3 download_with_cookies.py
   ```
   Make sure you're logged into TikTok in Brave, Chrome, or Safari first.

3. **Install browser cookie support:**
   ```bash
   pip install browser-cookie3
   ```

### TikTok Impersonation Warning

If you see warnings about impersonation:
- This is normal and usually doesn't prevent downloads
- The script now bypasses SSL verification to work around this
- If it still fails, use `download_with_cookies.py`

### Instagram Downloads Fail

- **Instagram requires authentication** - use `download_with_cookies.py` instead
- Make sure you're logged into Instagram in Brave, Chrome, or Safari
- The script will try Brave first (if you use Brave), then Chrome, then Safari
- Some posts may be private or restricted
- Instagram stories expire after 24 hours
- Update yt-dlp: `brew upgrade yt-dlp`

### X.com (Twitter) Downloads Fail

- Make sure the tweet/post is public
- Log into X.com in your browser first
- Use the cookie version: `python3 download_with_cookies.py`
- Some posts may be region-locked or have restricted media

### General Download Failures

- Check your internet connection
- Make sure the URL is valid and accessible
- Update yt-dlp: `brew upgrade yt-dlp`
- Try the alternative cookie-based script
- Some private or restricted content may not be downloadable

## Notes

- The script uses `yt-dlp`, a powerful command-line tool that supports many platforms
- YouTube videos are downloaded in the best available quality
- Instagram supports posts, reels, stories, and IGTV videos
- X.com posts will download all available media (videos, images)
- Downloaded files are named based on the video title or post ID
- **Instagram requires browser cookies** - always use `download_with_cookies.py` for Instagram
