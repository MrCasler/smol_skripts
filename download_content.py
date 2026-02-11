#!/usr/bin/env python3
"""
Simple content downloader for YouTube, Instagram, TikTok, and X.com
"""
import os
import sys
import re
from pathlib import Path
import subprocess


# Default download directory
DOWNLOAD_DIR = Path(__file__).parent / "downloads"


def detect_platform(url):
    """Detect which platform the URL is from"""
    url = url.lower()
    
    if re.search(r'(youtube\.com|youtu\.be)', url):
        return 'youtube'
    elif re.search(r'(instagram\.com)', url):
        return 'instagram'
    elif re.search(r'(tiktok\.com)', url):
        return 'tiktok'
    elif re.search(r'(twitter\.com|x\.com)', url):
        return 'x'
    else:
        return 'unknown'


def check_yt_dlp():
    """Check if yt-dlp is installed"""
    try:
        subprocess.run(['yt-dlp', '--version'], 
                      capture_output=True, 
                      check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def download_content(url, platform):
    """Download content using yt-dlp"""
    
    # Create platform-specific folder
    platform_dir = DOWNLOAD_DIR / platform
    platform_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📥 Downloading from {platform}...")
    print(f"📁 Saving to: {platform_dir}\n")
    
    # Configure yt-dlp options based on platform
    if platform == 'youtube':
        # For YouTube, download best quality
        cmd = [
            'yt-dlp',
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '--no-check-certificate',  # Bypass SSL issues
            '-o', str(platform_dir / '%(title)s.%(ext)s'),
            url
        ]
    elif platform == 'tiktok':
        # For TikTok, download video with SSL bypass and cookies
        cmd = [
            'yt-dlp',
            '--no-check-certificate',  # Bypass SSL certificate verification
            '--user-agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '-o', str(platform_dir / '%(title)s.%(ext)s'),
            url
        ]
    elif platform == 'instagram':
        # For Instagram, download posts, reels, stories, IGTV
        # Instagram often requires cookies, so we'll try without first
        cmd = [
            'yt-dlp',
            '--no-check-certificate',
            '--user-agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '--write-thumbnail',
            '-o', str(platform_dir / '%(uploader)s_%(id)s.%(ext)s'),
            url
        ]
    elif platform == 'x':
        # For X/Twitter, download all media (videos, images)
        cmd = [
            'yt-dlp',
            '--no-check-certificate',  # Bypass SSL issues
            '--user-agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '--write-thumbnail',
            '-o', str(platform_dir / '%(uploader)s_%(id)s.%(ext)s'),
            url
        ]
    
    try:
        result = subprocess.run(cmd, check=True)
        print(f"\n✅ Download complete! Saved to: {platform_dir}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Download failed!")
        
        # Provide platform-specific troubleshooting
        if platform == 'instagram':
            print("\n💡 Instagram troubleshooting:")
            print("   1. Instagram requires login - use download_with_cookies.py instead")
            print("   2. Make sure you're logged into Instagram in Brave or Firefox")
            print("   3. Some posts may be private or restricted")
            print("   4. Update yt-dlp: brew upgrade yt-dlp")
        elif platform == 'tiktok':
            print("\n💡 TikTok troubleshooting:")
            print("   1. Update yt-dlp: brew upgrade yt-dlp")
            print("   2. Install browser cookies support: pip install browser-cookie3")
            print("   3. Some TikTok videos may be region-locked or private")
            print("   4. Try download_with_cookies.py if this fails")
        elif platform == 'x':
            print("\n💡 X.com troubleshooting:")
            print("   1. Make sure the post is public")
            print("   2. Try logging into X.com in your browser first")
            print("   3. Update yt-dlp: brew upgrade yt-dlp")
            print("   4. Try download_with_cookies.py if this fails")
        
        return False


def main():
    """Main function"""
    
    print("=" * 60)
    print("🎬 Content Downloader")
    print("=" * 60)
    print("Supports: YouTube, Instagram, TikTok, X.com (Twitter)")
    print("=" * 60)
    
    # Check if yt-dlp is installed
    if not check_yt_dlp():
        print("\n❌ Error: yt-dlp is not installed!")
        print("\nTo install yt-dlp:")
        print("  brew install yt-dlp")
        print("  or")
        print("  pip install yt-dlp")
        sys.exit(1)
    
    # Get URL from user
    print("\n📎 Paste your link below:")
    url = input("URL: ").strip()
    
    if not url:
        print("❌ No URL provided!")
        sys.exit(1)
    
    # Detect platform
    platform = detect_platform(url)
    
    if platform == 'unknown':
        print(f"❌ Unsupported platform for URL: {url}")
        print("Supported platforms: YouTube, Instagram, TikTok, X.com")
        sys.exit(1)
    
    print(f"✓ Detected platform: {platform.upper()}")
    
    # Download content
    success = download_content(url, platform)
    
    if success:
        print("\n🎉 All done!")
    else:
        print("\n⚠️  Download encountered issues.")
        sys.exit(1)


if __name__ == "__main__":
    main()
