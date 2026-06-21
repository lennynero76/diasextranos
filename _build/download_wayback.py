#!/usr/bin/env python3
"""
Recupera imágenes faltantes usando:
1. CDX API de Wayback Machine (busca snapshots reales)
2. Descarga directa con timestamps encontrados
"""
import os
import re
import subprocess
import sys
import time
import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

REPORT_FILE = "/tmp/images_report.txt"
OUTPUT_BASE = "/home/javierpva/diasextranos"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

stats = {"cdx_ok": 0, "direct_ok": 0, "failed": 0, "exists": 0}
CDX_CACHE = {}  # cache CDX results

def is_real_image(path):
    """Verifica que el archivo es una imagen real."""
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        return False
    try:
        result = subprocess.run(
            ["file", "--brief", "--mime-type", path],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip().startswith("image/")
    except Exception:
        return False

def extract_original_url(wb_url):
    """Extrae la URL original de una URL de Wayback Machine."""
    m = re.search(r'web\.archive\.org/web/\d+[a-z_]*/(.+)', wb_url)
    if m:
        return m.group(1)
    return wb_url

def cdx_get_timestamps(original_url):
    """Usa CDX API para obtener timestamps donde fue capturada la URL."""
    if original_url in CDX_CACHE:
        return CDX_CACHE[original_url]

    # Remove protocol for CDX
    url_for_cdx = re.sub(r'^https?://', '', original_url)
    encoded = urllib.parse.quote(url_for_cdx, safe='/:@?=&')
    cdx_url = (
        f"http://web.archive.org/cdx/search/cdx"
        f"?url={encoded}&output=json&limit=8"
        f"&fl=timestamp,statuscode&filter=statuscode:200"
        f"&collapse=timestamp:8"
    )

    try:
        req = urllib.request.Request(cdx_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        if data and len(data) > 1:
            timestamps = [row[0] for row in data[1:]]
            CDX_CACHE[original_url] = timestamps
            return timestamps
    except Exception as e:
        pass

    CDX_CACHE[original_url] = []
    return []

def curl_download(url, dest_path, timeout=30):
    """Descarga con curl y verifica que es imagen real."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = dest_path + ".tmp"

    try:
        result = subprocess.run(
            ["curl", "-s", "-L", "-A", USER_AGENT,
             "-o", tmp_path, "-w", "%{http_code}",
             "--max-time", str(timeout),
             "--max-filesize", "10485760",  # 10MB max
             "--connect-timeout", "15",
             url],
            capture_output=True, text=True, timeout=timeout + 10
        )
        http_code = result.stdout.strip()

        if os.path.exists(tmp_path) and is_real_image(tmp_path):
            os.rename(tmp_path, dest_path)
            return True
        else:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return False
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False

def process_image(wb_url, local_path):
    """Intenta recuperar una imagen usando múltiples estrategias."""
    full_dest = os.path.join(OUTPUT_BASE, local_path)

    if is_real_image(full_dest):
        return "exists"

    original_url = extract_original_url(wb_url)

    # Estrategia 1: Intentar la URL de Wayback directamente (con im_)
    # Asegurarse de que tiene im_
    if "web.archive.org" in wb_url:
        # Normalizar a formato im_
        direct_url = re.sub(
            r'(web\.archive\.org/web/\d+)(?:[a-z_]*)/',
            r'\1im_/',
            wb_url
        )
        if curl_download(direct_url, full_dest, timeout=25):
            return "direct"

        # También probar sin modificador
        plain_url = re.sub(
            r'(web\.archive\.org/web/\d+)(?:[a-z_]*)/',
            r'\1/',
            wb_url
        )
        if plain_url != direct_url and curl_download(plain_url, full_dest, timeout=25):
            return "direct"

    # Estrategia 2: CDX API para buscar otros timestamps
    if "wp-content/uploads" in original_url:
        timestamps = cdx_get_timestamps(original_url)
        time.sleep(0.3)  # rate limit CDX

        for ts in timestamps[:6]:
            wb_try = f"https://web.archive.org/web/{ts}im_/{original_url}"
            if curl_download(wb_try, full_dest, timeout=25):
                return "cdx"
            time.sleep(0.2)

    # Estrategia 3: Probar con URL-encoding del nombre (para caracteres especiales)
    filename = os.path.basename(original_url)
    encoded_filename = urllib.parse.quote(filename, safe='')
    if encoded_filename != filename:
        encoded_original = original_url[:-len(filename)] + encoded_filename
        timestamps2 = cdx_get_timestamps(encoded_original)
        time.sleep(0.3)
        for ts in timestamps2[:3]:
            wb_try = f"https://web.archive.org/web/{ts}im_/{encoded_original}"
            if curl_download(wb_try, full_dest, timeout=25):
                return "cdx"
            time.sleep(0.2)

    return "failed"

def parse_report():
    """Lee el reporte y retorna las imágenes faltantes."""
    entries = []
    current = {}
    with open(REPORT_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("URL:"):
                current["url"] = line.split("URL:", 1)[1].strip()
            elif line.startswith("LOCAL:"):
                current["local"] = line.split("LOCAL:", 1)[1].strip()
            elif line.startswith("STATO:"):
                current["status"] = line.split(":", 1)[1].strip()
                if current.get("url") and current.get("local"):
                    entries.append(dict(current))
                current = {}
    return entries

def worker(entry):
    url = entry["url"]
    local = entry["local"]
    full = os.path.join(OUTPUT_BASE, local)

    if is_real_image(full):
        return ("exists", local, url)

    result = process_image(url, local)
    time.sleep(0.4)  # rate limiting entre imágenes
    return (result, local, url)

def main():
    entries = parse_report()
    missing = [e for e in entries if e["status"] == "[MISSING]"]

    # Verificar cuáles siguen faltando en disco
    still_missing = [
        e for e in missing
        if not is_real_image(os.path.join(OUTPUT_BASE, e["local"]))
    ]

    print(f"Imágenes en reporte [MISSING]: {len(missing)}")
    print(f"Siguen faltando en disco: {len(still_missing)}")
    print(f"Usando CDX API + descarga directa...\n")

    ok_direct = 0
    ok_cdx = 0
    failed = 0
    exists = 0
    failed_list = []

    start = time.time()
    total = len(still_missing)

    # Procesamiento con 3 workers paralelos (respetando rate limits)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(worker, e): e for e in still_missing}

        for i, future in enumerate(as_completed(futures)):
            result, local_path, url = future.result()
            filename = os.path.basename(local_path)

            if result == "exists":
                exists += 1
                print(f"[{i+1:3d}/{total}] = {filename}")
            elif result == "direct":
                ok_direct += 1
                print(f"[{i+1:3d}/{total}] ✓ DIRECT: {filename}")
            elif result == "cdx":
                ok_cdx += 1
                print(f"[{i+1:3d}/{total}] ✓ CDX:    {filename}")
            else:
                failed += 1
                failed_list.append(local_path)
                print(f"[{i+1:3d}/{total}] ✗ FAIL:   {filename}")

    elapsed = time.time() - start
    total_ok = ok_direct + ok_cdx

    print(f"\n{'='*60}")
    print(f"RESUMEN - Completado en {elapsed:.0f}s")
    print(f"  Ya existían:          {exists}")
    print(f"  Recuperadas (directo): {ok_direct}")
    print(f"  Recuperadas (CDX):     {ok_cdx}")
    print(f"  TOTAL RECUPERADAS:     {total_ok}")
    print(f"  Fallidas:              {failed}")
    print(f"{'='*60}")

    if failed_list:
        with open("/tmp/failed_images.txt", "w") as f:
            for p in failed_list:
                f.write(p + "\n")
        print(f"\nListado de fallidas: /tmp/failed_images.txt")

    return total_ok

if __name__ == "__main__":
    main()
