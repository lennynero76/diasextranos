#!/usr/bin/env python3
"""
Recuperación completa de imágenes faltantes:
1. CDX API sin filtro de statuscode
2. Page snapshots de Wayback Machine
3. Descarga de imágenes
4. Actualización de HTML
"""
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

SITE_ROOT = "/home/javierpva/diasextranos"
UPLOADS = os.path.join(SITE_ROOT, "assets/uploads")
UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
SNAPSHOT_DIR = "/tmp/wb_snapshots"
os.makedirs(SNAPSHOT_DIR, exist_ok=True)


# ── 1. Recopilar SVGs referenciados en HTML ────────────────────────────────────
def collect_needed():
    """Return dict: relative_path -> set of full local target paths."""
    result = subprocess.run(
        ["grep", "-rh", r"\.svg", "-R", SITE_ROOT, "--include=*.html"],
        capture_output=True, text=True
    )
    needed = {}
    for m in re.finditer(r'(?:src|href|content)=["\']([^"\']*assets/uploads/([^"\']*\.svg))["\']',
                         result.stdout):
        full_ref, rel = m.group(1), m.group(2)
        local = os.path.join(UPLOADS, rel)
        if not needed.get(rel):
            needed[rel] = local
    print(f"  SVGs referenciados en HTML: {len(needed)}")
    return needed


# ── 2. CDX API queries ─────────────────────────────────────────────────────────
def fetch_cdx_year(year):
    url = (
        f"http://web.archive.org/cdx/search/cdx"
        f"?url=www.diasextranos.com/wp-content/uploads/{year}/*"
        f"&output=json&limit=10000"
        f"&fl=timestamp,original,statuscode,mimetype"
    )
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "30", url],
            capture_output=True, text=True, timeout=35
        )
        data = json.loads(r.stdout)
        if data and data[0] == ["timestamp", "original", "statuscode", "mimetype"]:
            data = data[1:]
        return data
    except Exception as e:
        print(f"    CDX {year} error: {e}")
        return []


