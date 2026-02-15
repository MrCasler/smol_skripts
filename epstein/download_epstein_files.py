#!/usr/bin/env python3
"""
Epstein Files Downloader — justice.gov/epstein/

Downloads PDF files from the DOJ Epstein document repository.

Modes:
  [1] Download ALL        — Search "No images produced", paginate all pages, download every PDF.
  [2] Journalist (auto)   — Search curated keywords (names, violence, evidence) and save
                             the first N files per keyword. Generates a journalist_report.json.
  [3] File list            — Download from an existing file_ids.txt (no browser search needed).
  [4] Custom search        — Type your own query, choose how many files to download.

How it works:
  1. Opens Brave browser (Selenium + undetected-chromedriver) for age verification.
  2. Syncs browser cookies → a Python `requests` session for fast downloads.
  3. Searches the site via the browser, collects EFTA file IDs from result pages.
  4. Downloads each file as PDF via the requests session (with cookie auth).

Dependencies:
  pip install requests selenium undetected-chromedriver certifi
"""

# ── Imports ───────────────────────────────────────────────────────────────────

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import os
import shutil
from pathlib import Path
from urllib.parse import quote
import re
from typing import List, Dict, Optional, Set
import json

# #region agent log
_SCRIPT_DIR = Path(__file__).resolve().parent
DEBUG_LOG_PATH = _SCRIPT_DIR / ".cursor" / "debug.log"
DEBUG_LOG_FALLBACK = _SCRIPT_DIR / "downloads" / "debug.log"
def _debug_log(message: str, data: dict, hypothesis_id: str = ""):
    import time as _t
    payload = {"timestamp": int(_t.time() * 1000), "location": "download_epstein_files", "message": message, "data": data, "hypothesisId": hypothesis_id}
    line = json.dumps(payload) + "\n"
    for path in (DEBUG_LOG_PATH, DEBUG_LOG_FALLBACK):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a") as f:
                f.write(line)
        except Exception:
            pass
# #endregion

# ── SSL / Chromedriver patches ────────────────────────────────────────────────
# Fix macOS Python SSL cert errors before any chromedriver imports.

try:
    import ssl
    import urllib.request
    import certifi

    _original_urlopen = urllib.request.urlopen
    _ssl_context = ssl.create_default_context(cafile=certifi.where())

    def _urlopen_with_certs(*args, **kwargs):
        """Wrapper that injects a proper SSL context (macOS fix)."""
        if "context" not in kwargs:
            kwargs["context"] = _ssl_context
        return _original_urlopen(*args, **kwargs)

    urllib.request.urlopen = _urlopen_with_certs
except ImportError:
    pass  # certifi missing; SSL errors may occur

# Import undetected-chromedriver (patches its internal urlopen too).
try:
    import undetected_chromedriver as uc
    try:
        import undetected_chromedriver.patcher as _uc_patcher
        _uc_patcher.urlopen = _urlopen_with_certs  # type: ignore[name-defined]
    except (AttributeError, ImportError, NameError):
        pass
    _HAS_UC = True
except ImportError:
    _HAS_UC = False

# Selenium imports.
try:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    _HAS_SELENIUM = True
except ImportError:
    _HAS_SELENIUM = False


# ── Journalist keyword lists ──────────────────────────────────────────────────
# Curated search terms grouped by category.
# Each keyword becomes a separate site search; results are tagged + ranked.

HIGH_PROFILE_NAMES = [
    "Maxwell", "Ghislaine", "Prince Andrew", "Andrew", "Clinton", "Bill Clinton",
    "Trump", "Donald Trump", "Dershowitz", "Alan Dershowitz",
    "Wexner", "Les Wexner", "Brunel", "Jean-Luc Brunel",
    "Richardson", "Bill Richardson", "Mitchell", "George Mitchell",
    "Dubin", "Glenn Dubin", "Eva Dubin", "Kellen", "Sarah Kellen",
    "Nadia Marcinkova", "Marcinkova", "Adriana Ross", "Lesley Groff",
    "Alfredo Rodriguez", "Rodriguez", "Virginia Giuffre", "Giuffre",
    "Roberts", "Virginia Roberts", "Johanna Sjoberg", "Sjoberg",
    "Courtney Wild", "Annie Farmer", "Maria Farmer",
    "Epstein", "Jeffrey Epstein", "Gates", "Bill Gates", "Elon Musk", "Musk", "Jeff Bezos", "Larry Ellison", "Michael Bloomberg",
]

