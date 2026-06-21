#!/usr/bin/env python3
"""
Descarga snapshots de posts desde Wayback Machine y extrae imágenes del HTML.
"""
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlunparse

OUTPUT_BASE = "/home/javierpva/diasextranos"
SNAPSHOT_DIR = "/tmp/wb_snapshots"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Images we still need (from the failed list)
NEEDED_IMAGES = set()
with open("/tmp/images_report.txt") as f:
    current = {}
    for line in f:
        line = line.strip()
        if line.startswith("URL:"):
            current["url"] = line.split("URL:", 1)[1].strip()
        elif line.startswith("LOCAL:"):
            current["local"] = line.split("LOCAL:", 1)[1].strip()
        elif line.startswith("STATO:") or line.startswith("STATUS:"):
            current["status"] = line.split(":", 1)[1].strip()
            if current.get("url") and current.get("local") and current["status"] != "[EXISTS]":
                # Check if we really don't have it
                full = os.path.join(OUTPUT_BASE, "assets/uploads", current["local"])
                if not os.path.exists(full) or os.path.getsize(full) < 500:
                    fname = os.path.basename(current["local"])
                    NEEDED_IMAGES.add(fname.lower())
            current = {}

print(f"Imágenes que necesitamos: {len(NEEDED_IMAGES)}")

# Read CDX pages
with open("/tmp/cdx_pages.json") as f:
    cdx_data = json.load(f)

# Build list of page snapshots to download
# Group by URL, take most recent timestamp
pages = {}
for row in cdx_data[1:]:
    ts, url, status, mime = row
    if status != "200" or "text/html" not in mime:
        continue
    # Normalize URL
    url = url.replace(":80/", "/")
    if url not in pages or ts > pages[url]:
        pages[url] = ts

print(f"Unique pages with snapshots: {len(pages)}")

def download_page(url, timestamp):
    """Download a page snapshot from Wayback Machine."""
    cache_key = re.sub(r'[^a-z0-9]', '_', url.lower())[:100]
    cache_file = os.path.join(SNAPSHOT_DIR, f"{cache_key}.html")
    
    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 1000:
        with open(cache_file) as f:
            return f.read()
    
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    wb_url = f"https://web.archive.org/web/{timestamp}id_/{url}"
    
    try:
        result = subprocess.run(
            ["curl", "-s", "-L", "-A", USER_AGENT,
             "-o", cache_file, "-w", "%{http_code}",
             "--max-time", "15",
             wb_url],
            capture_output=True, text=True, timeout=20
        )
        
        if result.stdout.strip() == "200" and os.path.exists(cache_file):
            with open(cache_file) as f:
                return f.read()
    except Exception:
        pass
    
    return None

def extract_images_from_html(html, page_url):
    """Extract image URLs from HTML content."""
    images = []
    
    # Find all img src attributes
    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I):
        img_url = match.group(1)
        if "wp-content/uploads" in img_url:
            # Extract filename
            fname = os.path.basename(img_url.split("?")[0])
            if fname.lower() in NEEDED_IMAGES:
                images.append((img_url, fname))
    
    # Also find in content div
    content_match = re.search(r'<div[^>]+class=["\'][^"\']*entry-content[^"\']*["\'][^>]*>(.*?)</div>', html, re.I | re.S)
    if content_match:
        content = content_match.group(1)
        for match in re.finditer(r'(?:src|href)=["\']([^"\']*wp-content/uploads/[^"\']+)["\']', content, re.I):
            img_url = match.group(1)
            fname = os.path.basename(img_url.split("?")[0])
            if fname.lower() in NEEDED_IMAGES:
                images.append((img_url, fname))
    
    return images

def download_image(img_url, timeout=15):
    """Download an image from Wayback Machine."""
    # Extract path after wp-content/uploads/
    idx = img_url.find("wp-content/uploads/")
    if idx == -1:
        return None
    rel = img_url[idx + len("wp-content/uploads/"):].split("?")[0]
    
    full_local = os.path.join(OUTPUT_BASE, "assets/uploads", rel)
    if os.path.exists(full_local) and os.path.getsize(full_local) > 500:
        return full_local
    
    os.makedirs(os.path.dirname(full_local), exist_ok=True)
    
    # Try multiple timestamps
    for ts in ["20191030", "20180601", "20170101", "20161025", "20160926", "20160812", "20160624", "20160215", "20160212", "20160207", "20160120", "20160113", "20150412", "20140625", "20140603", "20140530", "20140528", "20131209"]:
        wb_url = f"https://web.archive.org/web/{ts}id_/{img_url}"
        try:
            result = subprocess.run(
                ["curl", "-s", "-L", "-A", USER_AGENT,
                 "-o", full_local, "-w", "%{http_code}",
                 "--max-time", str(timeout),
                 wb_url],
                capture_output=True, text=True, timeout=timeout + 5
            )
            
            if result.stdout.strip() == "200" and os.path.exists(full_local):
                size = os.path.getsize(full_local)
                if size > 500:
                    file_result = subprocess.run(
                        ["file", "--brief", "--mime-type", full_local],
                        capture_output=True, text=True, timeout=5
                    )
                    mime = file_result.stdout.strip()
                    if mime.startswith("image/"):
                        return full_local
                    else:
                        os.remove(full_local)
                        continue
                else:
                    if os.path.exists(full_local):
                        os.remove(full_local)
        except Exception:
            if os.path.exists(full_local):
                os.remove(full_local)
            continue
    
    return None

def process_page(args):
    """Download a page and extract images."""
    url, timestamp = args
    html = download_page(url, timestamp)
    if not html:
        return []
    
    images = extract_images_from_html(html, url)
    results = []
    for img_url, fname in images:
        result = download_image(img_url)
        if result:
            results.append((fname, result))
    
    return results

def main():
    # Prioritize pages that are likely to have images
    # Sort by timestamp (newest first)
    sorted_pages = sorted(pages.items(), key=lambda x: x[1], reverse=True)
    
    print(f"\nProcesando {len(sorted_pages)} páginas para extraer imágenes...\n")
    
    found_images = {}
    pages_processed = 0
    
    # Process pages in parallel
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(process_page, p): p for p in sorted_pages[:100]}  # Top 100 pages
        
        for i, future in enumerate(as_completed(futures)):
            results = future.result()
            pages_processed += 1
            
            for fname, path in results:
                if fname.lower() not in found_images:
                    found_images[fname.lower()] = path
                    print(f"  ✓ {fname} ({os.path.getsize(path)}B)")
            
            if pages_processed % 10 == 0:
                print(f"  Procesadas {pages_processed} páginas, {len(found_images)} imágenes encontradas")
            
            # Stop if we found all needed images
            if len(found_images) >= len(NEEDED_IMAGES):
                print(f"\n¡Todas las imágenes encontradas!")
                break
    
    print(f"\n{'='*60}")
    print(f"Páginas procesadas: {pages_processed}")
    print(f"Imágenes encontradas: {len(found_images)}")
    print(f"Imágenes que necesitábamos: {len(NEEDED_IMAGES)}")
    
    if found_images:
        with open("/tmp/found_from_pages.json", "w") as f:
            json.dump(found_images, f, indent=2)
        print(f"\nImágenes guardadas en /tmp/found_from_pages.json")

if __name__ == "__main__":
    main()
