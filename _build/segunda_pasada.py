#!/usr/bin/env python3
"""
Segunda pasada CDX API: consultas adicionales + descarga + actualizar HTML.
"""
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_BASE = "/home/javierpva/diasextranos/assets/uploads"
SITE_ROOT = "/home/javierpva/diasextranos"
USER_AGENT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
WORKERS = 5

CDX_QUERIES = [
    # Sin filtro de statuscode (captura 301/302 también)
    "http://web.archive.org/cdx/search/cdx?url=www.diasextranos.com/wp-content/uploads/*&output=json&from=2010&to=2020&limit=50000&fl=timestamp,original,statuscode,mimetype&filter=mimetype:image",
    # JPEG específico
    "http://web.archive.org/cdx/search/cdx?url=www.diasextranos.com/wp-content/uploads/*&output=json&from=2010&to=2020&limit=50000&fl=timestamp,original,statuscode,mimetype&filter=mimetype:image/jpeg",
    # PNG específico
    "http://web.archive.org/cdx/search/cdx?url=www.diasextranos.com/wp-content/uploads/*&output=json&from=2010&to=2020&limit=50000&fl=timestamp,original,statuscode,mimetype&filter=mimetype:image/png",
    # GIF específico
    "http://web.archive.org/cdx/search/cdx?url=www.diasextranos.com/wp-content/uploads/*&output=json&from=2010&to=2020&limit=50000&fl=timestamp,original,statuscode,mimetype&filter=mimetype:image/gif",
]


def fetch_cdx(url):
    """Fetch CDX API URL and return list of [timestamp, original, statuscode, mimetype]."""
    print(f"  Consultando: {url[:80]}...")
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "60", url],
            capture_output=True, text=True, timeout=65
        )
        data = json.loads(result.stdout)
        # Skip header row
        if data and data[0] == ["timestamp", "original", "statuscode", "mimetype"]:
            return data[1:]
        return data
    except Exception as e:
        print(f"  ERROR fetching CDX: {e}")
        return []


def url_to_local_path(url):
    """Convert wp-content/uploads URL to local relative path."""
    idx = url.find("wp-content/uploads/")
    if idx == -1:
        return None
    rel = url[idx + len("wp-content/uploads/"):]
    rel = rel.split("?")[0].split("#")[0]
    return rel


def get_existing_real_images():
    """Return set of relative paths for existing non-SVG images."""
    existing = set()
    for root, dirs, files in os.walk(OUTPUT_BASE):
        for f in files:
            if not f.endswith(".svg"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, OUTPUT_BASE)
                existing.add(rel)
    return existing


def get_svgs():
    """Return set of relative paths for SVG placeholders."""
    svgs = set()
    for root, dirs, files in os.walk(OUTPUT_BASE):
        for f in files:
            if f.endswith(".svg"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, OUTPUT_BASE)
                svgs.add(rel)
    return svgs


def build_best_candidates(all_entries):
    """
    De-duplicate CDX entries: for each unique URL, keep the entry with the latest timestamp.
    Prefer status 200 over redirects.
    """
    # key = normalized original URL (lowercase)
    best = {}  # url -> (timestamp, original, statuscode, mimetype)

    for row in all_entries:
        if len(row) < 4:
            continue
        timestamp, original, statuscode, mimetype = row[0], row[1], row[2], row[3]

        # Only process image mimetypes
        if not mimetype.startswith("image/"):
            continue

        key = original.lower()
        if key not in best:
            best[key] = (timestamp, original, statuscode, mimetype)
        else:
            existing_ts, existing_orig, existing_sc, existing_mime = best[key]
            # Prefer status 200; then prefer later timestamp
            if statuscode == "200" and existing_sc != "200":
                best[key] = (timestamp, original, statuscode, mimetype)
            elif existing_sc == "200" and statuscode != "200":
                pass  # keep existing
            elif timestamp > existing_ts:
                best[key] = (timestamp, original, statuscode, mimetype)

    return list(best.values())


def download_image(timestamp, original_url, statuscode, mimetype, timeout=25):
    """Download image from Wayback Machine."""
    local_rel = url_to_local_path(original_url)
    if not local_rel:
        return (original_url, False, "can't parse path", None)

    full_local = os.path.join(OUTPUT_BASE, local_rel)

    # Skip if already exists as real image (non-SVG)
    if os.path.exists(full_local) and not full_local.endswith(".svg"):
        size = os.path.getsize(full_local)
        if size > 500:
            return (local_rel, True, "already_exists", local_rel)

    os.makedirs(os.path.dirname(full_local), exist_ok=True)

    # Build Wayback URL with id_ (raw identity mode)
    wb_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"

    try:
        result = subprocess.run(
            ["curl", "-s", "-L", "-A", USER_AGENT,
             "-o", full_local, "-w", "%{http_code}",
             "--max-time", str(timeout),
             "--connect-timeout", "10",
             wb_url],
            capture_output=True, text=True, timeout=timeout + 10
        )

        http_code = result.stdout.strip()
        if http_code == "200" and os.path.exists(full_local):
            size = os.path.getsize(full_local)
            if size > 500:
                file_result = subprocess.run(
                    ["file", "--brief", "--mime-type", full_local],
                    capture_output=True, text=True, timeout=5
                )
                mime = file_result.stdout.strip()
                if mime.startswith("image/"):
                    return (local_rel, True, f"ok {size}B", local_rel)
                else:
                    os.remove(full_local)
                    return (local_rel, False, f"not image: {mime}", None)
            else:
                if os.path.exists(full_local):
                    os.remove(full_local)
                return (local_rel, False, f"too small: {size}B", None)
        else:
            if os.path.exists(full_local):
                os.remove(full_local)
            return (local_rel, False, f"HTTP {http_code}", None)
    except Exception as e:
        if os.path.exists(full_local):
            try:
                os.remove(full_local)
            except:
                pass
        return (local_rel, False, str(e)[:60], None)


