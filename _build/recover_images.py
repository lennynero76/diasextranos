#!/usr/bin/env python3
"""
Script to recover missing images from Wayback Machine and generate SVG placeholders.
"""

import os
import re
import sys
import time
import json
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SITE_ROOT = Path("/home/javierpva/diasextranos")
REPORT_FILE = Path("/tmp/images_report.txt")
MAX_WORKERS = 5
REQUEST_TIMEOUT = 30
START_TIME = time.time()
MAX_DURATION = 8 * 60  # 8 minutes

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; diasextranos-recovery/1.0)",
}

def time_left():
    return MAX_DURATION - (time.time() - START_TIME)

def parse_report():
    """Extract missing image entries from the report."""
    text = REPORT_FILE.read_text(encoding="utf-8")
    blocks = text.split("URL:")

    missing = []
    for block in blocks[1:]:
        if "[MISSING]" not in block:
            continue
        lines = block.strip().splitlines()
        url_line = lines[0].strip()
        orig = None
        local = None
        for line in lines:
            if line.strip().startswith("ORIG:"):
                orig = line.split("ORIG:")[1].strip()
            if line.strip().startswith("LOCAL:"):
                local = line.split("LOCAL:")[1].strip()
        missing.append({
            "url": url_line,
            "orig": orig,
            "local": local,
        })
    return missing


def http_get(url, timeout=REQUEST_TIMEOUT):
    """Simple HTTP GET, returns bytes or None."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read()
    except Exception:
        pass
    return None


def try_wayback_direct(entry):
    """Try to download the image directly from the Wayback URL if it's a WB URL."""
    url = entry["url"]
    if "web.archive.org" not in url:
        return None

    # The URL already has im_ format — try it directly
    data = http_get(url)
    if data and len(data) > 500:
        return data

    # If the URL has im_, also try without im_ (raw)
    if "im_/" in url:
        raw_url = url.replace("im_/", "/")
        data = http_get(raw_url)
        if data and len(data) > 500:
            return data

    return None


def try_cdx_api(orig_url):
    """Query Wayback CDX API for available snapshots of orig_url."""
    if not orig_url:
        return None
    encoded = urllib.parse.quote(orig_url, safe="")
    cdx_url = (
        f"http://web.archive.org/cdx/search/cdx"
        f"?url={encoded}&output=json&limit=5&fl=timestamp,statuscode,mimetype"
        f"&filter=statuscode:200&filter=mimetype:image/"
    )
    data = http_get(cdx_url, timeout=15)
    if not data:
        return None
    try:
        rows = json.loads(data.decode("utf-8"))
        if len(rows) <= 1:  # Only header row
            return None
        # rows[0] is header, rest are results
        for row in rows[1:]:
            ts, status, mime = row[0], row[1], row[2]
            if status == "200" and mime.startswith("image/"):
                wb_url = f"https://web.archive.org/web/{ts}id_/{orig_url}"
                img_data = http_get(wb_url)
                if img_data and len(img_data) > 500:
                    return img_data
    except Exception:
        pass
    return None


def download_image(entry):
    """Try all strategies to download an image. Returns (entry, data_or_None)."""
    if time_left() < 10:
        return entry, None

    # Strategy 1: direct Wayback URL
    data = try_wayback_direct(entry)
    if data:
        return entry, data

    # Strategy 2: CDX API with orig URL
    if entry.get("orig"):
        data = try_cdx_api(entry["orig"])
        if data:
            return entry, data

    # Strategy 3: CDX API with direct URL if it's not a WB URL
    if "web.archive.org" not in entry["url"] and entry["url"] != entry.get("orig"):
        data = try_cdx_api(entry["url"])
        if data:
            return entry, data

    return entry, None


def save_image(entry, data):
    """Save image data to local path."""
    local_path = SITE_ROOT / entry["local"]
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(data)
    return local_path


def make_svg_placeholder(filename, width=300, height=200):
    """Generate an SVG placeholder with the filename."""
    name_display = Path(filename).stem
    # Escape XML chars
    name_display = name_display.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Truncate if too long
    if len(name_display) > 30:
        name_display = name_display[:28] + "…"

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="#2a2a2a" rx="4"/>
  <rect x="2" y="2" width="{width-4}" height="{height-4}" fill="none" stroke="#6d97b7" stroke-width="1" rx="3" stroke-dasharray="6,4"/>
  <!-- Broken image icon -->
  <g transform="translate({width//2-24},{height//2-28})">
    <rect x="2" y="4" width="36" height="28" rx="2" fill="none" stroke="#6d97b7" stroke-width="2"/>
    <polyline points="2,24 10,14 18,20 26,10 40,28" fill="none" stroke="#6d97b7" stroke-width="2"/>
    <circle cx="12" cy="12" r="3" fill="#6d97b7"/>
    <line x1="0" y1="28" x2="6" y2="22" stroke="#6d97b7" stroke-width="2"/>
    <line x1="38" y1="6" x2="32" y2="12" stroke="#6d97b7" stroke-width="2"/>
    <line x1="0" y1="28" x2="38" y2="6" stroke="#6d97b7" stroke-width="1.5" opacity="0.5"/>
  </g>
  <text x="{width//2}" y="{height//2+20}" text-anchor="middle"
        font-family="Georgia, serif" font-size="11" fill="#6d97b7" opacity="0.9">
    {name_display}
  </text>
  <text x="{width//2}" y="{height-10}" text-anchor="middle"
        font-family="Georgia, serif" font-size="9" fill="#404040">
    imagen no disponible
  </text>
