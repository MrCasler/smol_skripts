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
from pathlib import Path
from urllib.parse import quote
import re
from typing import List, Dict, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Prefer undetected_chromedriver so driver version matches browser (Brave 143 etc.)
try:
    import undetected_chromedriver as uc
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
        opts = uc.ChromeOptions()
        if headless:
            opts.add_argument("--headless")
        brave_path = find_brave_binary() if use_brave else None
        if brave_path:
            opts.binary_location = brave_path
            print(f"Using Brave via undetected-chromedriver: {brave_path}")
        return uc.Chrome(options=opts)
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
            
            # Find search input
            try:
                search_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @type='text']"))
                )
                search_input.clear()
                search_input.send_keys(search_query)
                time.sleep(1)
                
                # Find and click search button
                search_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Search') or @type='submit']")
                search_button.click()
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
    
    def get_all_pages(self, search_query: str = "No images produced") -> List[Dict]:
        """
        Navigate through all pages of search results.
        """
        all_files = []
        page = 1
        
        while True:
            print(f"\nProcessing page {page}...")
            
            files = self.search_files(search_query)
            
            if not files:
                print("No more files found.")
                break
            
            all_files.extend(files)
            
            # Try to find and click "Next" button
            try:
                next_button = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Next') or contains(text(), 'next')]")
                if 'disabled' in next_button.get_attribute('class') or 'disabled' in next_button.get_attribute('aria-disabled'):
                    break
                next_button.click()
                time.sleep(3)
                page += 1
            except NoSuchElementException:
                print("No 'Next' button found. Reached end of results.")
                break
        
        return all_files
    
    def test_file_extension(self, file_id: str, dataset: int, extension: str) -> bool:
        """
        Test if a file exists with the given extension.
        """
        try:
            dataset_encoded = quote(f"DataSet {dataset}")
            url = f"{self.base_url}files/{dataset_encoded}/{file_id}{extension}"
            
            # Use HEAD request
            response = self.session.head(url, allow_redirects=True, timeout=10)
            
            if response.status_code == 405:
                response = self.session.get(url, stream=True, timeout=10)
                response.close()
            
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                content_length = response.headers.get('Content-Length', '0')
                
                if 'text/html' not in content_type or int(content_length) > 10000:
                    return True
            
            return False
            
        except Exception as e:
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
        """
        try:
            dataset_encoded = quote(f"DataSet {dataset}")
            url = f"{self.base_url}files/{dataset_encoded}/{file_id}{extension}"
            
            response = self.session.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            folder_name = extension.lstrip('.')
            filename = f"EFTA{file_id}{extension}"
            save_path = self.download_dir / folder_name / filename
            
            with open(save_path, 'wb') as f:
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
            
            # Get all files from search results
            print("\nCollecting all file IDs from search results...")
            all_files = self.get_all_pages("No images produced")
            
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