VIOLENT_KEYWORDS = [
   "assault", "rape", "abuse", "abused", "force", "forced", "threat",
    "threaten", "minor", "minors", "underage", "child", "children",
    "victim", "victims", "trafficking", "trafficked", "recruit",
    "recruited", "massage", "sexual", "molest", "coerce", "coerced",
    "blackmail", "intimidat", "silence", "silenced", "hush", "nude", "naked", "nudity", "nakedness", "pornography", "pornographic", "porn"
    "no limit", "map",
]

EVIDENCE_KEYWORDS = [
   "flight log", "flight", "Lolita Express", "Little St. James",
    "island", "New York", "Manhattan", "Palm Beach", "New Mexico",
    "Zorro Ranch", "Paris", "London", "testimony", "deposition",
    "sworn", "statement", "affidavit", "exhibit", "evidence",
    "photograph", "photo", "video", "recording", "tape",
    "diary", "journal", "email", "letter", "document",
    "FBI", "police", "investigation", "arrest", "indictment",
    "plea", "settlement", "compensation", "lawsuit",
    "witness", "cooperat", "informant", "money", "password", "token", "api", "secret", "government", "cameroon", "france", "germany", "thailand", "japan"]

# Default limits — can be overridden by user input.
DEFAULT_FILES_PER_KEYWORD = 10   # How many files to save per keyword search
DEFAULT_PAGES_PER_SEARCH = 1    # Max pages to paginate per search
DEFAULT_MAX_PAGES_ALL = 100     # Max pages for "download ALL" mode


# ── Helper: find Brave browser ────────────────────────────────────────────────

def find_brave_binary() -> Optional[str]:
    """Return the path to the Brave browser binary, or None if not found."""
    candidates = [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Brave.app/Contents/MacOS/Brave Browser",
        os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ]
    for candidate_path in candidates:
        if os.path.exists(candidate_path):
            return candidate_path
    return None


# ── Helper: create Selenium driver ────────────────────────────────────────────

def create_browser_driver():
    """
    Create a Brave browser driver via undetected-chromedriver.

    Handles Apple Silicon arch mismatches by clearing the chromedriver cache
    and retrying up to 3 times.
    """
    if not _HAS_UC:
        raise RuntimeError(
            "undetected-chromedriver is required.\n"
            "Install: pip install undetected-chromedriver"
        )

    brave_path = find_brave_binary()
    if brave_path:
        print(f"  Using Brave: {brave_path}")

    # Clear chromedriver cache on Apple Silicon to avoid x86_64 binaries.
    cache_dir = Path.home() / "Library/Application Support/undetected_chromedriver"
    import platform
    if platform.machine() == "arm64" and cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)

    for attempt in range(3):
        # undetected-chromedriver requires a FRESH ChromeOptions each attempt.
        options = uc.ChromeOptions()
        if brave_path:
            options.binary_location = brave_path
        try:
            return uc.Chrome(options=options, version_main=143)
        except OSError as err:
            is_arch_error = getattr(err, "errno", None) == 86 or "Bad CPU type" in str(err)
            if is_arch_error and attempt < 2:
                print(f"  Attempt {attempt + 1}: wrong CPU arch, clearing cache...")
                shutil.rmtree(cache_dir, ignore_errors=True)
                for item in (Path.home() / "Library/Application Support").glob("undetected_chromedriver*"):
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                time.sleep(1)
                continue
            raise

    raise RuntimeError("Failed to create browser driver after 3 retries")


# ══════════════════════════════════════════════════════════════════════════════
#  BrowserSession — wraps Selenium for age verification + site search
# ══════════════════════════════════════════════════════════════════════════════

