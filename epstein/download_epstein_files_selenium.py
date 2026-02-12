#!/usr/bin/env python3
"""
Optional Selenium-based flow: open browser, pass age verification, search, download.
For the simpler path (no Selenium): use file_ids.txt + cookies with download_epstein_files.py.
Uses undetected-chromedriver when available so driver version matches Brave (Chromium).
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import os
import shutil
from pathlib import Path
from urllib.parse import quote
import re
from typing import List, Dict, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Patch urlopen BEFORE importing undetected_chromedriver (patcher does "from urllib.request import urlopen" at load time)
# This fixes SSL cert errors on macOS where Python's default SSL context lacks CA certs
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
    pass  # certifi not installed; may hit SSL errors

# Prefer undetected_chromedriver so driver version matches browser (Brave 143 etc.)
try:
    import undetected_chromedriver as uc  # type: ignore
    # Also patch the patcher module's urlopen directly (belt-and-suspenders)
    try:
        import undetected_chromedriver.patcher as _patcher_mod  # type: ignore
        _patcher_mod.urlopen = _urlopen_with_certs
    except (AttributeError, ImportError):
        pass
    _HAS_UC = True
except ImportError:
    _HAS_UC = False

def find_brave_binary():
    """Find Brave browser binary on macOS."""
    for path in [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Brave.app/Contents/MacOS/Brave Browser",
        os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ]:
        if os.path.exists(path):
            return path
    return None


def _create_driver(headless: bool, use_brave: bool):
    """Create Chrome/Brave driver; prefer undetected_chromedriver for version match."""
    if _HAS_UC:
        brave_path = find_brave_binary() if use_brave else None
        if brave_path:
            print(f"Using Brave via undetected-chromedriver: {brave_path}")
        uc_cache = Path.home() / "Library/Application Support/undetected_chromedriver"
        # On Apple Silicon, ensure we get arm64 chromedriver (not x86_64)
        import platform
        is_apple_silicon = platform.machine() == "arm64"
        if is_apple_silicon and uc_cache.exists():
            # Pre-emptively remove cache on Apple Silicon to force fresh download
            print("Apple Silicon detected: ensuring arm64 chromedriver...")
            shutil.rmtree(uc_cache, ignore_errors=True)
        # Retry loop: if wrong CPU architecture cached, remove cache and retry
        for attempt in range(3):  # Allow 3 attempts
            # CRITICAL: Create fresh ChromeOptions each attempt (undetected_chromedriver forbids reuse)
            opts = uc.ChromeOptions()
            if headless:
                opts.add_argument("--headless")
            if brave_path:
                opts.binary_location = brave_path
            try:
                # Specify version_main=143 to match Brave 143 (undetected_chromedriver defaults to latest which may be too new)
                driver = uc.Chrome(options=opts, version_main=143)
                return driver
            except OSError as e:
                errno = getattr(e, "errno", None)
                if errno == 86 or "Bad CPU type" in str(e):
                    print(f"Attempt {attempt+1}: Wrong CPU architecture detected, removing cache...")
                    # Aggressive cache removal
                    shutil.rmtree(uc_cache, ignore_errors=True)
                    # Remove any related cache directories
                    parent_cache = Path.home() / "Library/Application Support"
                    for item in parent_cache.glob("undetected_chromedriver*"):
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                    time.sleep(1.0)  # Longer pause to ensure cleanup
                    if attempt < 2:  # Don't continue on last attempt
                        continue
                raise
        raise RuntimeError("Failed to create Chrome driver after retries (wrong CPU architecture)")
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.core.os_manager import ChromeType
    opts = Options()
    if headless:
        opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    brave_path = find_brave_binary() if use_brave else None
    if brave_path:
        opts.binary_location = brave_path
        print(f"Using Brave at: {brave_path}")
    try:
        service = Service(ChromeDriverManager(chrome_type=ChromeType.BRAVE if brave_path else None).install())
    except Exception:
        service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


class EpsteinFileDownloaderSelenium:
    def __init__(self, base_url: str = "https://www.justice.gov/epstein/", headless: bool = False, use_brave: bool = True):
        self.base_url = base_url
        self.headless = headless
        self.driver = _create_driver(headless=headless, use_brave=use_brave)
        if not _HAS_UC:
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Setup requests session for downloads (reusing cookies from selenium)
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # File extensions to test
        self.file_extensions = [
            '.mp4', '.mov', '.flv', '.avi', '.mkv', '.wmv',  # Video
            '.mp3', '.ogg', '.wav', '.m4a', '.flac',  # Audio
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',  # Images
            '.txt', '.doc', '.docx', '.pdf', '.rtf',  # Documents
            '.zip', '.rar', '.7z', '.tar', '.gz',  # Archives
            '.csv', '.xls', '.xlsx',  # Spreadsheets
            '.html', '.htm', '.xml',  # Web formats
        ]
        
        self.download_dir = Path("downloads")
        self.download_dir.mkdir(exist_ok=True)
        
        # Create subdirectories for each file type
        for ext in self.file_extensions:
            folder_name = ext.lstrip('.')
            (self.download_dir / folder_name).mkdir(exist_ok=True)
    
    def sync_cookies(self):
        """Sync cookies from Selenium to requests session."""
        selenium_cookies = self.driver.get_cookies()
        for cookie in selenium_cookies:
            self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain'))
    
    def handle_age_verification(self) -> bool:
        """
        Handle the age verification page using Selenium.
        """
        try:
            print("Navigating to main page...")
            self.driver.get(self.base_url)
            time.sleep(2)
            
            # Check for age verification
            try:
                # Look for age verification elements
                age_verification = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '18') or contains(text(), 'age')]"))
                )
                
                print("Age verification detected. Looking for verification button...")
                
                # Try to find and click "Yes" button
                try:
                    yes_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Yes') or contains(text(), 'yes')]")
                    yes_button.click()
                    print("Clicked 'Yes' on age verification.")
                    time.sleep(2)
                except NoSuchElementException:
                    # Try alternative selectors
                    try:
                        yes_button = self.driver.find_element(By.ID, "age-yes")
                        yes_button.click()
                        time.sleep(2)
                    except NoSuchElementException:
                        print("Could not find age verification button. You may need to verify manually.")
                        input("Please verify your age in the browser and press Enter to continue...")
                
                # Wait for page to load after verification
                time.sleep(3)
                
            except TimeoutException:
                print("No age verification required or already verified.")
            
            # Sync cookies after verification
            self.sync_cookies()
            
            # Check for CAPTCHA
            if 'captcha' in self.driver.page_source.lower() or 'robot' in self.driver.page_source.lower():
                print("CAPTCHA detected. Please solve it manually...")
                input("Press Enter after solving the CAPTCHA...")
                self.sync_cookies()
            
            return True
            
        except Exception as e:
            print(f"Error during age verification: {e}")
            return False
    
    def search_files(self, search_query: str = "No images produced", dataset: int = None) -> List[Dict]:
        """
        Search for files using the search interface.
        Returns a list of file dictionaries.
        """
        try:
            print(f"Searching for '{search_query}'...")
            self.driver.get(self.base_url)
            time.sleep(2)
            
            # Find search input - use specific IDs from the HTML structure (same as fetch_file_list_selenium.py)
            try:
                print("Waiting for search box...")
                search_input = WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.ID, "searchInput"))
                )
                print("Found search box, entering query...")
                search_input.clear()
                search_input.send_keys(search_query)
                time.sleep(1)
                
                # Use the search button with ID="searchButton"
                print("Looking for search button...")
                search_button = WebDriverWait(self.driver, 18).until(
                    EC.presence_of_element_located((By.ID, "searchButton"))
                )
                # Scroll into view and try click
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", search_button)
                time.sleep(0.5)
                try:
                    WebDriverWait(self.driver, 9).until(EC.element_to_be_clickable(search_button))
                    search_button.click()
                except Exception:
                    print("Regular click failed, trying JavaScript click...")
                    self.driver.execute_script("arguments[0].click();", search_button)
                print("Search submitted, waiting for results...")
                time.sleep(3)
                
            except (TimeoutException, NoSuchElementException) as e:
                print(f"Could not find search interface: {e}")
                print("Trying to parse current page...")
            
            # Parse results
            file_ids = []
            page_source = self.driver.page_source
            
            # Pattern to match file IDs: EFTA followed by digits
            pattern = r'EFTA(\d+)'
            matches = re.findall(pattern, page_source)
            
            # Also look for dataset information
            dataset_pattern = r'DataSet\s*(\d+)'
            dataset_matches = re.findall(dataset_pattern, page_source)
            
            # Extract unique file IDs with their datasets
            seen = set()
            for match in matches:
                file_id = match
                full_id = f"EFTA{file_id}"
                
                if full_id not in seen:
                    seen.add(full_id)
                    # Try to find associated dataset
                    dataset_num = None
                    # Look for dataset in nearby text (simplified)
                    if dataset_matches:
                        dataset_num = int(dataset_matches[0]) if dataset_matches else None
                    
                    file_ids.append({
                        'id': file_id,
                        'full_id': full_id,
                        'dataset': dataset_num,
                    })
            
            print(f"Found {len(file_ids)} file IDs on this page")
            return file_ids
            
        except Exception as e:
            print(f"Error searching files: {e}")
            return []
    
    def get_all_pages(self, search_query: str = "No images produced", max_pages: int = 100) -> List[Dict]:
        """
        Navigate through all pages of search results (up to max_pages).
        """
        all_files = []
        page = 1
        
        # Do initial search
        print(f"\nProcessing page {page}...")
        files = self.search_files(search_query)
        if files:
            all_files.extend(files)
        
        while page < max_pages:
            # Pagination: look for the "Next" link with class "usa-pagination__next-page"
            try:
                next_btn = self.driver.find_element(By.XPATH, "//a[contains(@class, 'usa-pagination__next-page')]")
                # Check if it's disabled
                if next_btn.get_attribute("aria-disabled") == "true" or "disabled" in (next_btn.get_attribute("class") or ""):
                    print("  'Next' button is disabled, reached end of results")
                    break
                # Scroll into view and click
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                time.sleep(0.5)
                try:
                    next_btn.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(3)  # Wait for next page to load
                page += 1
                
                print(f"\nProcessing page {page}...")
                # Parse the new page (don't search again, just parse current page)
                file_ids = []
                page_source = self.driver.page_source
                pattern = r'EFTA(\d+)'
                matches = re.findall(pattern, page_source)
                dataset_pattern = r'DataSet\s*(\d+)'
                dataset_matches = re.findall(dataset_pattern, page_source)
                
                seen = set()
                for match in matches:
                    file_id = match
                    full_id = f"EFTA{file_id}"
                    if full_id not in seen:
                        seen.add(full_id)
                        dataset_num = int(dataset_matches[0]) if dataset_matches else None
                        file_ids.append({
                            'id': file_id,
                            'full_id': full_id,
                            'dataset': dataset_num,
                        })
                
                if file_ids:
                    all_files.extend(file_ids)
                    print(f"Found {len(file_ids)} file IDs on this page (total: {len(all_files)})")
                else:
                    print("No file IDs found on this page")
                    break
                    
            except NoSuchElementException:
                print("  No 'Next' button found, reached end of results")
                break
        
        if page >= max_pages:
            print(f"\nReached page limit ({max_pages}), stopping...")
        
        return all_files
    
    def test_file_extension(self, file_id: str, dataset: int, extension: str) -> bool:
        """
        Test if a file exists with the given extension.
        Downloads first 2KB and checks if it's actual binary content (not HTML error page).
        """
        try:
            dataset_encoded = quote(f"DataSet {dataset}")
            url = f"{self.base_url}files/{dataset_encoded}/{file_id}{extension}"
            
            # GET first 2KB to verify content
            resp = self.session.get(url, headers={'Range': 'bytes=0-2047'}, stream=True, timeout=15)
            if resp.status_code not in (200, 206):
                return False
            chunk = resp.content[:2048]
            resp.close()
            if not chunk or len(chunk) < 10:
                return False
            # Reject HTML pages (error pages, age verification, etc.)
            try:
                text = chunk[:500].decode('utf-8', errors='ignore').lower().strip()
                if text.startswith(('<!doctype', '<html', '<!html')) or '<html' in text[:200]:
                    return False
            except:
                pass  # Can't decode → binary → likely a real file
            return True
        except Exception:
            return False
    
    def find_file_type(self, file_id: str, dataset: int) -> Optional[str]:
        """
        Test different file extensions to find the correct one.
        """
        print(f"  Testing file {file_id} in dataset {dataset}...")
        
        for ext in self.file_extensions:
            if self.test_file_extension(file_id, dataset, ext):
                print(f"    Found: {ext}")
                return ext
            time.sleep(0.1)
        
        print(f"    No valid extension found for {file_id}")
        return None
    
    def download_file(self, file_id: str, dataset: int, extension: str) -> bool:
        """
        Download a file and save it to the appropriate folder.
        Validates content to reject HTML error pages.
        """
        try:
            dataset_encoded = quote(f"DataSet {dataset}")
            url = f"{self.base_url}files/{dataset_encoded}/{file_id}{extension}"
            
            response = self.session.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            # Validate first chunk
            first_chunk = next(response.iter_content(chunk_size=4096), None)
            if not first_chunk:
                print(f"    Skipping {file_id}{extension}: empty response")
                return False
            try:
                text = first_chunk[:500].decode('utf-8', errors='ignore').lower().strip()
                if text.startswith(('<!doctype', '<html')) or '<html' in text[:200]:
                    print(f"    Skipping {file_id}{extension}: HTML error page")
                    response.close()
                    return False
            except:
                pass
            
            folder_name = extension.lstrip('.')
            # Avoid double EFTA prefix
            base_id = file_id if file_id.startswith("EFTA") else f"EFTA{file_id}"
            filename = f"{base_id}{extension}"
            save_path = self.download_dir / folder_name / filename
            
            with open(save_path, 'wb') as f:
                f.write(first_chunk)
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            print(f"    Downloaded: {save_path}")
            return True
            
        except Exception as e:
            print(f"    Error downloading {file_id}{extension}: {e}")
            return False
    
    def process_files(self, files: List[Dict]):
        """
        Process a list of files: find their types and download them.
        """
        stats = {
            'total_files': len(files),
            'downloaded': 0,
            'failed': 0,
            'not_found': 0,
        }
        
        for file_info in files:
            file_id = file_info['full_id']
            dataset = file_info.get('dataset', 8)  # Default to dataset 8 if not found
            
            # If dataset is None, try all datasets
            if dataset is None:
                for ds in range(1, 11):
                    extension = self.find_file_type(file_id, ds)
                    if extension:
                        if self.download_file(file_id, ds, extension):
                            stats['downloaded'] += 1
                        else:
                            stats['failed'] += 1
                        break
                else:
                    stats['not_found'] += 1
            else:
                extension = self.find_file_type(file_id, dataset)
                if extension:
                    if self.download_file(file_id, dataset, extension):
                        stats['downloaded'] += 1
                    else:
                        stats['failed'] += 1
                else:
                    stats['not_found'] += 1
            
            time.sleep(0.5)
        
        return stats
    
    def run(self):
        """
        Main execution method.
        """
        print("Starting Epstein Files Downloader (Selenium version)...")
        
        try:
            # Handle age verification
            if not self.handle_age_verification():
                print("Warning: Age verification may have failed.")
            
            # Get all files from search results (up to 50 pages for testing)
            print("\nCollecting all file IDs from search results...")
            all_files = self.get_all_pages("No images produced", max_pages=50)
            
            print(f"\nFound {len(all_files)} total files to process.")
            
            # Process files
            stats = self.process_files(all_files)
            
            print(f"\n\nSummary:")
            print(f"  Total files: {stats['total_files']}")
            print(f"  Downloaded: {stats['downloaded']}")
            print(f"  Failed: {stats['failed']}")
            print(f"  Not found: {stats['not_found']}")
            
        finally:
            self.driver.quit()


def main():
    # Set headless=False to see the browser (useful for debugging and CAPTCHA)
    # use_brave=True to use Brave (only Chromium-based browser supported here; no Firefox)
    downloader = EpsteinFileDownloaderSelenium(headless=False, use_brave=True)
    downloader.run()


if __name__ == "__main__":
    main()
