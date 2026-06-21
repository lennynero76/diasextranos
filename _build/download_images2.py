#!/usr/bin/env python3
"""
Descarga imágenes del blog diasextranos.com desde Wayback Machine.
Las URLs ya vienen con el prefijo de Wayback Machine.
"""
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

FAILED_FILE = "/tmp/failed_images.txt"
OUTPUT_BASE = "/home/javierpva/diasextranos"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def parse_failed():
    """Parse the failed images file."""
    entries = []
    with open(FAILED_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            url, local = line.split("\t", 1)
            entries.append((url.strip(), local.strip()))
    return entries

def download_image(wb_url, local_path, timeout=20):
    """Download an image from Wayback Machine. Returns (success, source)."""
    full_local = os.path.join(OUTPUT_BASE, local_path)
    
    # Skip if already exists and is valid
    if os.path.exists(full_local) and os.path.getsize(full_local) > 500:
        return (True, "already_exists")
    
    # Create directory
    os.makedirs(os.path.dirname(full_local), exist_ok=True)
    
    # Try the URL as-is first (it already has the Wayback prefix)
    urls_to_try = [wb_url]
    
    # Also try without im_ prefix (some work with just id_)
    if "/im_/" in wb_url:
        urls_to_try.append(wb_url.replace("/im_/", "/id_/"))
    
    # Also try extracting the original URL and building a fresh Wayback URL
    # Original URL is embedded in the Wayback URL
    match = re.search(r'web\.archive\.org/web/\d+[a-z_]*/(https?://.*)', wb_url)
    if match:
        original_url = match.group(1)
        # Try with different timestamps
        for ts in ["20191030", "20180601", "20170101", "20160512", "20150101"]:
            for mode in ["id_", "im_"]:
                clean = re.sub(r'^https?://', '', original_url)
                urls_to_try.append(f"https://web.archive.org/web/{ts}{mode}/http://{clean}")
    
    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for u in urls_to_try:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)
    
    for try_url in unique_urls:
        try:
            result = subprocess.run(
                ["curl", "-s", "-L", "-A", USER_AGENT,
                 "-o", full_local, "-w", "%{http_code}",
                 "--max-time", str(timeout),
                 try_url],
                capture_output=True, text=True, timeout=timeout + 5
            )
            
            http_code = result.stdout.strip()
            
            if http_code == "200" and os.path.exists(full_local):
                size = os.path.getsize(full_local)
                if size > 500:
                    # Verify it's an image
                    file_result = subprocess.run(
                        ["file", "--brief", "--mime-type", full_local],
                        capture_output=True, text=True, timeout=5
                    )
                    mime = file_result.stdout.strip()
                    if mime.startswith("image/"):
                        return (True, try_url)
                    else:
                        os.remove(full_local)
                        continue
                else:
                    if os.path.exists(full_local):
                        os.remove(full_local)
                    continue
                    
        except (subprocess.TimeoutExpired, Exception) as e:
            if os.path.exists(full_local):
                os.remove(full_local)
            continue
    
    return (False, None)

def worker(args):
    """Worker function for parallel downloads."""
    wb_url, local_path = args
    
    # Check if already exists
    full_local = os.path.join(OUTPUT_BASE, local_path)
    if os.path.exists(full_local) and os.path.getsize(full_local) > 500:
        return (wb_url, local_path, "exists", None)
    
    success, source = download_image(wb_url, local_path)
    return (wb_url, local_path, "ok" if success else "failed", source)

def main():
    entries = parse_failed()
    
    print(f"Intentando descargar {len(entries)} imágenes con 6 hilos paralelos...\n")
    
    ok = 0
    failed = 0
    failed_list = []
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(worker, e): e for e in entries}
        
        for i, future in enumerate(as_completed(futures)):
            wb_url, local_path, result, source = future.result()
            
            if result in ("ok", "exists"):
                ok += 1
                status_icon = "✓"
            else:
                failed += 1
                failed_list.append((wb_url, local_path))
                status_icon = "✗"
            
            progress = (i + 1) / len(entries) * 100
            filename = os.path.basename(local_path)
            print(f"[{progress:5.1f}%] {status_icon} {filename}")
    
    elapsed = time.time() - start
    
    print(f"\n{'='*60}")
    print(f"Descarga completada en {elapsed:.1f}s")
    print(f"  OK:     {ok}")
    print(f"  Fallo:  {failed}")
    print(f"  Total:  {len(entries)}")
    
    # Save failed list
    if failed_list:
        with open("/tmp/failed_images2.txt", "w") as f:
            for url, local in failed_list:
                f.write(f"{url}\t{local}\n")
        print(f"\nImágenes fallidas guardadas en /tmp/failed_images2.txt")
    
    return failed == 0

if __name__ == "__main__":
    main()
