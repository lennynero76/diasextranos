#!/usr/bin/env python3
"""
Descarga imágenes del blog diasextranos.com desde Wayback Machine.
Lee el reporte de imágenes y descarga las faltantes.
"""
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPORT_FILE = "/tmp/images_report.txt"
OUTPUT_BASE = "/home/javierpva/diasextranos/assets/uploads"
WAYBACK_TIMESTAMPS = [
    "20191030",
    "20190101",
    "20180601",
    "20170601",
    "20161025",
    "20160512",
    "20150101",
    "20140101",
    "20130101",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def parse_report():
    """Parse the images report and return list of (url, local_path, status) tuples."""
    entries = []
    current = {}
    
    with open(REPORT_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("URL:"):
                current["url"] = line.split("URL:", 1)[1].strip()
            elif line.startswith("LOCAL:"):
                current["local"] = line.split("LOCAL:", 1)[1].strip()
            elif line.startswith("STATO:") or line.startswith("STATUS:"):
                current["status"] = line.split(":", 1)[1].strip()
                if current.get("url") and current.get("local"):
                    entries.append((current["url"], current["local"], current["status"]))
                current = {}
    
    return entries

def build_wayback_url(original_url, timestamp):
    """Build a Wayback Machine URL for the given original URL and timestamp."""
    # Strip protocol
    clean = re.sub(r'^https?://', '', original_url)
    return f"https://web.archive.org/web/{timestamp}id_/http://{clean}"

def download_image(url, local_path, timeout=15):
    """Try to download an image from Wayback Machine. Returns (success, final_url)."""
    full_local = os.path.join("/home/javierpva/diasextranos", local_path)
    
    # Skip if already exists
    if os.path.exists(full_local) and os.path.getsize(full_local) > 100:
        return (True, "already_exists")
    
    # Create directory
    os.makedirs(os.path.dirname(full_local), exist_ok=True)
    
    # Try each timestamp
    for ts in WAYBACK_TIMESTAMPS:
        wb_url = build_wayback_url(url, ts)
        try:
            result = subprocess.run(
                ["curl", "-s", "-L", "-A", USER_AGENT,
                 "-o", full_local, "-w", "%{http_code}",
                 "--max-time", str(timeout),
                 wb_url],
                capture_output=True, text=True, timeout=timeout + 5
            )
            
            http_code = result.stdout.strip()
            
            if http_code == "200" and os.path.exists(full_local):
                size = os.path.getsize(full_local)
                # Check it's actually an image, not an HTML error page
                if size > 500:
                    # Verify it's an image
                    file_result = subprocess.run(
                        ["file", "--brief", "--mime-type", full_local],
                        capture_output=True, text=True, timeout=5
                    )
                    mime = file_result.stdout.strip()
                    if mime.startswith("image/"):
                        return (True, wb_url)
                    else:
                        # Not an image, remove and try next
                        os.remove(full_local)
                        continue
                else:
                    # Too small, probably not an image
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
    url, local_path, status = args
    if status == "[EXISTS]":
        return (url, local_path, "exists", None)
    
    success, source = download_image(url, local_path)
    return (url, local_path, "ok" if success else "failed", source)

def main():
    entries = parse_report()
    
    # Filter to only missing images
    missing = [(url, local, status) for url, local, status in entries if status != "[EXISTS]"]
    exists_count = len(entries) - len(missing)
    
    print(f"Total imágenes: {len(entries)}")
    print(f"Ya existen: {exists_count}")
    print(f"Faltantes: {len(missing)}")
    print(f"Descargando con {min(8, len(missing))} hilos paralelos...\n")
    
    ok = 0
    failed = 0
    failed_list = []
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(worker, e): e for e in missing}
        
        for i, future in enumerate(as_completed(futures)):
            url, local_path, result, source = future.result()
            
            if result in ("ok", "exists"):
                ok += 1
                status_icon = "✓"
            else:
                failed += 1
                failed_list.append((url, local_path))
                status_icon = "✗"
            
            # Progress
            progress = (i + 1) / len(missing) * 100
            filename = os.path.basename(local_path)
            print(f"[{progress:5.1f}%] {status_icon} {filename}")
    
    elapsed = time.time() - start
    
    print(f"\n{'='*60}")
    print(f"Descarga completada en {elapsed:.1f}s")
    print(f"  OK:     {ok}")
    print(f"  Fallo:  {failed}")
    print(f"  Total:  {len(missing)}")
    
    # Save failed list
    if failed_list:
        with open("/tmp/failed_images.txt", "w") as f:
            for url, local in failed_list:
                f.write(f"{url}\t{local}\n")
        print(f"\nImágenes fallidas guardadas en /tmp/failed_images.txt")
    
    return failed == 0

if __name__ == "__main__":
    main()
