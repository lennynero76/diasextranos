#!/usr/bin/env python3
"""
Download Wayback Machine snapshots of key posts and extract + download images.
Uses the map of local SVGs referenced in HTML to know what to look for.
"""
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

SITE_ROOT = "/home/javierpva/diasextranos"
UPLOADS = os.path.join(SITE_ROOT, "assets/uploads")
SNAPSHOT_DIR = "/tmp/wb_snapshots"
UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# ── Build SVG map ─────────────────────────────────────────────────────────────
result = subprocess.run(
    ["grep", "-rh", r"\.svg", SITE_ROOT, "-R", "--include=*.html"],
    capture_output=True, text=True
)
svg_map = {}  # basename_lower -> (rel_path, local_svg_path)
for m in re.finditer(r'assets/uploads/((\d{4}/\d{2}/([^"\']+\.svg)))', result.stdout):
    rel = m.group(2)
    fname = os.path.basename(rel).lower()
    base = os.path.splitext(fname)[0]
    svg_map[base] = (rel, os.path.join(UPLOADS, rel))

print(f"SVGs needed: {len(svg_map)}")

# ── Page snapshots to fetch ───────────────────────────────────────────────────
with open("/tmp/cdx_pages.json") as f:
    cdx_data = json.load(f)

pages = {}
for row in cdx_data[1:]:
    ts, url, status, mime = row
    if status != "200" or "text/html" not in mime:
        continue
    url = url.replace(":80/", "/")
    if not any(skip in url for skip in ["/tag/", "/page/", "/author/", "/?", "/categoria/"]):
        if url not in pages or ts > pages[url]:
            pages[url] = ts

print(f"Page snapshots available: {len(pages)}")

# ── Download a page snapshot ──────────────────────────────────────────────────
def download_page(url, ts):
    cache_key = re.sub(r'[^a-z0-9]', '_', url.lower())[:80]
    cache_file = os.path.join(SNAPSHOT_DIR, f"{cache_key}.html")

    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 2000:
        with open(cache_file, errors='replace') as f:
            return f.read()

    wb_url = f"https://web.archive.org/web/{ts}id_/{url}"
    try:
        r = subprocess.run(
            ["curl", "-s", "-L", "-A", UA, "-o", cache_file,
             "-w", "%{http_code}", "--max-time", "20", wb_url],
            capture_output=True, text=True, timeout=25
        )
        if os.path.exists(cache_file) and os.path.getsize(cache_file) > 2000:
            with open(cache_file, errors='replace') as f:
                return f.read()
    except Exception:
        pass
    return None


# ── Extract images from HTML ──────────────────────────────────────────────────
def extract_images(html):
    """Extract (base_name, full_url) pairs for wp-content/uploads images."""
    found = {}
    patterns = [
        r'(?:src|href|content)=["\']([^"\']*?(?:wp-content|web\.archive)/[^\'"]*?/uploads/(\d{4}/\d{2}/[^"\']+\.(?:jpg|jpeg|png|gif|webp)))["\']',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.I):
            img_url = m.group(1)
            rel_part = m.group(2)  # YYYY/MM/filename.ext
            fname = os.path.basename(rel_part).lower()
            base = os.path.splitext(fname)[0]
            # Normalize URL - strip wayback prefix
            img_url = re.sub(r'https?://web\.archive\.org/web/\d+(?:id_)?/', '', img_url)
            if not img_url.startswith('http'):
                img_url = "http://www.diasextranos.com/" + img_url.lstrip('/')
            found[base] = (img_url, rel_part)
    return found


# ── Download image ────────────────────────────────────────────────────────────
def download_image(orig_url, rel_part, svg_local):
    ext = os.path.splitext(rel_part)[1].lower() or ".jpg"
    local = svg_local[:-4] + ext  # replace .svg with real ext

    if os.path.exists(local) and os.path.getsize(local) > 3000:
        fr = subprocess.run(["file", "--brief", "--mime-type", local],
                            capture_output=True, text=True, timeout=5)
        if fr.stdout.strip().startswith("image/"):
            return local

    os.makedirs(os.path.dirname(local), exist_ok=True)

    timestamps = ["20191001", "20181001", "20170601", "20160601", "20150601", "20140601", "20131201"]
    for ts in timestamps:
        wb_url = f"https://web.archive.org/web/{ts}id_/{orig_url}"
        try:
            r = subprocess.run(
                ["curl", "-s", "-L", "-A", UA, "-o", local,
                 "-w", "%{http_code}", "--max-time", "25", wb_url],
                capture_output=True, text=True, timeout=30
            )
            if os.path.exists(local) and os.path.getsize(local) > 3000:
                fr = subprocess.run(["file", "--brief", "--mime-type", local],
                                    capture_output=True, text=True, timeout=5)
                if fr.stdout.strip().startswith("image/"):
                    return local
            if os.path.exists(local):
                os.remove(local)
        except Exception:
            if os.path.exists(local):
                os.remove(local)
    return None


