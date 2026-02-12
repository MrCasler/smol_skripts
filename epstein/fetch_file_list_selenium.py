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
    import undetected_chromedriver as uc  # type: ignore
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
MAX_PAGES = 50  # Limit pages for testing
MAX_PAGES = 50  # Limit pages for testing


def find_brave_binary():
    for path in [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Brave.app/Contents/MacOS/Brave Browser",
        os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ]:
        if os.path.exists(path):
            return path
    return None

def extract_file_ids_from_page(html: str) -> list:
    """Extract file IDs and dataset numbers from page HTML.
    Returns list of tuples: [(file_id, dataset), ...]
    Example: [('EFTA00024813', 'DataSet 8'), ...]
    """
    results = []
    # Pattern to match: <a href=".../DataSet 8/EFTA00024813.pdf">EFTA00024813.pdf</a> - DataSet 8
    # Extract both the file ID and dataset from the href
    pattern = r'href="[^"]*/(DataSet\s+\d+)/EFTA(\d+)\.pdf"[^>]*>EFTA\2\.pdf</a>\s*-\s*\1'
    matches = re.findall(pattern, html)
    for dataset, file_id in matches:
        results.append((file_id, dataset))
    
    # Fallback: if the above pattern doesn't match, try simpler patterns
    if not results:
        # Pattern 1: Extract from href path
        pattern1 = r'/(DataSet\s+\d+)/EFTA(\d+)\.pdf'
        matches1 = re.findall(pattern1, html)
        for dataset, file_id in matches1:
            results.append((file_id, dataset))
        
        # Pattern 2: Extract from text "EFTA00024813.pdf - DataSet 8"
        if not results:
            pattern2 = r'EFTA(\d+)\.pdf[^<]*-\s*(DataSet\s+\d+)'
            matches2 = re.findall(pattern2, html)
            for file_id, dataset in matches2:
                results.append((file_id, dataset))
    
    return results


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
        print(f"Using Brave: {brave_path}")
    uc_cache = Path.home() / "Library/Application Support/undetected_chromedriver"
    driver = None
    for attempt in range(2):
        try:
            # Create fresh ChromeOptions each attempt (undetected_chromedriver forbids reusing options)
            options = uc.ChromeOptions()
            if brave_path:
                options.binary_location = brave_path
            _debug_log(f"uc.Chrome() attempt {attempt+1}", None, "H1")
            # Specify version_main=143 to match Brave 143 (undetected_chromedriver defaults to latest which may be too new)
            driver = uc.Chrome(options=options, version_main=143)
            _debug_log("uc.Chrome() succeeded after SSL fix", {"runId": "post-fix", "attempt": attempt+1}, "H1")
            break
        except OSError as e:
            _debug_log("uc.Chrome() OSError", {"errno": getattr(e, "errno", None), "error": str(e), "attempt": attempt+1}, "H1")
            if getattr(e, "errno", None) == 86 or "Bad CPU type" in str(e):
                if attempt == 0 and uc_cache.exists():
                    print("Removing wrong-architecture cached chromedriver, retrying...")
                    shutil.rmtree(uc_cache, ignore_errors=True)
                    continue
            raise
        except Exception as e:
            _debug_log("uc.Chrome() exception", {"type": type(e).__name__, "error": str(e), "attempt": attempt+1}, "H1")
            raise
    if driver is None:
        raise RuntimeError("Failed to create Chrome driver after retries")
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
        # Find search, run search - use specific IDs from the HTML structure
        try:
            print("Waiting for search box...")
            search_el = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.ID, "searchInput"))
            )
            print("Found search box, entering query...")
            search_el.clear()
            search_el.send_keys(DEFAULT_SEARCH)
            time.sleep(1)
            
            # Use the search button with ID="searchButton"
            print("Looking for search button...")
            submit = WebDriverWait(driver, 18).until(
                EC.presence_of_element_located((By.ID, "searchButton"))
            )
            # Scroll into view
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit)
            time.sleep(0.5)
            
            # Try regular click first, fallback to JavaScript click
            try:
                WebDriverWait(driver, 9).until(EC.element_to_be_clickable(submit))
                submit.click()
            except Exception:
                print("Regular click failed, trying JavaScript click...")
                driver.execute_script("arguments[0].click();", submit)
            
            print("Search submitted, waiting for results...")
            # Wait for search results to load - look for EFTA IDs or result indicators
            try:
                # Wait for any element containing "EFTA" or result indicators
                WebDriverWait(driver, 15).until(
                    lambda d: "EFTA" in d.page_source or 
                    len(d.find_elements(By.XPATH, "//*[contains(text(), 'EFTA')]")) > 0 or
                    len(d.find_elements(By.XPATH, "//*[contains(@class, 'result') or contains(@class, 'search')]")) > 0
                )
                print("Results page loaded")
            except TimeoutException:
                print("Warning: Results may not have loaded, continuing anyway...")
            time.sleep(2)  # Extra wait for dynamic content
        except (TimeoutException, NoSuchElementException) as e:
            print(f"Could not find search elements: {e}")
            print("Manually run a search in the browser, then press Enter here.")
            input()
        
        all_files = {}  # Dict: {file_id: dataset} to track unique files
        page = 1
        while page <= MAX_PAGES:
            # Wait a moment for page to stabilize
            time.sleep(1)
            html = driver.page_source
            file_data = extract_file_ids_from_page(html)
            
            # Add new files (file_id, dataset tuples)
            new_count = 0
            for file_id, dataset in file_data:
                if file_id not in all_files:
                    all_files[file_id] = dataset
                    new_count += 1
            
            print(f"  Page {page}: {new_count} new IDs (total {len(all_files)})")
            
            # Debug: show a snippet of HTML if no IDs found
            if not file_data and page == 1:
                print(f"  Debug: Page source length: {len(html)} chars")
                if "EFTA" in html:
                    # Find where EFTA appears
                    idx = html.find("EFTA")
                    snippet = html[max(0, idx-100):min(len(html), idx+200)]
                    print(f"  Debug: Found 'EFTA' in HTML, snippet: ...{snippet}...")
                else:
                    print("  Debug: 'EFTA' not found in page source")
            
            if not file_data:
                if page == 1:
                    print("  No file IDs found on first page. The search may need more time or the page structure changed.")
                    print("  Check the browser window - if results are visible, press Enter to continue anyway.")
                    input()
                    # Try one more time after user confirmation
                    html = driver.page_source
                    file_data = extract_file_ids_from_page(html)
                    if file_data:
                        for file_id, dataset in file_data:
                            if file_id not in all_files:
                                all_files[file_id] = dataset
                        print(f"  Found {len(file_data)} IDs after waiting")
                    else:
                        break
                else:
                    break
            
            # Save progress periodically (every 10 pages) and before pagination
            if page % 10 == 0:
                lines = []
                for file_id, dataset in all_files.items():
                    lines.append(f"EFTA{file_id}.pdf - {dataset}")
                lines.sort(key=lambda x: int(re.search(r'EFTA(\d+)', x).group(1)))
                OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
                print(f"  Progress saved: {len(lines)} files so far")
            
            # Check page limit
            if page >= MAX_PAGES:
                print(f"\nReached page limit ({MAX_PAGES}), stopping...")
                break
            
            # Pagination: look for the "Next" link with class "usa-pagination__next-page"
            try:
                next_btn = driver.find_element(By.XPATH, "//a[contains(@class, 'usa-pagination__next-page')]")
                # Check if it's disabled (shouldn't be, but check anyway)
                if next_btn.get_attribute("aria-disabled") == "true" or "disabled" in (next_btn.get_attribute("class") or ""):
                    break
                # Scroll into view and click
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                time.sleep(0.5)
                try:
                    next_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(3)  # Wait for next page to load
                page += 1
            except NoSuchElementException:
                print("  No 'Next' button found, reached end of results")
                break
        # Format as "EFTA00024813.pdf - DataSet 8" and sort numerically by file ID
        lines = []
        for file_id, dataset in all_files.items():
            lines.append(f"EFTA{file_id}.pdf - {dataset}")
        
        # Sort numerically by the file ID number (preserving leading zeros in output)
        lines.sort(key=lambda x: int(re.search(r'EFTA(\d+)', x).group(1)))
        
        OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nWrote {len(lines)} file IDs to {OUTPUT_FILE}")
        print("Run: python download_epstein_files.py")
    finally:
        driver.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