def build_cdx_index():
    """Returns dict: basename_lower -> [(timestamp, full_url, status)]"""
    index = {}
    years = [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018]
    print(f"  Consultando CDX API para {len(years)} años (sin filtro status)...")
    for year in years:
        rows = fetch_cdx_year(year)
        for ts, orig, status, mime in rows:
            if not any(orig.lower().endswith(e) for e in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                continue
            fname = os.path.basename(orig.split("?")[0]).lower()
            if fname not in index:
                index[fname] = []
            index[fname].append((ts, orig, status))
        time.sleep(0.5)
    # Sort by timestamp descending
    for fname in index:
        index[fname].sort(key=lambda x: x[0], reverse=True)
    print(f"  CDX index: {len(index)} nombres únicos de imagen")
    return index


# ── 3. Download image from Wayback Machine ─────────────────────────────────────
def download_image(orig_url, timestamp, local_svg_path):
    """Download image replacing the SVG placeholder. Returns local path or None."""
    # Determine local path with correct extension
    ext_orig = os.path.splitext(orig_url.split("?")[0])[1].lower()
    if not ext_orig:
        ext_orig = ".jpg"
    base = local_svg_path[:-4]  # strip .svg
    local_path = base + ext_orig

    if os.path.exists(local_path) and os.path.getsize(local_path) > 3000:
        return local_path

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    # Try direct Wayback URL
    wb_url = f"https://web.archive.org/web/{timestamp}id_/{orig_url}"
    try:
        r = subprocess.run(
            ["curl", "-s", "-L", "-A", UA, "-o", local_path, "-w", "%{http_code}",
             "--max-time", "20", wb_url],
            capture_output=True, text=True, timeout=25
        )
        if r.stdout.strip() in ("200", "301", "302") and os.path.exists(local_path):
            size = os.path.getsize(local_path)
            if size > 3000:
                fr = subprocess.run(["file", "--brief", "--mime-type", local_path],
                                    capture_output=True, text=True, timeout=5)
                if fr.stdout.strip().startswith("image/"):
                    return local_path
            if os.path.exists(local_path):
                os.remove(local_path)
    except Exception:
        if os.path.exists(local_path):
            os.remove(local_path)
    return None


# ── 4. Page snapshots ─────────────────────────────────────────────────────────
def get_page_snapshots():
    """Return list of (url, timestamp) for page snapshots."""
    with open("/tmp/cdx_pages.json") as f:
        data = json.load(f)
    pages = {}
    for row in data[1:]:
        ts, url, status, mime = row
        if status != "200" or "text/html" not in mime:
            continue
        url = url.replace(":80/", "/")
        if url not in pages or ts > pages[url]:
            pages[url] = ts
    # Filter to actual posts (not tags, categories, etc.)
    posts = [(url, ts) for url, ts in pages.items()
             if not any(x in url for x in ['/tag/', '/categoria/', '/author/', '/page/', '/?'])]
    return sorted(posts, key=lambda x: x[1], reverse=True)[:50]


def download_page_html(url, timestamp):
    """Download page snapshot HTML. Returns HTML string or None."""
    cache_key = re.sub(r'[^a-z0-9]', '_', url.lower())[:80]
    cache_file = os.path.join(SNAPSHOT_DIR, f"{cache_key}.html")
    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 2000:
        with open(cache_file, errors='replace') as f:
            return f.read()
    wb_url = f"https://web.archive.org/web/{timestamp}id_/{url}"
    try:
        r = subprocess.run(
            ["curl", "-s", "-L", "-A", UA, "-o", cache_file,
             "-w", "%{http_code}", "--max-time", "15", wb_url],
            capture_output=True, text=True, timeout=20
        )
        if r.stdout.strip() == "200" and os.path.exists(cache_file):
            with open(cache_file, errors='replace') as f:
                return f.read()
    except Exception:
        pass
    return None


def extract_image_urls_from_html(html):
    """Extract wp-content/uploads image URLs from HTML."""
    urls = []
    for m in re.finditer(r'(?:src|href|content)=["\']([^"\']*wp-content/uploads/[^"\']+\.(?:jpg|jpeg|png|gif|webp))["\']',
                         html, re.I):
        url = m.group(1)
        # Normalize to bare URL (strip wayback prefix)
        url = re.sub(r'https?://web\.archive\.org/web/\d+(?:id_)?/', '', url)
        if 'diasextranos.com' in url or url.startswith('/wp-content/'):
            urls.append(url)
    return list(set(urls))


def process_page_for_images(args, needed_lower):
    """Download page and return list of (orig_url, fname_lower) for needed images."""
    url, ts = args
    html = download_page_html(url, ts)
    if not html:
        return []
    found = []
    for img_url in extract_image_urls_from_html(html):
        fname = os.path.basename(img_url.split("?")[0]).lower()
        # Check if this is a needed image (match by basename without extension)
        base = os.path.splitext(fname)[0]
        for needed_rel in needed_lower:
            needed_base = os.path.splitext(os.path.basename(needed_rel))[0].lower()
            if base == needed_base:
                found.append((img_url, needed_rel))
    return found


# ── 5. Update HTML references ──────────────────────────────────────────────────
def update_html_references(svg_rel, new_ext):
    """Replace .svg references with new_ext in all HTML files."""
    old_ref = f"assets/uploads/{svg_rel}"
    new_ref = old_ref[:-4] + new_ext

    result = subprocess.run(
        ["grep", "-rl", old_ref, SITE_ROOT, "--include=*.html"],
        capture_output=True, text=True
    )
    files = result.stdout.strip().split("\n") if result.stdout.strip() else []
    count = 0
    for fpath in files:
        if not fpath:
            continue
        with open(fpath, 'r', errors='replace') as f:
            content = f.read()
        new_content = content.replace(old_ref, new_ref)
        if new_content != content:
            with open(fpath, 'w') as f:
                f.write(new_content)
            count += 1
    return count


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "=" * 60)
    print("RECUPERACIÓN DE IMÁGENES - diasextranos.com")
    print("=" * 60)

    # Step 1: Collect needed images
    print("\n[1] Recopilando imágenes faltantes...")
    needed = collect_needed()
    needed_lower = {rel.lower(): rel for rel in needed}

    # Step 2: CDX index
    print("\n[2] Construyendo índice CDX (todos los años, sin filtro status)...")
    cdx_index = build_cdx_index()

    # Step 3: Try to download via CDX index
    print("\n[3] Descargando desde CDX index...")
    recovered_cdx = {}
    tasks = []
    for rel_lower, rel in list(needed_lower.items()):
        base = os.path.splitext(os.path.basename(rel_lower))[0]
        # Try exact match and variations
        for fname_key in cdx_index:
            key_base = os.path.splitext(fname_key)[0]
            if key_base == base:
                entries = cdx_index[fname_key]
                tasks.append((rel, rel_lower, needed[rel], entries))
                break

    print(f"  Encontrados en CDX: {len(tasks)} de {len(needed)}")

    def try_download_cdx(args):
        rel, rel_lower, local_svg, entries = args
        for ts, orig_url, status in entries[:5]:  # try up to 5 timestamps
            result = download_image(orig_url, ts, local_svg)
            if result:
                return (rel, result)
        return None

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(try_download_cdx, t): t for t in tasks}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                rel, local_path = res
                ext = os.path.splitext(local_path)[1]
                recovered_cdx[rel] = local_path
                n = update_html_references(rel, ext)
                print(f"  ✓ {os.path.basename(rel)} ({os.path.getsize(local_path)//1024}KB, {n} HTML)")

    print(f"  CDX: {len(recovered_cdx)} recuperadas")

    # Update needed list
    for rel in recovered_cdx:
        if rel.lower() in needed_lower:
            del needed_lower[rel.lower()]

    print(f"  Aún faltan: {len(needed_lower)}")

    # Step 4: Page snapshots
    print("\n[4] Procesando snapshots de páginas...")
    pages = get_page_snapshots()
    print(f"  {len(pages)} snapshots de posts")

    recovered_pages = {}
    page_found_urls = {}

    def try_page(args):
        return process_page_for_images(args, needed_lower)

    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(try_page, p): p for p in pages[:40]}
        for fut in as_completed(futures):
            results = fut.result()
            for img_url, needed_rel in results:
                if needed_rel not in page_found_urls:
                    page_found_urls[needed_rel] = img_url

    print(f"  URLs encontradas en páginas: {len(page_found_urls)}")

    # Download found URLs
    def download_from_page_url(args):
        needed_rel_lower, img_url = args
        needed_rel = needed_lower.get(needed_rel_lower, needed_rel_lower)
        local_svg = needed.get(needed_rel, os.path.join(UPLOADS, needed_rel))

        # Build full URL
        if img_url.startswith('/wp-content/'):
            img_url = f"http://www.diasextranos.com{img_url}"
        elif not img_url.startswith('http'):
            img_url = f"http://www.diasextranos.com/wp-content/uploads/{img_url}"

        # Try multiple timestamps
        for ts in ["20191001", "20180601", "20170101", "20160601", "20150601", "20140601"]:
            result = download_image(img_url, ts, local_svg)
            if result:
                return (needed_rel_lower, result)
        return None

    page_tasks = [(rel_lower, url) for rel_lower, url in page_found_urls.items()
                  if rel_lower not in {r.lower() for r in recovered_cdx}]

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(download_from_page_url, t): t for t in page_tasks}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                rel_lower, local_path = res
                ext = os.path.splitext(local_path)[1]
                recovered_pages[rel_lower] = local_path
                rel = needed_lower.get(rel_lower, rel_lower)
                n = update_html_references(rel, ext)
                print(f"  ✓ {os.path.basename(local_path)} ({os.path.getsize(local_path)//1024}KB, {n} HTML)")

    print(f"  Pages: {len(recovered_pages)} recuperadas")

    # ── Final report ──────────────────────────────────────────────────────────
    total = len(recovered_cdx) + len(recovered_pages)
    still_needed = len(needed_lower) - len(recovered_pages)

    print("\n" + "=" * 60)
    print("RESUMEN FINAL")
    print("=" * 60)
    print(f"  Imágenes recuperadas via CDX:    {len(recovered_cdx)}")
    print(f"  Imágenes recuperadas via páginas: {len(recovered_pages)}")
    print(f"  TOTAL recuperadas:               {total}")
    print(f"  SVGs aún en HTML:                ~{max(0, 165 - total)}")
    print("=" * 60)

    return total


if __name__ == "__main__":
    main()
