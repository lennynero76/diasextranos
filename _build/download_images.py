#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descarga best-effort de las imágenes de los posts desde Wayback Machine.
Las que fallen se sirven en tiempo de ejecución vía el fallback onerror -> Wayback."""
import os, json, time, urllib.request, urllib.error

OUT = "/home/javierpva/diasextranos"
ASSETS_UP = os.path.join(OUT, "assets", "uploads")
URLS = os.path.join(OUT, "_build", "image_urls.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; diasextranos-archive/1.0)"}


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        ct = r.headers.get("Content-Type", "")
    return data, ct


def is_image(data, ct):
    if data[:3] == b"\xff\xd8\xff":      # jpg
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":  # png
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if "image/" in ct and len(data) > 600:
        return True
    return False


def nearest(orig_url):
    """Pregunta a la API de disponibilidad de Wayback por la captura más cercana."""
    api = "https://archive.org/wayback/available?url=" + urllib.parse.quote(orig_url, safe="")
    try:
        data, _ = fetch(api, timeout=25)
        j = json.loads(data)
        snap = j.get("archived_snapshots", {}).get("closest", {})
        if snap.get("available") and snap.get("url"):
            u = snap["url"]
            # forzar variante de imagen im_
            return u.replace("/http", "im_/http", 1) if "im_/" not in u else u
    except Exception:
        pass
    return None


def main():
    import urllib.parse  # noqa
    urls = json.load(open(URLS, encoding="utf-8"))
    ok = skip = fail = 0
    log = []
    for rel, wb_url in urls.items():
        dst = os.path.join(ASSETS_UP, rel)
        if os.path.exists(dst):
            skip += 1
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # 1) intento directo con el snapshot embebido
        got = None
        for attempt in (wb_url, None):
            url = attempt
            if url is None:
                # 2) fallback: snapshot más cercano de la URL original
                orig = wb_url
                import re
                m = re.search(r'(https?://(?:www\.)?diasextranos\.com.*)$', wb_url)
                if m:
                    orig = m.group(1)
                url = nearest(orig)
                if not url:
                    break
            try:
                data, ct = fetch(url)
                if is_image(data, ct):
                    got = data
                    break
            except Exception:
                pass
            time.sleep(0.4)
        if got:
            with open(dst, "wb") as f:
                f.write(got)
            ok += 1
        else:
            fail += 1
            log.append(rel)
        time.sleep(0.25)
    print(f"Descargadas: {ok} | ya presentes: {skip} | fallidas: {fail}")
    if log:
        with open(os.path.join(OUT, "_build", "images_failed.txt"), "w") as f:
            f.write("\n".join(log))
        print("Fallidas (usan fallback Wayback en runtime):", len(log))


if __name__ == "__main__":
    main()