def update_html_files(newly_downloaded):
    """
    Update all index.html files:
    - Replace .svg references with the real image extension if real image exists locally.
    """
    # Build a map: svg_rel_path -> real_rel_path (if real image exists)
    replacements = {}

    for root, dirs, files in os.walk(OUTPUT_BASE):
        for f in files:
            if f.endswith(".svg"):
                svg_full = os.path.join(root, f)
                svg_rel = os.path.relpath(svg_full, OUTPUT_BASE)
                base_no_ext = os.path.splitext(svg_full)[0]
                for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                    candidate = base_no_ext + ext
                    if os.path.exists(candidate) and os.path.getsize(candidate) > 500:
                        real_rel = os.path.relpath(candidate, OUTPUT_BASE)
                        replacements[svg_rel] = real_rel
                        break

    if not replacements:
        print("No hay reemplazos SVG→imagen para hacer en HTML.")
        return 0

    print(f"\nReemplazos SVG→imagen disponibles: {len(replacements)}")

    html_files = []
    for root, dirs, files in os.walk(SITE_ROOT):
        # Skip hidden dirs and _build
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['_build', 'node_modules']]
        for f in files:
            if f == "index.html":
                html_files.append(os.path.join(root, f))

    updated_files = 0
    total_replacements = 0

    for html_path in html_files:
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                content = f.read()

            new_content = content
            changes = 0
            for svg_rel, real_rel in replacements.items():
                svg_web = "/assets/uploads/" + svg_rel.replace(os.sep, "/")
                real_web = "/assets/uploads/" + real_rel.replace(os.sep, "/")
                if svg_web in new_content:
                    new_content = new_content.replace(svg_web, real_web)
                    changes += new_content.count(real_web)  # approximate

            if new_content != content:
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                updated_files += 1
                total_replacements += 1  # at least 1 change per file

        except Exception as e:
            print(f"  ERROR actualizando {html_path}: {e}")

    print(f"HTML actualizados: {updated_files} archivos")
    return updated_files


def count_real_images():
    count = 0
    for root, dirs, files in os.walk(OUTPUT_BASE):
        for f in files:
            if not f.endswith(".svg"):
                count += 1
    return count


def main():
    print("=" * 60)
    print("SEGUNDA PASADA CDX API")
    print("=" * 60)

    # Step 1: Fetch CDX data from all queries
    print("\n[1/4] Consultando CDX API...")
    all_entries = []
    for q in CDX_QUERIES:
        entries = fetch_cdx(q)
        print(f"       → {len(entries)} entradas")
        all_entries.extend(entries)
        time.sleep(1)  # Cortesía con Wayback Machine

    print(f"\nTotal entradas CDX (con duplicados): {len(all_entries)}")

    # Step 2: De-duplicate and find candidates
    candidates = build_best_candidates(all_entries)
    print(f"URLs únicas: {len(candidates)}")

    # Step 3: Filter out already-downloaded real images
    existing_real = get_existing_real_images()
    print(f"Imágenes reales ya locales: {len(existing_real)}")

    to_download = []
    already_have = 0
    for ts, orig, sc, mime in candidates:
        local_rel = url_to_local_path(orig)
        if not local_rel:
            continue
        if local_rel in existing_real:
            already_have += 1
            continue
        to_download.append((ts, orig, sc, mime))

    print(f"Ya tenemos: {already_have}")
    print(f"A descargar: {len(to_download)}")

    # Step 4: Download
    print(f"\n[2/4] Descargando {len(to_download)} imágenes con {WORKERS} hilos...")
    downloaded_ok = 0
    downloaded_fail = 0
    newly_downloaded = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(download_image, ts, orig, sc, mime): (ts, orig)
                   for ts, orig, sc, mime in to_download}

        for i, future in enumerate(as_completed(futures)):
            local_rel, success, msg, real_path = future.result()
            filename = os.path.basename(local_rel) if local_rel else "?"

            if success and msg != "already_exists":
                downloaded_ok += 1
                newly_downloaded.append(local_rel)
                print(f"  [{i+1}/{len(to_download)}] ✓ {filename} ({msg})")
            elif msg == "already_exists":
                pass  # silencio
            else:
                downloaded_fail += 1
                if "HTTP 404" not in msg and "HTTP 503" not in msg:
                    print(f"  [{i+1}/{len(to_download)}] ✗ {filename} ({msg})")

    elapsed = time.time() - start
    print(f"\nDescarga completada en {elapsed:.1f}s")
    print(f"  Descargadas OK:  {downloaded_ok}")
    print(f"  Fallidas:        {downloaded_fail}")

    # Step 5: Update HTML
    print("\n[3/4] Actualizando referencias HTML (.svg → imagen real)...")
    updated = update_html_files(newly_downloaded)

    # Step 6: Summary
    total_real = count_real_images()
    total_svgs = sum(1 for root, dirs, files in os.walk(OUTPUT_BASE)
                     for f in files if f.endswith(".svg"))

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  Imágenes nuevas encontradas (CDX):  {len(to_download)}")
    print(f"  Imágenes descargadas exitosamente:  {downloaded_ok}")
    print(f"  Total imágenes reales locales:      {total_real}")
    print(f"  Placeholders SVG restantes:         {total_svgs}")
    print(f"  Archivos HTML actualizados:         {updated}")
    print("=" * 60)


if __name__ == "__main__":
    main()
