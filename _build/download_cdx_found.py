#!/usr/bin/env python3
"""Download all images found in CDX index and update HTML references."""
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

SITE_ROOT = "/home/javierpva/diasextranos"
UPLOADS = os.path.join(SITE_ROOT, "assets/uploads")
UA = "Mozilla/5.0 (compatible; Googlebot/2.1)"

with open("/tmp/cdx_images_all.json") as f:
    cdx_rows = json.load(f)

# Build: fname -> [(timestamp, url)]
by_fname = {}
for ts, orig, status, mime in cdx_rows:
    if status not in ("200", "301", "302") and status != "-":
        continue
    fname = orig.split("/")[-1].split("?")[0].lower()
    if fname not in by_fname:
        by_fname[fname] = []
    by_fname[fname].append((ts, orig))

# Sort by timestamp descending
for fname in by_fname:
    by_fname[fname].sort(key=lambda x: x[0], reverse=True)

print(f"Images in CDX index: {len(by_fname)}")

# Build map of SVG->local path from HTML references
result = subprocess.run(
    ["grep", "-rh", r"\.svg", SITE_ROOT, "-R", "--include=*.html"],
    capture_output=True, text=True
)
svg_map = {}  # fname_lower -> (rel_path, local_svg_path)
for m in re.finditer(r'assets/uploads/((\d{4}/\d{2}/([^"\']+\.svg)))', result.stdout):
    rel = m.group(2)
    fname = os.path.basename(rel).lower()
    svg_map[fname] = (rel, os.path.join(UPLOADS, rel))

print(f"SVGs referenced in HTML: {len(svg_map)}")

# Match CDX images to SVG placeholders
matches = []
for cdx_fname, entries in by_fname.items():
    base = os.path.splitext(cdx_fname)[0]
    for svg_fname, (rel, local_svg) in svg_map.items():
        svg_base = os.path.splitext(svg_fname)[0]
        if base == svg_base:
            matches.append((rel, local_svg, entries, cdx_fname))
            break

print(f"CDX matches for SVGs: {len(matches)}")


def download_and_update(args):
    rel, local_svg, entries, cdx_fname = args
    ext = os.path.splitext(cdx_fname)[1]
    local_path = local_svg[:-4] + ext

    # Skip if already exists and is valid
    if os.path.exists(local_path) and os.path.getsize(local_path) > 3000:
        fr = subprocess.run(["file", "--brief", "--mime-type", local_path],
                            capture_output=True, text=True, timeout=5)
        if fr.stdout.strip().startswith("image/"):
            # Update HTML anyway
            update_html(rel, ext)
            return f"ALREADY {os.path.basename(local_path)}"

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    for ts, orig_url in entries[:8]:
        wb_url = f"https://web.archive.org/web/{ts}id_/{orig_url}"
        try:
            r = subprocess.run(
                ["curl", "-s", "-L", "-A", UA, "-o", local_path,
                 "-w", "%{http_code}", "--max-time", "25", wb_url],
                capture_output=True, text=True, timeout=30
            )
            if os.path.exists(local_path) and os.path.getsize(local_path) > 3000:
                fr = subprocess.run(["file", "--brief", "--mime-type", local_path],
                                    capture_output=True, text=True, timeout=5)
                if fr.stdout.strip().startswith("image/"):
                    n = update_html(rel, ext)
                    return f"OK {os.path.basename(local_path)} ({os.path.getsize(local_path)//1024}KB, {n} HTML)"
            if os.path.exists(local_path):
                os.remove(local_path)
        except Exception as e:
            if os.path.exists(local_path):
                os.remove(local_path)

    return f"FAIL {os.path.basename(cdx_fname)}"


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


ok = 0
fail = 0
with ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(download_and_update, m): m for m in matches}
    for fut in as_completed(futures):
        res = fut.result()
        if res.startswith("OK") or res.startswith("ALREADY"):
            ok += 1
            print(f"  ✓ {res}")
        else:
            fail += 1
            print(f"  ✗ {res}")

print(f"\nTotal: {ok} OK, {fail} FAIL")