class BrowserSession:
    """
    Manages a Selenium browser instance.

    Responsibilities:
      - Navigate to justice.gov/epstein and handle age verification
      - Submit search queries and paginate through results
      - Extract EFTA file IDs and dataset numbers from result pages
      - Export cookies for the requests-based downloader
    """

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.driver = create_browser_driver()

    # ── Age verification ──────────────────────────────────────────────────────

    def handle_age_verification(self):
        """Navigate to the site and pass the age-verification gate."""
        self.driver.get(self.base_url)
        time.sleep(2)

        # Try to detect and click the "Yes, I am 18+" button.
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(text(), '18') or contains(text(), 'age')]")
                )
            )
            print("  Age verification detected.")
            try:
                yes_button = self.driver.find_element(
                    By.XPATH, "//button[contains(text(), 'Yes') or contains(text(), 'yes')]"
                )
                yes_button.click()
                print("  Clicked 'Yes'.")
                time.sleep(2)
            except NoSuchElementException:
                try:
                    self.driver.find_element(By.ID, "age-yes").click()
                    time.sleep(2)
                except NoSuchElementException:
                    print("  Could not find the button. Please verify age manually in the browser.")
                    input("  Press Enter when done...")
        except TimeoutException:
            print("  No age verification prompt (already verified or not required).")

        # Handle CAPTCHA if present.
        page_text = self.driver.page_source.lower()
        if "captcha" in page_text or "robot" in page_text:
            print("  CAPTCHA detected. Please solve it in the browser.")
            input("  Press Enter when done...")

        time.sleep(1)

    # ── Cookie management ─────────────────────────────────────────────────────

    def get_cookies_as_dict(self) -> dict:
        """Return all browser cookies as a {name: value} dict."""
        return {cookie["name"]: cookie["value"] for cookie in self.driver.get_cookies()}

    def save_cookies_to_file(self, file_path: Path):
        """Save the full cookie list (with domains, paths, etc.) to a JSON file."""
        with open(file_path, "w") as fp:
            json.dump(self.driver.get_cookies(), fp, indent=2)

    # ── Search & pagination ───────────────────────────────────────────────────

    def _submit_search(self, query: str):
        """Navigate to the site and submit a search query via the search box."""
        self.driver.get(self.base_url)
        time.sleep(2)

        # Type the query into the search input.
        search_input = WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located((By.ID, "searchInput"))
        )
        search_input.clear()
        search_input.send_keys(query)
        time.sleep(0.5)

        # Click the search button (try normal click, fall back to JS click).
        search_button = WebDriverWait(self.driver, 18).until(
            EC.presence_of_element_located((By.ID, "searchButton"))
        )
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", search_button
        )
        time.sleep(0.3)
        try:
            WebDriverWait(self.driver, 9).until(EC.element_to_be_clickable(search_button))
            search_button.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", search_button)

        # Wait for results to appear.
        try:
            WebDriverWait(self.driver, 15).until(
                lambda d: "EFTA" in d.page_source
                or len(d.find_elements(By.XPATH, "//*[contains(text(), 'EFTA')]")) > 0
            )
        except TimeoutException:
            pass  # Results may be empty; that's OK.
        time.sleep(2)

    def _extract_file_ids_from_page(self) -> List[Dict]:
        """
        Parse the current page source and extract EFTA file IDs with dataset numbers.

        Returns a list of dicts: [{"full_id": "EFTA00033175", "dataset": 8}, ...]
        """
        page_html = self.driver.page_source
        extracted_files: List[Dict] = []
        seen_ids: Set[str] = set()

        # Primary pattern: extract dataset number and file ID from href paths.
        # Example href: /files/DataSet 8/EFTA00033175.pdf
        for match in re.finditer(r'/DataSet\s*(\d+)/EFTA(\d+)\.\w+', page_html):
            dataset_number = int(match.group(1))
            file_id = f"EFTA{match.group(2)}"
            if file_id not in seen_ids:
                seen_ids.add(file_id)
                extracted_files.append({"full_id": file_id, "dataset": dataset_number})

        # Fallback: find EFTA IDs anywhere in the page (with 5+ digits).
        for match in re.finditer(r'EFTA(\d{5,})', page_html):
            file_id = f"EFTA{match.group(1)}"
            if file_id not in seen_ids:
                seen_ids.add(file_id)
                # Try to find a nearby DataSet reference for context.
                context_window = page_html[max(0, match.start() - 200):match.end() + 200]
                dataset_match = re.search(r'DataSet\s*(\d+)', context_window)
                dataset_number = int(dataset_match.group(1)) if dataset_match else None
                extracted_files.append({"full_id": file_id, "dataset": dataset_number})

        return extracted_files

    def _click_next_page(self) -> bool:
        """
        Click the "Next" pagination button.

        Returns True if the next page loaded, False if there are no more pages.
        """
        try:
            next_button = self.driver.find_element(
                By.XPATH, "//a[contains(@class, 'usa-pagination__next-page')]"
            )
            if next_button.get_attribute("aria-disabled") == "true":
                return False
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", next_button
            )
            time.sleep(0.3)
            try:
                next_button.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", next_button)
            time.sleep(3)
            return True
        except NoSuchElementException:
            return False

    def search_and_collect(
        self,
        query: str,
        max_pages: int = DEFAULT_PAGES_PER_SEARCH,
        max_files: int = 0,
    ) -> List[Dict]:
        """
        Search for `query`, paginate up to `max_pages`, and collect file IDs.

        Args:
            query:     The search string to type into the site search box.
            max_pages: Stop paginating after this many pages.
            max_files: Stop collecting after this many unique files (0 = unlimited).

        Returns:
            List of file info dicts: [{"full_id": ..., "dataset": ...}, ...]
        """
        print(f'  Searching: "{query}"')
        try:
            self._submit_search(query)
        except Exception as err:
            print(f"    Search failed: {err}")
            return []

        collected_files: List[Dict] = []
        seen_ids: Set[str] = set()

        for page_number in range(1, max_pages + 1):
            page_files = self._extract_file_ids_from_page()
            new_files = [f for f in page_files if f["full_id"] not in seen_ids]
            for file_info in new_files:
                seen_ids.add(file_info["full_id"])
            collected_files.extend(new_files)

            # Log progress.
            if page_number == 1:
                print(f"    Page {page_number}: {len(new_files)} files")
            elif new_files:
                print(f"    Page {page_number}: +{len(new_files)} (total {len(collected_files)})")

            # Stop if we've hit the file limit.
            if max_files > 0 and len(collected_files) >= max_files:
                collected_files = collected_files[:max_files]
                break

            # Stop if there's no next page.
            if not self._click_next_page():
                break

        return collected_files

    def close(self):
        """Quit the browser."""
        try:
            self.driver.quit()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  EpsteinFileDownloader — downloads files via the requests session
