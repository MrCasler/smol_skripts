#!/usr/bin/env python3
"""
Optional: fetch file IDs from justice.gov/epstein using a real browser and write file_ids.txt.
Run this once to populate file_ids.txt; then use download_epstein_files.py (cookies + file list).

Uses undetected-chromedriver so the driver version matches Brave (Chromium).
You only need Chrome/Chromium for this script; cookie export can be from Brave or Firefox.
"""

import os
import re
import time
import json
import shutil
from pathlib import Path

# #region agent log
def _debug_log(msg, data=None, hypothesis_id=None):
    try:
        payload = {"message": msg, "timestamp": time.time(), "location": "fetch_file_list_selenium.py"}
        if data is not None:
            payload["data"] = data
        if hypothesis_id is not None:
            payload["hypothesisId"] = hypothesis_id
        with open("/Users/casler/Desktop/smol_skripts/.cursor/debug.log", "a") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass
# #endregion

# Patch urlopen BEFORE importing undetected_chromedriver (patcher does "from urllib.request import urlopen" at load time)
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
    _debug_log("patched urlopen before uc import", {"runId": "post-fix"}, "H4")
except ImportError:
    import sys
    print("Tip: pip install certifi — avoids SSL errors on macOS.", file=sys.stderr)

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    HAS_UC = True
except ImportError:
    HAS_UC = False

BASE_URL = "https://www.justice.gov/epstein/"
DEFAULT_SEARCH = "No images produced"
OUTPUT_FILE = Path(__file__).parent / "file_ids.txt"


def find_brave_binary():
    for path in [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Brave.app/Contents/MacOS/Brave Browser",
        os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ]:
        if os.path.exists(path):
            return path
    return None


def extract_file_ids_from_page(html: str) -> set:
    """Extract unique EFTA IDs from page HTML."""
    pattern = r"EFTA(\d+)"
    return set(re.findall(pattern, html))


def main():
    if not HAS_UC:
        print("Install undetected-chromedriver: pip install undetected-chromedriver")
        return 1
    # #region agent log
    try:
        import ssl
        certifi_where = None
        try:
            import certifi
            certifi_where = certifi.where()
        except ImportError:
            pass
        _debug_log("SSL/cert state before uc.Chrome", {
            "SSL_CERT_FILE": os.environ.get("SSL_CERT_FILE"),
            "REQUESTS_CA_BUNDLE": os.environ.get("REQUESTS_CA_BUNDLE"),
            "certifi_available": certifi_where is not None,
            "certifi_where": certifi_where,
        }, "H2")
        _debug_log("about to call uc.Chrome (patcher will HTTPS fetch)", None, "H1")
    except Exception as e:
        _debug_log("instrumentation error", {"error": str(e)}, "H5")
    # #endregion
    # Ensure patcher module uses SSL context with certifi (patch its urlopen reference directly)
    try:
        import ssl
        import urllib.request
        import certifi
        import undetected_chromedriver.patcher as _patcher_mod
        _ctx = ssl.create_default_context(cafile=certifi.where())
        _orig = urllib.request.urlopen
        def _wrap(*a, **k):
            if "context" not in k:
                k["context"] = _ctx
            return _orig(*a, **k)
        _patcher_mod.urlopen = _wrap
        _debug_log("patched patcher.urlopen directly", {"runId": "post-fix"}, "H4")
    except (ImportError, AttributeError):
        pass
    print("Fetching file list from justice.gov/epstein (browser will open)")
    print("Pass age verification in the browser if prompted, then the script will search and collect IDs.\n")
    options = uc.ChromeOptions()
    brave_path = find_brave_binary()
    if brave_path:
        options.binary_location = brave_path
        print(f"Using Brave: {brave_path}")
    uc_cache = Path.home() / "Library/Application Support/undetected_chromedriver"
    for attempt in range(2):
        try:
            driver = uc.Chrome(options=options)
            break
        except OSError as e:
            if getattr(e, "errno", None) == 86 or "Bad CPU type" in str(e):
                if attempt == 0 and uc_cache.exists():
                    print("Removing wrong-architecture cached chromedriver, retrying...")
                    shutil.rmtree(uc_cache, ignore_errors=True)
                    continue
            raise
    _debug_log("uc.Chrome() succeeded after SSL fix", {"runId": "post-fix"}, "H1")
    try:
        driver.get(BASE_URL)
        time.sleep(2)
        # Optional: try to click age verification
        try:
            yes_btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Yes') or contains(., 'yes')]"))
            )
            yes_btn.click()
            time.sleep(2)
        except (TimeoutException, NoSuchElementException):
            pass
        # Find search, run search
        try:
            search_el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @type='text']"))
            )
            search_el.clear()
            search_el.send_keys(DEFAULT_SEARCH)
            time.sleep(0.5)
            submit = driver.find_element(By.XPATH, "//button[@type='submit'] | //input[@type='submit'] | //*[contains(text(),'Search')]")
            submit.click()
            time.sleep(3)
        except (TimeoutException, NoSuchElementException):
            print("Could not find search box. Manually run a search in the browser, then press Enter here.")
            input()
        all_ids = set()
        page = 1
        while True:
            html = driver.page_source
            ids = extract_file_ids_from_page(html)
            new_ids = ids - all_ids
            all_ids |= ids
            print(f"  Page {page}: {len(new_ids)} new IDs (total {len(all_ids)})")
            if not ids:
                break
            try:
                next_btn = driver.find_element(By.XPATH, "//a[contains(text(),'Next') or contains(text(),'next')]")
                if next_btn.get_attribute("aria-disabled") == "true" or "disabled" in (next_btn.get_attribute("class") or ""):
                    break
                next_btn.click()
                time.sleep(2)
                page += 1
            except NoSuchElementException:
                break
        lines = sorted(f"EFTA{i}" for i in sorted(int(x) for x in all_ids))
        OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nWrote {len(lines)} file IDs to {OUTPUT_FILE}")
        print("Run: python download_epstein_files.py")
    finally:
        driver.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
