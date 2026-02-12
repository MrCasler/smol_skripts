#!/usr/bin/env python3
"""
Download files from justice.gov/epstein/

Flow:
  1. Opens browser (Brave via Selenium) for age verification
  2. Syncs cookies from the browser to a requests session
  3. Uses file_ids.txt for the list of files to download
  4. For each file ID: tries extensions until one returns a real file (not HTML), downloads it

The browser is only needed once for age verification. All downloads happen via
the requests session (fast, parallel-ready).
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import os
import shutil
from pathlib import Path
from urllib.parse import quote
import re
from typing import List, Dict, Optional
import json

# --- Selenium imports (for age verification only) ---
try:
    import ssl
    import urllib.request
    import certifi
    _orig_urlopen = urllib.request.urlopen
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    def _urlopen_with_certs(*args, **kwargs):
        if "context" not in kwargs:
            kwargs["context"] = _ssl_ctx
        return _orig_urlopen(*args, **kwargs)
    urllib.request.urlopen = _urlopen_with_certs
except ImportError:
    pass

try:
    import undetected_chromedriver as uc
    try:
        import undetected_chromedriver.patcher as _patcher_mod
        _patcher_mod.urlopen = _urlopen_with_certs
    except (AttributeError, ImportError, NameError):
        pass
    _HAS_UC = True
except ImportError:
    _HAS_UC = False

try:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    _HAS_SELENIUM = True
except ImportError:
    _HAS_SELENIUM = False


def find_brave_binary():
    for path in [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Brave.app/Contents/MacOS/Brave Browser",
        os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ]:
        if os.path.exists(path):
            return path
    return None


def _create_driver():
    """Create a browser driver for age verification."""
    if not _HAS_UC:
        raise RuntimeError("undetected_chromedriver is required. Install: pip install undetected-chromedriver")

    brave_path = find_brave_binary()
    if brave_path:
        print(f"Using Brave: {brave_path}")

    uc_cache = Path.home() / "Library/Application Support/undetected_chromedriver"
    import platform
    if platform.machine() == "arm64" and uc_cache.exists():
        shutil.rmtree(uc_cache, ignore_errors=True)

    for attempt in range(3):
        opts = uc.ChromeOptions()
        if brave_path:
            opts.binary_location = brave_path
        try:
            return uc.Chrome(options=opts, version_main=143)
        except OSError as e:
            if getattr(e, "errno", None) == 86 or "Bad CPU type" in str(e):
                print(f"Attempt {attempt+1}: Wrong CPU arch, removing cache...")
                shutil.rmtree(uc_cache, ignore_errors=True)
                for item in (Path.home() / "Library/Application Support").glob("undetected_chromedriver*"):
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                time.sleep(1)
                if attempt < 2:
                    continue
            raise
    raise RuntimeError("Failed to create driver after retries")


def get_cookies_via_browser(base_url: str) -> dict:
    """
    Open a browser, navigate to the site, handle age verification,
    and return the cookies as a dict {name: value}.
    """
    if not _HAS_SELENIUM:
        raise RuntimeError("Selenium is required. Install: pip install selenium")

    print("\n--- Opening browser for age verification ---")
    driver = _create_driver()

    try:
        driver.get(base_url)
        time.sleep(2)

        # Handle age verification
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '18') or contains(text(), 'age')]"))
            )
            print("Age verification detected. Looking for 'Yes' button...")
            try:
                yes_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Yes') or contains(text(), 'yes')]")
                yes_btn.click()
                print("Clicked 'Yes'.")
                time.sleep(2)
            except NoSuchElementException:
                try:
                    yes_btn = driver.find_element(By.ID, "age-yes")
                    yes_btn.click()
                    time.sleep(2)
                except NoSuchElementException:
                    print("Could not auto-click. Please verify age in the browser.")
                    input("Press Enter after verifying age...")
        except TimeoutException:
            print("No age verification prompt detected.")

        # Handle CAPTCHA
        if 'captcha' in driver.page_source.lower() or 'robot' in driver.page_source.lower():
            print("CAPTCHA detected. Please solve it in the browser.")
            input("Press Enter after solving CAPTCHA...")

        time.sleep(2)

        # Collect all cookies
        cookies = {}
        for c in driver.get_cookies():
            cookies[c['name']] = c['value']

        print(f"Got {len(cookies)} cookies from browser.")

        # Save cookies to cookies_browser.json for future runs
        cookie_list = driver.get_cookies()
        cookies_path = Path(__file__).parent / "cookies_browser.json"
        with open(cookies_path, "w") as f:
            json.dump(cookie_list, f, indent=2)
        print(f"Saved browser cookies to {cookies_path}")

        return cookies

    finally:
        driver.quit()
        print("Browser closed.\n")


class EpsteinFileDownloader:
    def __init__(self, base_url: str = "https://www.justice.gov/epstein/",
                 download_dir: Optional[Path] = None):
        self.base_url = base_url
        self.session = requests.Session()

        retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://www.justice.gov/epstein/',
        })

        # Extensions to test for each file (order: most common first)
        self.file_extensions = [
            '.pdf', '.mp4', '.mov', '.avi', '.wmv', '.m4v', '.webm', '.flv', '.mkv',
            '.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac',
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp',
            '.txt', '.doc', '.docx', '.rtf',
            '.zip', '.rar', '.7z', '.gz',
            '.csv', '.xls', '.xlsx',
        ]

        self.download_dir = download_dir if download_dir is not None else Path("downloads")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        for ext in self.file_extensions:
            (self.download_dir / ext.lstrip('.')).mkdir(exist_ok=True)

    def set_cookies(self, cookies: dict):
        """Set cookies on the requests session (from browser)."""
        for name, value in cookies.items():
            self.session.cookies.set(name, value, domain=".justice.gov")
        print(f"Set {len(cookies)} cookies on requests session.")

    def load_cookies_from_file(self, path: str) -> bool:
        """Load cookies from cookies_browser.json (saved by previous browser session)."""
        try:
            with open(path, 'r') as f:
                cookie_list = json.load(f)
            for c in cookie_list:
                domain = c.get('domain', '.justice.gov')
                self.session.cookies.set(c['name'], c['value'], domain=domain, path=c.get('path', '/'))
            print(f"Loaded {len(cookie_list)} cookies from {path}")
            return True
        except Exception as e:
            print(f"Could not load cookies from {path}: {e}")
            return False

    def verify_cookies_work(self) -> bool:
        """Test if cookies allow access to actual files (not age verification page)."""
        # Try a known file URL
        test_url = f"{self.base_url}files/DataSet%208/EFTA00033115.mp4"
        try:
            resp = self.session.head(test_url, allow_redirects=True, timeout=10)
            ct = resp.headers.get('Content-Type', '').lower()
            cl = int(resp.headers.get('Content-Length', '0') or '0')
            # If it returns HTML (especially ~9KB), cookies aren't working
            if 'text/html' in ct and cl < 50000:
                return False
            # If it returns video or large content, cookies work
            if cl > 50000 or 'video' in ct or 'application/octet' in ct:
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def get_file_ids_from_file(path: str = "file_ids.txt") -> List[Dict]:
        """Load file IDs from file_ids.txt.
        Formats: 'EFTA00024813.pdf - DataSet 8' or 'EFTA00024813' or '00024813'
        """
        file_ids = []
        p = Path(path)
        if not p.exists():
            return file_ids
        for line in p.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Match: EFTA00024813.ext - DataSet N
            m = re.match(r'EFTA(\d+)\.\w+\s*-\s*DataSet\s+(\d+)', line)
            if m:
                file_ids.append({"full_id": f"EFTA{m.group(1)}", "dataset": int(m.group(2))})
                continue
            # Match: EFTA00024813 (optionally with extension)
            m = re.match(r'(EFTA\d+)', line)
            if m:
                file_ids.append({"full_id": m.group(1), "dataset": None})
                continue
            # Match: bare number
            m = re.match(r'(\d+)', line)
            if m:
                file_ids.append({"full_id": f"EFTA{m.group(1)}", "dataset": None})
        return file_ids

    def test_extension(self, file_id: str, dataset: int, extension: str) -> bool:
        """
        Test if a file exists with the given extension.
        Simple: GET first 2KB. If it's HTML → not a real file. If it's binary → real file.
        """
        dataset_encoded = quote(f"DataSet {dataset}")
        url = f"{self.base_url}files/{dataset_encoded}/{file_id}{extension}"
        try:
            resp = self.session.get(url, headers={'Range': 'bytes=0-2047'}, stream=True, timeout=15)
            if resp.status_code not in (200, 206):
                return False
            chunk = resp.content[:2048]
            resp.close()
            if not chunk or len(chunk) < 10:
                return False
            # Check if the content is an HTML page (age verification / 404 / error)
            try:
                text = chunk[:500].decode('utf-8', errors='ignore').lower().strip()
                if text.startswith(('<!doctype', '<html', '<!html')) or '<html' in text[:200]:
                    return False  # HTML error page
            except:
                pass  # Can't decode as text → it's binary → good
            return True
        except Exception:
            return False

    def find_and_download(self, file_id: str, dataset: int) -> Optional[str]:
        """
        Try each extension for the file. On first real hit, download it.
        Returns the extension on success, None on failure.
        """
        dataset_encoded = quote(f"DataSet {dataset}")

        for ext in self.file_extensions:
            if not self.test_extension(file_id, dataset, ext):
                continue

            # Found a real file — download it
            url = f"{self.base_url}files/{dataset_encoded}/{file_id}{ext}"
            try:
                resp = self.session.get(url, stream=True, timeout=60)
                resp.raise_for_status()

                # Double-check first chunk isn't HTML
                first_chunk = next(resp.iter_content(chunk_size=4096), None)
                if not first_chunk:
                    continue
                try:
                    text = first_chunk[:500].decode('utf-8', errors='ignore').lower().strip()
                    if text.startswith(('<!doctype', '<html')) or '<html' in text[:200]:
                        resp.close()
                        continue
                except:
                    pass

                base_id = file_id if file_id.startswith("EFTA") else f"EFTA{file_id}"
                filename = f"{base_id}{ext}"
                save_path = self.download_dir / ext.lstrip('.') / filename
                with open(save_path, 'wb') as f:
                    f.write(first_chunk)
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                print(f"    ✓ {filename} ({ext})")
                return ext

            except Exception as e:
                print(f"    ✗ Error downloading {file_id}{ext}: {e}")
                continue

            time.sleep(0.05)

        return None

    def process_file_list(self, file_infos: List[Dict]) -> Dict:
        """Process all files: for each, try the hinted dataset (or all 1-10), and all extensions."""
        stats = {"total": len(file_infos), "downloaded": 0, "not_found": 0, "failed": 0}

        for i, info in enumerate(file_infos, 1):
            fid = info["full_id"]
            ds_hint = info.get("dataset")
            print(f"[{i}/{stats['total']}] {fid} (dataset hint: {ds_hint or 'none'})...")

            found = False
            datasets_to_try = [ds_hint] if ds_hint else range(1, 11)
            for ds in datasets_to_try:
                ext = self.find_and_download(fid, ds)
                if ext:
                    stats["downloaded"] += 1
                    found = True
                    break
                time.sleep(0.1)

            if not found:
                stats["not_found"] += 1
                print(f"    — no valid file found")
            time.sleep(0.3)

        return stats


def main():
    print("=" * 60)
    print("Epstein Files Downloader")
    print("=" * 60)

    base_url = "https://www.justice.gov/epstein/"
    download_dir = Path(__file__).parent / "downloads"
    downloader = EpsteinFileDownloader(base_url=base_url, download_dir=download_dir)

    # --- Step 1: Get valid cookies ---
    # Try saved browser cookies first
    cookies_path = Path(__file__).parent / "cookies_browser.json"
    have_cookies = False

    if cookies_path.exists():
        downloader.load_cookies_from_file(str(cookies_path))
        print("Testing if saved cookies still work...")
        if downloader.verify_cookies_work():
            print("Saved cookies work! Skipping browser.\n")
            have_cookies = True
        else:
            print("Saved cookies expired or invalid.\n")

    if not have_cookies:
        print("Need fresh cookies from browser (age verification required).")
        cookies = get_cookies_via_browser(base_url)
        downloader.set_cookies(cookies)
        if downloader.verify_cookies_work():
            print("Browser cookies verified — access works!\n")
            have_cookies = True
        else:
            print("WARNING: Cookies from browser don't seem to work.")
            print("The site may require specific cookies. Trying anyway...\n")

    # --- Step 2: Load file IDs ---
    file_ids_path = Path(__file__).parent / "file_ids.txt"
    if not file_ids_path.exists():
        file_ids_path.write_text(
            "# Add one EFTA file ID per line (e.g. EFTA00024813)\n"
            "# Or run fetch_file_list_selenium.py to populate this file.\n",
            encoding="utf-8",
        )
        print(f"Created {file_ids_path} — add file IDs, then run again.")
        return

    file_infos = downloader.get_file_ids_from_file(str(file_ids_path))
    if not file_infos:
        print("No file IDs found in file_ids.txt. Add IDs or run fetch_file_list_selenium.py.")
        return

    print(f"Loaded {len(file_infos)} file IDs from {file_ids_path}\n")

    # --- Step 3: Download ---
    stats = downloader.process_file_list(file_infos)

    print(f"\n{'=' * 60}")
    print(f"Done! Downloaded: {stats['downloaded']} | Not found: {stats['not_found']} | Failed: {stats['failed']}")
    print(f"{'=' * 60}")

    summary_path = download_dir / "download_summary.json"
    with open(summary_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"Summary saved to {summary_path}")


if __name__ == "__main__":
    main()
