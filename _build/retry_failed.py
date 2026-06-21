#!/usr/bin/env python3
"""
Reintenta descargar las imágenes fallidas con timestamps más recientes.
"""
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_BASE = "/home/javierpva/diasextranos/assets/uploads"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Failed images from previous run - map local path -> original URL
FAILED = [
    ("2010/09/charly-garcia.jpg", "http://www.diasextranos.com/wp-content/uploads/2010/09/charly-garcia.jpg"),
    ("2011/01/John-Barry2.jpg", "http://www.diasextranos.com/wp-content/uploads/2011/01/John-Barry2.jpg"),
    ("2011/01/Los-80...jpg", "http://www.diasextranos.com/wp-content/uploads/2011/01/Los-80...jpg"),
    ("2011/01/Los-80..II_.jpg", "http://www.diasextranos.com/wp-content/uploads/2011/01/Los-80..II_.jpg"),
    ("2011/01/Mumford-Sons.jpg", "http://www.diasextranos.com/wp-content/uploads/2011/01/Mumford-Sons.jpg"),
    ("2011/01/Pete-And-The-Pirates.jpg", "http://www.diasextranos.com/wp-content/uploads/2011/01/Pete-And-The-Pirates.jpg"),
    ("2011/01/sexy-sadie.jpg", "http://www.diasextranos.com/wp-content/uploads/2011/01/sexy-sadie.jpg"),
    ("2011/01/Sunrise.jpg", "http://www.diasextranos.com/wp-content/uploads/2011/01/Sunrise.jpg"),
    ("2011/01/The-Strokes.jpeg", "http://www.diasextranos.com/wp-content/uploads/2011/01/The-Strokes.jpeg"),
    ("2011/02/Fleet-Foxes.jpg", "http://www.diasextranos.com/wp-content/uploads/2011/02/Fleet-Foxes.jpg"),
    ("2011/02/Maja-Ivarsson.jpg", "http://www.diasextranos.com/wp-content/uploads/2011/02/Maja-Ivarsson.jpg"),
    ("2011/02/The-White-Stripes.jpg", "http://www.diasextranos.com/wp-content/uploads/2011/02/The-White-Stripes.jpg"),
    ("2012/01/Cabeza.jpg", "http://www.diasextranos.com/wp-content/uploads/2012/01/Cabeza.jpg"),
    ("2012/01/mullet-300x225.jpg", "http://www.diasextranos.com/wp-content/uploads/2012/01/mullet-300x225.jpg"),
    ("2013/11/Austra.jpg", "http://www.diasextranos.com/wp-content/uploads/2013/11/Austra.jpg"),
    ("2013/11/Chvrches.jpg", "http://www.diasextranos.com/wp-content/uploads/2013/11/Chvrches.jpg"),
    ("2013/11/Manel.jpg", "http://www.diasextranos.com/wp-content/uploads/2013/11/Manel.jpg"),
    ("2013/11/Hypnolove.jpg", "http://www.diasextranos.com/wp-content/uploads/2013/11/Hypnolove.jpg"),
    ("2013/11/Mikal-Cronin.jpg", "http://www.diasextranos.com/wp-content/uploads/2013/11/Mikal-Cronin.jpg"),
    ("2015/07/Florence-The-Machine.jpg", "http://www.diasextranos.com/wp-content/uploads/2015/07/Florence-The-Machine.jpg"),
    ("2015/08/Lana-del-Rey.jpg", "http://www.diasextranos.com/wp-content/uploads/2015/08/Lana-del-Rey.jpg"),
    ("2015/08/Tame-Impala1.jpg", "http://www.diasextranos.com/wp-content/uploads/2015/08/Tame-Impala1.jpg"),
    ("2015/08/Young-Galaxy.jpg", "http://www.diasextranos.com/wp-content/uploads/2015/08/Young-Galaxy.jpg"),
]

# Timestamps to try (newer first)
TIMESTAMPS = [
    "20191030", "20180601", "20170101", "20161025", "20160926",
    "20160812", "20160624", "20160215", "20160212", "20160207",
    "20160120", "20160113", "20150412", "20140625", "20140603",
    "20140530", "20140528", "20131209",
]

def download_with_retry(local_rel, original_url, timeout=15):
    """Try downloading with multiple timestamps."""
    full_local = os.path.join(OUTPUT_BASE, local_rel)
    
    if os.path.exists(full_local) and os.path.getsize(full_local) > 500:
        return (local_rel, True, "already_exists")
    
    os.makedirs(os.path.dirname(full_local), exist_ok=True)
    
    for ts in TIMESTAMPS:
        wb_url = f"https://web.archive.org/web/{ts}id_/{original_url}"
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
                    file_result = subprocess.run(
                        ["file", "--brief", "--mime-type", full_local],
                        capture_output=True, text=True, timeout=5
                    )
                    mime = file_result.stdout.strip()
                    if mime.startswith("image/"):
                        return (local_rel, True, f"ts={ts}, {size}B")
                    else:
                        os.remove(full_local)
                        continue
                else:
                    if os.path.exists(full_local):
                        os.remove(full_local)
                    continue
        except Exception:
            if os.path.exists(full_local):
                os.remove(full_local)
            continue
    
    return (local_rel, False, "all timestamps failed")

def worker(args):
    local_rel, original_url = args
    return download_with_retry(local_rel, original_url)

def main():
    print(f"Reintentando {len(FAILED)} imágenes fallidas...\n")
    
    ok = 0
    failed = 0
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(worker, e): e for e in FAILED}
        
        for i, future in enumerate(as_completed(futures)):
            local_rel, success, msg = future.result()
            
            if success:
                ok += 1
                icon = "✓"
            else:
                failed += 1
                icon = "✗"
            
            progress = (i + 1) / len(FAILED) * 100
            filename = os.path.basename(local_rel)
            print(f"[{progress:5.1f}%] {icon} {filename} ({msg})")
    
    elapsed = time.time() - start
    print(f"\nCompletado en {elapsed:.1f}s | OK: {ok} | Fallo: {failed}")

if __name__ == "__main__":
    main()