# ══════════════════════════════════════════════════════════════════════════════

class EpsteinFileDownloader:
    """
    Downloads Epstein files from justice.gov using a cookie-authenticated requests session.

    All files on the site are PDFs, so we download directly as .pdf.
    The `_is_real_file` check ensures we don't save HTML error pages.
    """

    SITE_BASE_URL = "https://www.justice.gov/epstein/"

    def __init__(self, base_url: str = SITE_BASE_URL, download_dir: Optional[Path] = None):
        self.base_url = base_url

        # Configure a requests session with retries and browser-like headers.
        self.session = requests.Session()
        retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Referer": self.base_url,
        })

        # Download directory setup.
        self.download_dir = download_dir if download_dir is not None else Path("downloads")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        (self.download_dir / "pdf").mkdir(exist_ok=True)
        self._debug_download_count = 0

    # ── Cookie management ─────────────────────────────────────────────────────

    def set_cookies_from_dict(self, cookies: dict):
        """Apply cookies (from the browser session) to the requests session."""
        for name, value in cookies.items():
            self.session.cookies.set(name, value, domain=".justice.gov")

    def load_cookies_from_json(self, json_path: str) -> bool:
        """Load cookies from a previously saved cookies_browser.json file."""
        try:
            with open(json_path, "r") as fp:
                cookie_list = json.load(fp)
            for cookie in cookie_list:
                self.session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain", ".justice.gov"),
                    path=cookie.get("path", "/"),
                )
            return True
        except Exception:
            return False

    def verify_cookies_work(self) -> bool:
        """
        Quick check: try to access a known file URL.

        If the server returns HTML (the age-verification page), cookies are bad.
        If it returns binary content, cookies are good.
        """
        test_url = f"{self.base_url}files/DataSet%208/EFTA00033115.mp4"
        try:
            response = self.session.head(test_url, allow_redirects=True, timeout=10)
            content_type = response.headers.get("Content-Type", "").lower()
            content_length = int(response.headers.get("Content-Length", "0") or "0")
            # HTML with small size = age verification page.
            if "text/html" in content_type and content_length < 50000:
                return False
            # Large file or non-HTML = cookies work.
            return content_length > 50000 or "video" in content_type or "octet" in content_type
        except Exception:
            return False

    # ── File ID loading ───────────────────────────────────────────────────────

    @staticmethod
    def load_file_ids_from_txt(txt_path: str) -> List[Dict]:
        """
        Parse file_ids.txt into a list of file info dicts.

        Supported line formats:
          EFTA00024813.pdf - DataSet 8
          EFTA00024813
          00024813
        """
        file_ids: List[Dict] = []
        path = Path(txt_path)
        if not path.exists():
            return file_ids

        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Format: EFTA00024813.pdf - DataSet 8
            match = re.match(r"EFTA(\d+)\.\w+\s*-\s*DataSet\s+(\d+)", line)
            if match:
                file_ids.append({"full_id": f"EFTA{match.group(1)}", "dataset": int(match.group(2))})
                continue

            # Format: EFTA00024813
            match = re.match(r"(EFTA\d+)", line)
            if match:
                file_ids.append({"full_id": match.group(1), "dataset": None})
                continue

            # Format: 00024813
            match = re.match(r"(\d+)", line)
            if match:
                file_ids.append({"full_id": f"EFTA{match.group(1)}", "dataset": None})

        return file_ids

    # ── Download logic ────────────────────────────────────────────────────────

    @staticmethod
    def _is_real_file(chunk: bytes) -> bool:
        """
        Return True if the chunk looks like a real binary file.

        Returns False if it looks like an HTML page (age verification, 404, etc.).
        """
        if not chunk or len(chunk) < 10:
            return False
        try:
            text_preview = chunk[:500].decode("utf-8", errors="ignore").lower().strip()
            if text_preview.startswith(("<!doctype", "<html", "<!html")):
                return False
            if "<html" in text_preview[:200]:
                return False
        except Exception:
            pass  # Can't decode → binary data → good.
        return True

    def download_pdf(self, file_id: str, dataset: int) -> bool:
        """
        Download a single PDF file.

        Constructs the URL as: /files/DataSet {N}/EFTA{id}.pdf
        Validates the first bytes to ensure it's a real PDF (not an HTML error page).

        Returns True on success, False on failure.
        """
        dataset_encoded = quote(f"DataSet {dataset}")
        url = f"{self.base_url}files/{dataset_encoded}/{file_id}.pdf"

        try:
            # #region agent log
            if getattr(self, "_debug_download_count", 0) < 3:
                _debug_log("download_pdf request", {"url": url, "file_id": file_id, "dataset": dataset}, "H3")
            # #endregion
            # Request as PDF so the server is more likely to return the file instead of an HTML challenge.
            file_headers = {"Accept": "application/pdf", "Referer": self.base_url}
            # Probe: download first 2 KB to check if it's a real file.
            probe_response = self.session.get(
                url, headers={**file_headers, "Range": "bytes=0-2047"}, stream=True, timeout=15
            )
            probe_bytes = probe_response.content[:2048]
            status = probe_response.status_code
            content_type = probe_response.headers.get("Content-Type", "")
            probe_response.close()
            # #region agent log
            if getattr(self, "_debug_download_count", 0) < 3:
                preview = probe_bytes[:120].decode("utf-8", errors="replace") if probe_bytes else ""
                if "\x00" in preview or (len(probe_bytes) and probe_bytes[0:1] != b"%" and b"<" not in probe_bytes[:20]):
                    preview = "(binary)"
                is_real = self._is_real_file(probe_bytes)
                _debug_log("download_pdf probe", {"status": status, "content_type": content_type, "len": len(probe_bytes), "preview": preview[:200], "is_real_file": is_real}, "H1")
                self._debug_download_count = getattr(self, "_debug_download_count", 0) + 1
            # #endregion
            if status not in (200, 206):
                return False
            # If we got 200/206 but body looks like HTML (e.g. Akamai challenge), retry once without Range.
            if not self._is_real_file(probe_bytes):
                probe_response2 = self.session.get(url, headers=file_headers, stream=True, timeout=15)
                probe_bytes = probe_response2.content[:2048]
                probe_response2.close()
                if probe_response2.status_code not in (200, 206) or not self._is_real_file(probe_bytes):
                    return False

            # Full download.
            download_response = self.session.get(url, headers=file_headers, stream=True, timeout=120)
            download_response.raise_for_status()

            # Double-check the first chunk of the full download.
            first_chunk = next(download_response.iter_content(chunk_size=4096), None)
            if not first_chunk or not self._is_real_file(first_chunk):
                download_response.close()
                return False

            # Save to disk.
            base_id = file_id if file_id.startswith("EFTA") else f"EFTA{file_id}"
            save_path = self.download_dir / "pdf" / f"{base_id}.pdf"
            with open(save_path, "wb") as output_file:
                output_file.write(first_chunk)
                for chunk in download_response.iter_content(chunk_size=8192):
                    if chunk:
                        output_file.write(chunk)

            return True

        except Exception:
            return False

    def download_file_list(self, file_infos: List[Dict], label: str = "") -> Dict:
        """
        Download a list of files (as PDFs).

        For each file, tries the hinted dataset first, or datasets 1–10 if no hint.

        Args:
            file_infos: List of {"full_id": "EFTA...", "dataset": int|None}
            label:      Optional prefix for log lines (e.g. "JOURNALIST")

        Returns:
            Stats dict: {"total": N, "downloaded": N, "not_found": N}
        """
        stats = {"total": len(file_infos), "downloaded": 0, "not_found": 0}
        prefix = f"[{label}] " if label else ""

        for index, file_info in enumerate(file_infos, start=1):
            file_id = file_info["full_id"]
            dataset_hint = file_info.get("dataset")

            print(f"  {prefix}[{index}/{stats['total']}] {file_id}", end="", flush=True)

            # Try the hinted dataset, or iterate 1-10.
            downloaded = False
            datasets_to_try = [dataset_hint] if dataset_hint else list(range(1, 11))
            for dataset in datasets_to_try:
                if self.download_pdf(file_id, dataset):
                    print(f"  ✓ .pdf (DS {dataset})")
                    stats["downloaded"] += 1
                    downloaded = True
                    break
                time.sleep(0.05)

            if not downloaded:
                print("  —")
                stats["not_found"] += 1

            time.sleep(0.2)

        return stats


