#!/usr/bin/env python3
"""
Helper script to manually specify file IDs if search doesn't work.
Create a file_ids.txt with one file ID per line (format: EFTA00024813 or just 00024813)
"""

from download_epstein_files import EpsteinFileDownloader
import sys

def load_file_ids(filename='file_ids.txt'):
    """Load file IDs from a text file."""
    file_ids = []
    try:
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Handle both formats: EFTA00024813 or 00024813
                if line.startswith('EFTA'):
                    file_id = line.replace('EFTA', '')
                    full_id = line
                else:
                    file_id = line
                    full_id = f"EFTA{line}"
                
                file_ids.append({
                    'id': file_id,
                    'full_id': full_id,
                    'dataset': None,  # Will try all datasets
                })
        return file_ids
    except FileNotFoundError:
        print(f"File {filename} not found.")
        print("Create a file_ids.txt with one file ID per line.")
        print("Format: EFTA00024813 or just 00024813")
        return []

def main():
    print("Manual File ID Processor")
    print("=" * 60)
    
    # Load file IDs
    file_ids = load_file_ids()
    
    if not file_ids:
        print("\nNo file IDs found. Creating example file_ids.txt...")
        with open('file_ids.txt', 'w') as f:
            f.write("# Add file IDs here, one per line\n")
            f.write("# Format: EFTA00024813 or just 00024813\n")
            f.write("# Example:\n")
            f.write("# EFTA00024813\n")
            f.write("# EFTA00033177\n")
        print("Created file_ids.txt - add your file IDs there and run again.")
        return
    
    print(f"\nFound {len(file_ids)} file IDs to process")
    
    # Initialize downloader
    cookies_file = None
    if os.path.exists("cookies.txt"):
        cookies_file = "cookies.txt"
    elif os.path.exists("cookies.json"):
        cookies_file = "cookies.json"
    
    downloader = EpsteinFileDownloader(cookies_file=cookies_file)
    
    # Process each file ID across all datasets
    stats = {
        'total_files': len(file_ids),
        'downloaded': 0,
        'failed': 0,
        'not_found': 0,
    }
    
    for file_info in file_ids:
        file_id = file_info['full_id']
        print(f"\nProcessing {file_id}...")
        
        # Try all datasets
        found = False
        for dataset in range(1, 11):
            extension = downloader.find_file_type(file_id, dataset)
            if extension:
                if downloader.download_file(file_id, dataset, extension):
                    stats['downloaded'] += 1
                    found = True
                    break
                else:
                    stats['failed'] += 1
                    found = True
                    break
        
        if not found:
            stats['not_found'] += 1
    
    print(f"\n\nSummary:")
    print(f"  Total files: {stats['total_files']}")
    print(f"  Downloaded: {stats['downloaded']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Not found: {stats['not_found']}")

if __name__ == "__main__":
    import os
    main()