</svg>'''
    return svg


def create_placeholder(entry):
    """Create SVG placeholder for a missing image."""
    local_path = SITE_ROOT / entry["local"]
    filename = local_path.name
    # Determine SVG path (same dir, same name but .svg)
    svg_name = Path(filename).stem + ".svg"
    svg_path = local_path.parent / svg_name
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_content = make_svg_placeholder(filename)
    svg_path.write_text(svg_content, encoding="utf-8")
    return svg_path


def update_html_files(placeholder_map):
    """Replace image references in HTML files with placeholder paths."""
    html_files = list(SITE_ROOT.rglob("*.html"))
    updated_count = 0
    files_changed = 0

    for html_file in html_files:
        try:
            content = html_file.read_text(encoding="utf-8")
        except Exception:
            continue

        original = content
        for orig_ref, placeholder_rel in placeholder_map.items():
            if orig_ref in content:
                content = content.replace(orig_ref, placeholder_rel)
                updated_count += 1

        if content != original:
            html_file.write_text(content, encoding="utf-8")
            files_changed += 1

    return files_changed, updated_count


def build_placeholder_map(failed_entries):
    """Build a map of old image refs → new SVG placeholder refs."""
    placeholder_map = {}

    for entry in failed_entries:
        local = entry["local"]
        stem = Path(local).stem
        ext_free = str(Path(local).parent / stem)
        svg_rel = ext_free + ".svg"

        # Map the original URL patterns to the SVG placeholder
        # Pattern 1: assets/uploads/... path in HTML
        orig_assets_path = local  # e.g. assets/uploads/2013/05/Mark-Oliver-Everett.jpg
        placeholder_assets_path = svg_rel
        placeholder_map[orig_assets_path] = placeholder_assets_path

        # Pattern 2: Wayback URL
        if "web.archive.org" in entry["url"]:
            placeholder_map[entry["url"]] = "/" + svg_rel

        # Pattern 3: original URL
        if entry.get("orig"):
            placeholder_map[entry["orig"]] = "/" + svg_rel

        # Pattern 4: direct URL (non-WB)
        if "web.archive.org" not in entry["url"] and entry.get("orig") != entry["url"]:
            placeholder_map[entry["url"]] = "/" + svg_rel

    return placeholder_map


def main():
    print("=" * 60)
    print("RECUPERACIÓN DE IMÁGENES - diasextranos.com")
    print("=" * 60)

    missing = parse_report()
    print(f"\nImágenes faltantes: {len(missing)}")

    # --- Paso 1: Descargar desde Wayback ---
    print(f"\n[PASO 1] Intentando descargar desde Wayback Machine ({MAX_WORKERS} hilos)...")

    downloaded = []
    failed = []

    futures_map = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for entry in missing:
            if time_left() < 30:
                print("  ⚠ Tiempo límite alcanzado, saltando descargas restantes")
                failed.extend([e for e in missing if e not in downloaded and e not in failed])
                break
            future = executor.submit(download_image, entry)
            futures_map[future] = entry

        for future in as_completed(futures_map):
            entry, data = future.result()
            local_path = SITE_ROOT / entry["local"]
            if data:
                try:
                    save_image(entry, data)
                    downloaded.append(entry)
                    print(f"  ✓ {entry['local']}")
                except Exception as e:
                    print(f"  ✗ Error guardando {entry['local']}: {e}")
                    failed.append(entry)
            else:
                failed.append(entry)
                print(f"  ✗ {Path(entry['local']).name}")

    print(f"\nDescargadas: {len(downloaded)} | Fallidas: {len(failed)}")

    # --- Paso 2: Placeholders SVG ---
    print(f"\n[PASO 2] Generando placeholders SVG para {len(failed)} imágenes...")

    placeholder_paths = []
    for entry in failed:
        svg_path = create_placeholder(entry)
        placeholder_paths.append(svg_path)
        print(f"  ✎ {svg_path.relative_to(SITE_ROOT)}")

    # --- Paso 3: Actualizar HTML ---
    print(f"\n[PASO 3] Actualizando referencias HTML...")

    placeholder_map = build_placeholder_map(failed)
    files_changed, refs_updated = update_html_files(placeholder_map)
    print(f"  Archivos HTML modificados: {files_changed}")
    print(f"  Referencias actualizadas: {refs_updated}")

    # --- Resumen ---
    elapsed = time.time() - START_TIME
    print("\n" + "=" * 60)
    print("RESUMEN FINAL")
    print("=" * 60)
    print(f"Tiempo total: {elapsed:.1f}s")
    print(f"Imágenes descargadas desde Wayback: {len(downloaded)}")
    print(f"Placeholders SVG generados: {len(failed)}")
    print(f"Archivos HTML actualizados: {files_changed}")

    if downloaded:
        print("\nDescargadas:")
        for e in downloaded:
            print(f"  ✓ {e['local']}")

    if failed:
        print(f"\nPlaceholders SVG (imágenes no recuperadas): {len(failed)}")
        for e in failed[:10]:
            print(f"  ✎ {e['local']}")
        if len(failed) > 10:
            print(f"  ... y {len(failed)-10} más")


if __name__ == "__main__":
    main()
