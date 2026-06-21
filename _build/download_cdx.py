#!/usr/bin/env python3
"""
Descarga imágenes del CDX API de Wayback Machine.
Lee /tmp/cdx_uploads.json y descarga todas las imágenes encontradas.
"""
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

CDX_FILE = "/tmp/cdx_uploads.json"
OUTPUT_BASE = "/home/javierpva/diasextranos/assets/uploads"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def parse_cdx():
    """Parse CDX JSON and return list of (timestamp, original_url) tuples."""
    entries = []
    with open(CDX_FILE) as f:
        data = json.load(f)
    
    # Skip header row
    for row in data[1:]:
        timestamp, original, statuscode, mimetype = row
        entries.append((timestamp, original, mimetype))
    
    return entries

def url_to_local_path(url):
    """Convert wp-content/uploads URL to local path."""
    # Extract path after wp-content/uploads/
    idx = url.find("wp-content/uploads/")
    if idx == -1:
        return None
    rel = url[idx + len("wp-content/uploads/"):]
    rel = rel.split("?")[0]  # Remove query params
    return rel

def download_image(timestamp, original_url, mimetype, timeout=20):
    """Download image from Wayback Machine."""
    local_rel = url_to_local_path(original_url)
    if not local_rel:
        return (original_url, False, "can't parse path")
    
    full_local = os.path.join(OUTPUT_BASE, local_rel)
    
    # Skip if already exists and valid
    if os.path.exists(full_local) and os.path.getsize(full_local) > 500:
        return (local_rel, True, "already_exists")
    
    os.makedirs(os.path.dirname(full_local), exist_ok=True)
    
    # Build Wayback URL with id_ (identity mode)
    wb_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"
    
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
            if size > 500:
                # Verify it's an image
                file_result = subprocess.run(
                    ["file", "--brief", "--mime-type", full_local],
                    capture_output=True, text=True, timeout=5
                )
                mime = file_result.stdout.strip()
                if mime.startswith("image/"):
                    return (local_rel, True, f"downloaded {size}B")
                else:
                    os.remove(full_local)
                    return (local_rel, False, f"not image: {mime}")
            else:
                if os.path.exists(full_local):
                    os.remove(full_local)
                return (local_rel, False, f"too small: {size}B")
        else:
            if os.path.exists(full_local):
                os.remove(full_local)
            return (local_rel, False, f"HTTP {http_code}")
    except Exception as e:
        if os.path.exists(full_local):
            os.remove(full_local)
        return (local_rel, False, str(e))

def worker(args):
    timestamp, original_url, mimetype = args
    local_rel, success, msg = download_image(timestamp, original_url, mimetype)
    return (local_rel, success, msg, original_url)

def main():
    entries = parse_cdx()
    print(f"CDX API encontró {len(entries)} imágenes con snapshots válidos")
    print(f"Descargando con 6 hilos paralelos...\n")
    
    ok = 0
    failed = 0
    failed_list = []
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(worker, e): e for e in entries}
        
        for i, future in enumerate(as_completed(futures)):
            local_rel, success, msg, original = future.result()
            
            if success:
                ok += 1
                icon = "✓"
            else:
                failed += 1
                failed_list.append((local_rel, msg))
                icon = "✗"
            
            progress = (i + 1) / len(entries) * 100
            filename = os.path.basename(local_rel) if local_rel else "?"
            print(f"[{progress:5.1f}%] {icon} {filename} ({msg})")
    
    elapsed = time.time() - start
    
    print(f"\n{'='*60}")
    print(f"Completado en {elapsed:.1f}s")
    print(f"  OK:     {ok}")
    print(f"  Fallo:  {failed}")
    
    if failed_list:
        print(f"\nFallidas:")
        for path, msg in failed_list:
            print(f"  {path}: {msg}")
    
    # Count total images now
    total = sum(1 for _ in walk_files(OUTPUT_BASE))
    print(f"\nTotal imágenes en assets/uploads/: {total}")

def walk_files(path):
    for root, dirs, files in os.walk(path):
        for f in files:
            yield os.path.join(root, f)

if __name__ == "__main__":
    main()