# ══════════════════════════════════════════════════════════════════════════════
#  Helper functions
# ══════════════════════════════════════════════════════════════════════════════

def save_file_ids_to_txt(all_files: Dict[str, Dict], output_path: Path):
    """Write collected file IDs to file_ids.txt (sorted by ID)."""
    lines = []
    for file_id, info in sorted(all_files.items(), key=lambda x: x[0]):
        dataset = info.get("dataset")
        if dataset is not None:
            lines.append(f"{file_id}.pdf - DataSet {dataset}")
        else:
            lines.append(file_id)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Saved {len(lines)} file IDs to {output_path}")


def print_summary(stats: Dict, download_dir: Path):
    """Print and save a download summary."""
    print(f"\n{'=' * 70}")
    print(f"  DONE")
    print(f"  Downloaded: {stats['downloaded']}")
    print(f"  Not found:  {stats['not_found']}")
    print(f"  Total:      {stats['total']}")
    print(f"{'=' * 70}")

    summary_path = download_dir / "download_summary.json"
    with open(summary_path, "w") as fp:
        json.dump(stats, fp, indent=2)
    print(f"  Summary saved to {summary_path}")


def ask_int(prompt: str, default: int) -> int:
    """Prompt the user for an integer, returning `default` on empty/invalid input."""
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  Invalid number, using default: {default}")
        return default