def update_html(svg_rel, new_ext):
    old_ref = f"assets/uploads/{svg_rel}"
    new_ref = old_ref[:-4] + new_ext
    r = subprocess.run(
        ["grep", "-rl", old_ref, SITE_ROOT, "--include=*.html"],
        capture_output=True, text=True
    )
    files = [f for f in r.stdout.strip().split("\n") if f]
    count = 0
    for fpath in files:
        with open(fpath, "r", errors="replace") as f:
            content = f.read()
        new_content = content.replace(old_ref, new_ref)
        if new_content != content:
            with open(fpath, "w") as f:
                f.write(new_content)
            count += 1
    return count


# ── Phase 1: Download pages and extract image URLs ────────────────────────────
print("\n[Phase 1] Downloading page snapshots and extracting image URLs...")

all_found_urls = {}  # base -> (img_url, rel_part, svg_info)

def process_page(args):
    url, ts = args
    html = download_page(url, ts)
    if not html:
        return {}
    imgs = extract_images(html)
    result = {}
    for base, (img_url, rel_part) in imgs.items():
        if base in svg_map:
            result[base] = (img_url, rel_part)
    return result

page_list = sorted(pages.items(), key=lambda x: x[1], reverse=True)

with ThreadPoolExecutor(max_workers=6) as ex:
    futures = {ex.submit(process_page, p): p for p in page_list}
    for i, fut in enumerate(as_completed(futures)):
        res = fut.result()
        for base, info in res.items():
            if base not in all_found_urls:
                all_found_urls[base] = info
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(futures)} pages, {len(all_found_urls)} image URLs found")

print(f"Total image URLs found in pages: {len(all_found_urls)}")

# ── Phase 2: Download images ──────────────────────────────────────────────────
print(f"\n[Phase 2] Downloading {len(all_found_urls)} images...")

ok = 0
fail = 0
skip = 0

def try_download(args):
    base, (img_url, rel_part) = args
    svg_rel, svg_local = svg_map[base]

    # Check if already downloaded
    ext = os.path.splitext(rel_part)[1]
    local = svg_local[:-4] + ext
    if os.path.exists(local) and os.path.getsize(local) > 3000:
        fr = subprocess.run(["file", "--brief", "--mime-type", local],
                            capture_output=True, text=True, timeout=5)
        if fr.stdout.strip().startswith("image/"):
            return ("SKIP", base, local)

    result = download_image(img_url, rel_part, svg_local)
    if result:
        return ("OK", base, result)
    return ("FAIL", base, None)

with ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(try_download, item): item for item in all_found_urls.items()}
    for fut in as_completed(futures):
        status, base, path = fut.result()
        if status == "OK":
            svg_rel, svg_local = svg_map[base]
            ext = os.path.splitext(path)[1]
            n = update_html(svg_rel, ext)
            size = os.path.getsize(path) // 1024
            print(f"  ✓ {os.path.basename(path)} ({size}KB, {n} HTML updated)")
            ok += 1
        elif status == "SKIP":
            svg_rel, svg_local = svg_map[base]
            ext = os.path.splitext(path)[1]
            update_html(svg_rel, ext)
            skip += 1
        else:
            print(f"  ✗ FAIL {base}")
            fail += 1

print(f"\n{'='*60}")
print(f"Downloaded: {ok} | Already existed: {skip} | Failed: {fail}")

# Show remaining SVGs
still_svg = subprocess.run(
    ["grep", "-rl", ".svg", SITE_ROOT, "--include=*.html"],
    capture_output=True, text=True
)
remaining = len([f for f in still_svg.stdout.strip().split() if f]) if still_svg.stdout.strip() else 0
print(f"Files still with SVG refs: {remaining}")
print("="*60)
