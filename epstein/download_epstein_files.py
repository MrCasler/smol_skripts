#!/usr/bin/env python3
"""
Download files from justice.gov/epstein/

Same idea as download_with_cookies / download_content:
  1. Cookies: Load from cookies.json or cookies.txt (export from Brave or Firefox after visiting
     justice.gov/epstein and passing age verification).
  2. File list: Use file_ids.txt (one EFTA ID per line) — primary, reliable. Optional
     search via the site may return 0 results due to Akamai bot protection.
  3. Download: For each file ID, try datasets 1–10 and extensions; download on first hit.

No Selenium required for downloading. Use fetch_file_list_selenium.py once to populate
file_ids.txt if you don't have a list.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import os
from pathlib import Path
from urllib.parse import urljoin, quote
import re
from typing import List, Dict, Optional
import json
import http.cookiejar
from bs4 import BeautifulSoup

class EpsteinFileDownloader:
    def __init__(self, base_url: str = "https://www.justice.gov/epstein/", cookies_file: Optional[str] = None, download_dir: Optional[Path] = None):
        self.base_url = base_url
        self.session = requests.Session()
        
        # Setup retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set headers to mimic a browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://www.justice.gov/epstein/',
        })
        
        # Load cookies if provided
        if cookies_file and os.path.exists(cookies_file):
            self.load_cookies(cookies_file)
        
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
        
        self.download_dir = download_dir if download_dir is not None else Path("downloads")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories for each file type
        for ext in self.file_extensions:
            folder_name = ext.lstrip('.')
            (self.download_dir / folder_name).mkdir(exist_ok=True)

    def get_file_ids_from_file(self, path: str = "file_ids.txt") -> List[Dict]:
        """Load file IDs from a text file (one per line: EFTA00024813 or 00024813)."""
        file_ids = []
        path = Path(path)
        if not path.exists():
            return file_ids
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("EFTA"):
                    full_id = line
                    id_num = line.replace("EFTA", "")
                else:
                    id_num = line
                    full_id = f"EFTA{line}"
                file_ids.append({"id": id_num, "full_id": full_id, "dataset": None})
        return file_ids
    
    def load_cookies(self, cookies_file: str):
        """
        Load cookies from a Netscape format cookie file or JSON file.
        """
        try:
            if cookies_file.endswith('.txt'):
                # Netscape format - try multiple parsing methods
                try:
                    jar = http.cookiejar.MozillaCookieJar(cookies_file)
                    jar.load(ignore_discard=True, ignore_expires=True)
                    self.session.cookies.update(jar)
                    print(f"Loaded cookies from {cookies_file} (MozillaCookieJar)")
                except Exception:
                    # Manual parsing for Netscape format
                    with open(cookies_file, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith('#') or not line:
                                continue
                            parts = line.split('\t')
                            if len(parts) >= 7:
                                domain = parts[0]
                                domain_specified = parts[1] == 'TRUE'
                                path = parts[2]
                                secure = parts[3] == 'TRUE'
                                expires = parts[4]
                                name = parts[5]
                                value = parts[6] if len(parts) > 6 else ''
                                
                                # Add cookie to session
                                self.session.cookies.set(name, value, domain=domain, path=path)
                    print(f"Loaded cookies from {cookies_file} (manual parsing)")
            elif cookies_file.endswith('.json'):
                # JSON format
                with open(cookies_file, 'r') as f:
                    cookies = json.load(f)
                    if isinstance(cookies, list):
                        for cookie in cookies:
                            domain = cookie.get('domain', '.justice.gov')
                            if not domain.startswith('.'):
                                domain = '.' + domain.lstrip('.')
                            self.session.cookies.set(
                                cookie['name'], 
                                cookie['value'], 
                                domain=domain,
                                path=cookie.get('path', '/')
                            )
                    elif isinstance(cookies, dict):
                        # Simple key-value format
                        for name, value in cookies.items():
                            self.session.cookies.set(name, value, domain='.justice.gov')
                print(f"Loaded cookies from {cookies_file}")
        except Exception as e:
            print(f"Warning: Could not load cookies from {cookies_file}: {e}")
            import traceback
            traceback.print_exc()
    
    def save_cookies(self, cookies_file: str = "cookies.txt"):
        """
        Save current session cookies to a file.
        """
        try:
            jar = http.cookiejar.MozillaCookieJar(cookies_file)
            for cookie in self.session.cookies:
                jar.set_cookie(cookie)
            jar.save(ignore_discard=True, ignore_expires=True)
            print(f"Saved cookies to {cookies_file}")
        except Exception as e:
            print(f"Warning: Could not save cookies: {e}")
    
    def handle_age_verification(self) -> bool:
        """
        Handle the age verification page.
        Returns True if successful, False otherwise.
        """
        try:
            # First, try to access the main page
            response = self.session.get(self.base_url)
            
            # Check if we need age verification
            if 'age verification' in response.text.lower() or 'Are you 18' in response.text:
                print("Age verification required. Attempting to verify...")
                
                # Look for the verification form
                # The form typically has a "Yes" button or checkbox
                # We'll try to submit the form with age verification
                
                # Try to find and submit the age verification form
                # This might need to be adjusted based on the actual form structure
                verification_data = {
                    'age_verified': 'yes',
                    'age': 'yes',
                }
                
                # Try POST to the same URL or a verification endpoint
                verify_response = self.session.post(self.base_url, data=verification_data, allow_redirects=True)
                
                if verify_response.status_code == 200:
                    print("Age verification submitted.")
                    return True
            else:
                print("No age verification required or already verified.")
                return True
                
        except Exception as e:
            print(f"Error during age verification: {e}")
            return False
    
    def search_files(self, search_query: str = "No images produced", dataset: int = None, page: int = 1) -> Optional[Dict]:
        """
        Search for files matching the query.
        Returns a dictionary with file IDs and metadata.
        """
        try:
            # First, get the main page to ensure we have proper cookies
            response = self.session.get(self.base_url)
            
            # Parse HTML to find search form
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to find search input and form
            search_input = soup.find('input', {'type': 'search'}) or soup.find('input', {'type': 'text', 'name': re.compile(r'search|q', re.I)})
            
            if search_input:
                # Find the form
                form = search_input.find_parent('form')
                if form:
                    form_action = form.get('action', '')
                    form_method = form.get('method', 'get').lower()
                    search_url = urljoin(self.base_url, form_action) if form_action else self.base_url
                    
                    # Prepare form data
                    form_data = {}
                    for input_field in form.find_all(['input', 'select']):
                        name = input_field.get('name')
                        if name:
                            if input_field.get('type') == 'checkbox' or input_field.get('type') == 'radio':
                                if input_field.get('checked'):
                                    form_data[name] = input_field.get('value', 'on')
                            else:
                                form_data[name] = input_field.get('value', '')
                    
                    # Set search query
                    search_input_name = search_input.get('name', 'q')
                    form_data[search_input_name] = search_query
                    
                    if form_method == 'post':
                        response = self.session.post(search_url, data=form_data, allow_redirects=True)
                    else:
                        response = self.session.get(search_url, params=form_data, allow_redirects=True)
                else:
                    # No form found, try direct search
                    response = self.session.get(self.base_url, params={'q': search_query})
            else:
                # Try direct URL parameters
                params = {'q': search_query}
                response = self.session.get(self.base_url, params=params)
            
            response.raise_for_status()
            
            # Parse the HTML with BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            file_ids = []
            
            # Debug: Save HTML for inspection (only on first call)
            debug_file = self.download_dir / "debug_search_page.html"
            if not debug_file.exists():
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                print(f"  Debug: Saved search page HTML to {debug_file}")
            
            # Look for file links and text containing EFTA IDs
            # Pattern: EFTA00024813.pdf - DataSet 8
            text_content = soup.get_text()
            
            # Find all EFTA IDs
            pattern = r'EFTA(\d+)'
            matches = re.findall(pattern, text_content)
            
            # Also look for links
            links = soup.find_all('a', href=re.compile(r'EFTA\d+'))
            for link in links:
                href = link.get('href', '')
                match = re.search(r'EFTA(\d+)', href)
                if match:
                    matches.append(match.group(1))
            
            # Extract dataset information from context
            dataset_pattern = r'DataSet\s*(\d+)'
            dataset_matches = re.findall(dataset_pattern, text_content)
            
            # Extract unique file IDs
            seen = set()
            for match in matches:
                file_id = match
                full_id = f"EFTA{file_id}"
                
                if full_id not in seen:
                    seen.add(full_id)
                    # Try to determine dataset from context
                    dataset_num = dataset
                    if dataset_num is None and dataset_matches:
                        # Use the most common dataset number found
                        dataset_num = int(dataset_matches[0]) if dataset_matches else None
                    
                    file_ids.append({
                        'id': file_id,
                        'full_id': full_id,
                        'dataset': dataset_num or 8,  # Default to dataset 8
                    })
            
            # Check for pagination
            has_more = bool(soup.find('a', string=re.compile(r'next|Next', re.I)) or 
                          soup.find('a', href=re.compile(r'page.*next', re.I)))
            
            if len(file_ids) == 0:
                print(f"  Warning: No file IDs found on page. Response status: {response.status_code}")
                print(f"  Response length: {len(response.text)} characters")
                # Check if we got redirected or blocked
                if '403' in response.text or 'Forbidden' in response.text:
                    print("  ⚠️  Got 403 Forbidden - cookies may be invalid or expired")
                if 'age verification' in response.text.lower():
                    print("  ⚠️  Age verification page detected - need to verify age first")
            
            return {
                'files': file_ids,
                'total_results': len(file_ids),
                'has_more': has_more,
            }
            
        except Exception as e:
            print(f"Error searching files: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def test_file_extension(self, file_id: str, dataset: int, extension: str) -> bool:
        """
        Test if a file exists with the given extension.
        Returns True if file exists (status 200), False otherwise.
        """
        try:
            # URL format: https://www.justice.gov/epstein/files/DataSet%208/EFTA00033177.pdf
            dataset_encoded = quote(f"DataSet {dataset}")
            url = f"{self.base_url}files/{dataset_encoded}/{file_id}{extension}"
            
            # Use HEAD request first (faster, doesn't download content)
            response = self.session.head(url, allow_redirects=True, timeout=10)
            
            # If HEAD doesn't work, try GET but only read headers
            if response.status_code == 405:  # Method not allowed
                response = self.session.get(url, stream=True, timeout=10)
                response.close()
            
            # Check if file exists (200 OK) and is not an error page
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                content_length = response.headers.get('Content-Length', '0')
                
                # Check if it's not an HTML error page
                if 'text/html' not in content_type or int(content_length) > 10000:
                    return True
            
            return False
            
        except Exception as e:
            # Timeout or connection error - assume file doesn't exist
            return False
    
    def find_file_type(self, file_id: str, dataset: int) -> Optional[str]:
        """
        Test different file extensions to find the correct one.
        Returns the extension if found, None otherwise.
        """
        print(f"  Testing file {file_id} in dataset {dataset}...")
        
        for ext in self.file_extensions:
            if self.test_file_extension(file_id, dataset, ext):
                print(f"    Found: {ext}")
                return ext
            time.sleep(0.1)  # Small delay to avoid rate limiting
        
            print(f"    No valid extension found for {file_id}")
        return None

    def process_file_list(self, file_infos: List[Dict]) -> Dict:
        """Process a list of file infos (from file_ids.txt or search). For each, try datasets 1-10 and extensions; download on first hit."""
        stats = {"total_files": len(file_infos), "downloaded": 0, "failed": 0, "not_found": 0}
        for file_info in file_infos:
            full_id = file_info["full_id"]
            dataset_hint = file_info.get("dataset")
            found = False
            for dataset in range(1, 11):
                if dataset_hint is not None and dataset != dataset_hint:
                    continue
                ext = self.find_file_type(full_id, dataset)
                if ext:
                    if self.download_file(full_id, dataset, ext):
                        stats["downloaded"] += 1
                    else:
                        stats["failed"] += 1
                    found = True
                    break
                time.sleep(0.1)
            if not found:
                stats["not_found"] += 1
            time.sleep(0.5)
        return stats
    
    def download_file(self, file_id: str, dataset: int, extension: str) -> bool:
        """
        Download a file and save it to the appropriate folder.
        """
        try:
            dataset_encoded = quote(f"DataSet {dataset}")
            url = f"{self.base_url}files/{dataset_encoded}/{file_id}{extension}"
            
            response = self.session.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            # Determine save path (file_id may be "EFTA00033177" or "00033177")
            folder_name = extension.lstrip('.')
            base_id = file_id if file_id.startswith("EFTA") else f"EFTA{file_id}"
            filename = f"{base_id}{extension}"
            save_path = self.download_dir / folder_name / filename
            
            # Download file
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            print(f"    Downloaded: {save_path}")
            return True
            
        except Exception as e:
            print(f"    Error downloading {file_id}{extension}: {e}")
            return False
    
    def process_dataset(self, dataset: int, max_pages: int = None) -> Dict:
        """
        Process all files in a dataset.
        """
        print(f"\nProcessing Dataset {dataset}...")
        
        stats = {
            'total_files': 0,
            'downloaded': 0,
            'failed': 0,
            'not_found': 0,
        }
        
        page = 1
        max_pages = max_pages or 1000  # Safety limit
        
        while page <= max_pages:
            print(f"\n  Page {page}...")
            
            # Search for files
            result = self.search_files("No images produced", dataset=dataset, page=page)
            
            if not result or not result['files']:
                print(f"  No more files found on page {page}")
                break
            
            files = result['files']
            stats['total_files'] += len(files)
            
            # Process each file
            for file_info in files:
                file_id = file_info['id']
                full_id = file_info['full_id']
                
                # Find the correct file extension
                extension = self.find_file_type(full_id, dataset)
                
                if extension:
                    # Download the file
                    if self.download_file(full_id, dataset, extension):
                        stats['downloaded'] += 1
                    else:
                        stats['failed'] += 1
                else:
                    stats['not_found'] += 1
                
                time.sleep(0.5)  # Rate limiting
            
            # Check if there are more pages
            if not result.get('has_more', False):
                break
            
            page += 1
            time.sleep(1)  # Delay between pages
        
        return stats
    
    def run(self, datasets: List[int] = None, max_pages_per_dataset: int = None, file_ids_path: str = "file_ids.txt"):
        """
        Main execution: prefer file_ids.txt (like download_with_cookies flow), else try search.
        """
        print("Epstein Files Downloader (cookies + file list, same idea as download_with_cookies)")
        print("Cookies: cookies.json or cookies.txt | File list: file_ids.txt (one EFTA ID per line)\n")
        
        if not self.handle_age_verification():
            print("Warning: Age verification may have failed. Continuing anyway...")
        self.save_cookies()
        
        # Primary path: file_ids.txt (reliable, no Akamai)
        file_infos = self.get_file_ids_from_file(file_ids_path)
        if file_infos:
            print(f"Using file list: {file_ids_path} ({len(file_infos)} file IDs)\n")
            stats = self.process_file_list(file_infos)
            summary = {"file_list": stats}
        elif Path(file_ids_path).exists():
            print("file_ids.txt exists but has no IDs (only comments?). Add EFTA IDs or run fetch_file_list_selenium.py.\n")
            summary = {}
            stats = None
        else:
            # Fallback: search (often returns 0 due to Akamai bot protection)
            print("No file_ids.txt (or empty). Trying site search — may return 0 results if Akamai blocks.\n")
            datasets = datasets or list(range(1, 11))
            all_stats = {}
            for dataset in datasets:
                stats = self.process_dataset(dataset, max_pages_per_dataset)
                all_stats[f"Dataset {dataset}"] = stats
                print(f"\nDataset {dataset} Summary: total={stats['total_files']} downloaded={stats['downloaded']} failed={stats['failed']} not_found={stats['not_found']}")
                time.sleep(2)
            summary = all_stats
            stats = None
        summary_path = self.download_dir / "download_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        if stats is not None:
            print(f"\nSummary: downloaded={stats['downloaded']} failed={stats['failed']} not_found={stats['not_found']}")
        print(f"\nDone. Summary saved to {summary_path}")


def main():
    print("=" * 60)
    print("Epstein Files Downloader")
    print("=" * 60)
    print("1. Export cookies from Brave or Firefox (justice.gov/epstein, after age verification)")
    print("   → Save as cookies.json or cookies.txt in this folder")
    print("2. Add file IDs to file_ids.txt (one per line, e.g. EFTA00024813)")
    print("   → Or run fetch_file_list_selenium.py once to populate from the site")
    print("=" * 60)
    
    cookies_file = None
    if os.path.exists("cookies.json"):
        cookies_file = "cookies.json"
    elif os.path.exists("cookies.txt"):
        cookies_file = "cookies.txt"
    else:
        print("\nNo cookies.json or cookies.txt found. Downloads may get 403.")
        print("Export cookies from the site and save here, then run again.\n")
    
    download_dir = Path(__file__).parent / "downloads"
    downloader = EpsteinFileDownloader(cookies_file=cookies_file, download_dir=download_dir)
    
    file_ids_path = Path(__file__).parent / "file_ids.txt"
    if not file_ids_path.exists():
        file_ids_path.write_text(
            "# Add one EFTA file ID per line (e.g. EFTA00024813 or 00024813)\n"
            "# Get IDs from the site search, or run fetch_file_list_selenium.py to populate this file.\n",
            encoding="utf-8",
        )
        print(f"Created {file_ids_path} — add your file IDs there, then run again.\n")
        return
    
    downloader.run(file_ids_path=str(file_ids_path))
    print("\nAll set.")
    return


if __name__ == "__main__":
    main()