# ══════════════════════════════════════════════════════════════════════════════
#  Main entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  EPSTEIN FILES DOWNLOADER")
    print("=" * 70)
    print()
    print("  [1] Download ALL files   — search 'No images produced', all pages")
    print("  [2] Journalist (auto)    — curated keyword searches, save first N per keyword")
    print("  [3] Download from file_ids.txt (no browser search)")
    print("  [4] Custom search        — type your own query, choose file count")
    print()

    mode = input("Choose mode [1/2/3/4]: ").strip()
    if mode not in ("1", "2", "3", "4"):
        print("Invalid choice. Exiting.")
        return

    # ── Paths ─────────────────────────────────────────────────────────────────
    base_url = "https://www.justice.gov/epstein/"
    script_dir = Path(__file__).parent
    download_dir = script_dir / "downloads"
    cookies_path = script_dir / "cookies_browser.json"
    file_ids_path = script_dir / "file_ids.txt"

    # ── Set up the downloader ─────────────────────────────────────────────────
    downloader = EpsteinFileDownloader(base_url=base_url, download_dir=download_dir)

    # ── Step 1: Ensure we have valid cookies ──────────────────────────────────
    have_valid_cookies = False

    if cookies_path.exists():
        downloader.load_cookies_from_json(str(cookies_path))
        print("Testing saved cookies...", end=" ")
        if downloader.verify_cookies_work():
            print("OK!")
            have_valid_cookies = True
        else:
            print("expired.")

    # For modes 1/2/4 we always need a browser (for searching).
    # For mode 3 we only need it if cookies are missing.
    need_browser = mode in ("1", "2", "4") or not have_valid_cookies
    browser: Optional[BrowserSession] = None

    if need_browser:
        print("\nOpening browser for age verification...")
        browser = BrowserSession(base_url)
        browser.handle_age_verification()

        cookies = browser.get_cookies_as_dict()
        browser.save_cookies_to_file(cookies_path)
        downloader.set_cookies_from_dict(cookies)

        print("Verifying cookies...", end=" ")
        if downloader.verify_cookies_work():
            print("OK!\n")
            have_valid_cookies = True
        else:
            print("WARNING: cookies may not work. Continuing anyway.\n")

    # ══════════════════════════════════════════════════════════════════════════
    #  MODE 3: Download from file_ids.txt
    # ══════════════════════════════════════════════════════════════════════════
    if mode == "3":
        if browser:
            browser.close()

        file_infos = downloader.load_file_ids_from_txt(str(file_ids_path))
        if not file_infos:
            print(f"No file IDs in {file_ids_path}. Use mode 1, 2, or 4 first.")
            return
        print(f"Loaded {len(file_infos)} file IDs from {file_ids_path}\n")

        stats = downloader.download_file_list(file_infos)
        print_summary(stats, download_dir)
        return

    # ══════════════════════════════════════════════════════════════════════════
    #  MODE 1: Download ALL
    # ══════════════════════════════════════════════════════════════════════════
    if mode == "1":
        assert browser is not None
        print("=" * 70)
        print("  MODE 1: Download ALL files")
        print("=" * 70)
        max_pages = ask_int("  Max pages to search", DEFAULT_MAX_PAGES_ALL)

        all_results = browser.search_and_collect(
            query="No images produced",
            max_pages=max_pages,
        )
        browser.close()

        all_files = {f["full_id"]: f for f in all_results}
        print(f"\n  Collected {len(all_files)} unique file IDs.\n")
        save_file_ids_to_txt(all_files, file_ids_path)

        stats = downloader.download_file_list(list(all_files.values()), label="ALL")
        print_summary(stats, download_dir)
        return

    # ══════════════════════════════════════════════════════════════════════════
    #  MODE 4: Custom search
    # ══════════════════════════════════════════════════════════════════════════
    if mode == "4":
        assert browser is not None
        print("=" * 70)
        print("  MODE 4: Custom search")
        print("=" * 70)

        custom_query = input("  Enter search query: ").strip()
        if not custom_query:
            print("  Empty query. Exiting.")
            browser.close()
            return

        max_files = ask_int("  Max files to download", 20)
        max_pages = ask_int("  Max pages to search", 10)

        results = browser.search_and_collect(
            query=custom_query,
            max_pages=max_pages,
            max_files=max_files,
        )
        browser.close()

        if not results:
            print("  No files found for that query.")
            return

        all_files = {f["full_id"]: f for f in results}
        print(f"\n  Found {len(all_files)} files.\n")
        save_file_ids_to_txt(all_files, file_ids_path)

        stats = downloader.download_file_list(list(all_files.values()), label="CUSTOM")
        print_summary(stats, download_dir)
        return

    # ══════════════════════════════════════════════════════════════════════════
    #  MODE 2: Journalist (auto keyword searches)
    # ══════════════════════════════════════════════════════════════════════════
    if mode == "2":
        assert browser is not None
        print("=" * 70)
        print("  MODE 2: Journalist — curated keyword searches")
        print("=" * 70)

        files_per_keyword = ask_int("  Files to save per keyword", DEFAULT_FILES_PER_KEYWORD)
        pages_per_search = ask_int("  Max pages per keyword search", DEFAULT_PAGES_PER_SEARCH)

        # Keyword categories for structured searching.
        keyword_groups = [
            ("High-profile names", HIGH_PROFILE_NAMES),
            ("Violent / concerning language", VIOLENT_KEYWORDS),
            ("Evidence / locations", EVIDENCE_KEYWORDS),
        ]

        # Collect files from all keyword searches, tagging each with the keywords it matched.
        all_files: Dict[str, Dict] = {}  # file_id → {full_id, dataset, matched_keywords: []}

        for group_name, keywords in keyword_groups:
            print(f"\n  --- {group_name} ---")

            for keyword in keywords:
                results = browser.search_and_collect(
                    query=keyword,
                    max_pages=pages_per_search,
                    max_files=files_per_keyword,
                )

                new_count = 0
                for file_info in results:
                    file_id = file_info["full_id"]
                    if file_id not in all_files:
                        all_files[file_id] = {**file_info, "matched_keywords": [keyword]}
                        new_count += 1
                    else:
                        # File already found via another keyword — add the tag.
                        if keyword not in all_files[file_id]["matched_keywords"]:
                            all_files[file_id]["matched_keywords"].append(keyword)

                if new_count > 0:
                    print(f"    → {new_count} new files (total unique: {len(all_files)})")

                time.sleep(1)  # Rate limiting between searches.

        browser.close()

        # Sort by number of keyword matches (most cross-referenced = most interesting).
        sorted_files = sorted(
            all_files.values(),
            key=lambda f: len(f.get("matched_keywords", [])),
            reverse=True,
        )

        # ── Report ────────────────────────────────────────────────────────────
        print(f"\n{'=' * 70}")
        print(f"  Found {len(sorted_files)} unique files across all keyword searches")
        print(f"{'=' * 70}\n")

        # Show top hits.
        top_n = min(20, len(sorted_files))
        print(f"  Top {top_n} most cross-referenced files:\n")
        for file_info in sorted_files[:top_n]:
            keywords = file_info.get("matched_keywords", [])
            dataset = file_info.get("dataset", "?")
            print(f"    {file_info['full_id']} (DS {dataset})")
            print(f"      keywords: {', '.join(keywords[:8])}")
        print()

        # Save journalist report JSON.
        report_path = download_dir / "journalist_report.json"
        report_entries = [
            {
                "file_id": f["full_id"],
                "dataset": f.get("dataset"),
                "matched_keywords": f.get("matched_keywords", []),
                "keyword_count": len(f.get("matched_keywords", [])),
            }
            for f in sorted_files
        ]
        with open(report_path, "w") as fp:
            json.dump(report_entries, fp, indent=2)
        print(f"  Journalist report saved to {report_path}")

        # Save file IDs.
        save_file_ids_to_txt(all_files, file_ids_path)

        # ── Download ──────────────────────────────────────────────────────────
        proceed = input(f"\n  Download all {len(sorted_files)} files? [y/N]: ").strip().lower()
        if proceed in ("y", "yes"):
            stats = downloader.download_file_list(sorted_files, label="JOURNALIST")
            print_summary(stats, download_dir)
        else:
            print("  Skipped downloads. Run mode [3] later to download from file_ids.txt.")


if __name__ == "__main__":
    main()
