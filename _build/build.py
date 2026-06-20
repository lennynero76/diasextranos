#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador estático de Días Extraños.
Convierte los posts HTML archivados (dos temas de WordPress distintos) en un
sitio estático limpio listo para desplegar en Vercel.
"""
import os, re, json, glob, shutil, html as htmllib
from datetime import datetime
from bs4 import BeautifulSoup, Comment, NavigableString

SRC          = "/home/javierpva/diasextranos_posts"
UPLOADS_LOCAL = "/home/javierpva/diasextranos_rebuild/web/wp-content/uploads"
OUT          = "/home/javierpva/diasextranos"
ASSETS_UP    = os.path.join(OUT, "assets", "uploads")

SITE_NAME   = "Días Extraños"
SITE_DESC   = "Los Diarios de Lenny Nero"
SITE_URL    = "https://diasextranos.com"
AUTHOR      = "Lenny Nero"

MONTHS = ["enero","febrero","marzo","abril","mayo","junio","julio",
          "agosto","septiembre","octubre","noviembre","diciembre"]

# Categorías principales del blog (slug -> nombre mostrado)
CAT_NAMES = {
    "musica":     "Música",
    "favoritos":  "Favoritos",
    "cine":       "Cine",
    "literatura": "Literatura",
    "historia":   "Historia",
    "opinion":    "Opinión",
    "tecnologia": "Tecnología",
    "copyfight":  "Copyfight",
    "chorradas":  "Chorradas",
    "general":    "General",
    "varios":     "Varios",
}
# Orden de aparición en el menú
CAT_ORDER = ["musica","favoritos","cine","literatura","historia",
             "opinion","tecnologia","copyfight","chorradas","general","varios"]

# Categorías con contenido (se rellena en main); por defecto todas
ACTIVE_CATS = list(CAT_ORDER)

WB_PREFIX = re.compile(r'^(?:https?:)?//web\.archive\.org/web/\d+[a-z_]*?/(.*)$', re.I)


def strip_wayback(url):
    """Quita el prefijo de Wayback Machine y devuelve la URL original."""
    if not url:
        return url
    m = WB_PREFIX.match(url.strip())
    if not m:
        return url
    rest = m.group(1)
    if rest.startswith("http://") or rest.startswith("https://"):
        return rest
    if rest.startswith("//"):
        return "https:" + rest
    # a veces queda "http:/dominio" -> normalizar
    rest = re.sub(r'^https?:/(?!/)', lambda mm: mm.group(0)[:-1] + "//", rest)
    return rest


def slugify_segment(url):
    """De una URL de diasextranos.com devuelve el slug del post si aplica."""
    o = strip_wayback(url)
    m = re.match(r'https?://(?:www\.)?diasextranos\.com(?::80)?/([^/?#]+)/?$', o)
    if m:
        return m.group(1)
    return None


def upload_rel(url):
    """Devuelve la ruta relativa dentro de wp-content/uploads, o None."""
    m = re.search(r'wp-content/uploads/(.+)$', url)
    if m:
        return m.group(1).split('?')[0]
    return None


def parse_spanish_date(s):
    """Parsea fechas tipo '1 agosto 2013, 10:41 am'."""
    if not s:
        return None
    m = re.search(r'(\d{1,2})\s+de?\s*([a-záéíóú]+)\s+de?\s*(\d{4})', s, re.I)
    if not m:
        m = re.search(r'(\d{1,2})\s+([a-záéíóú]+)\s+(\d{4})', s, re.I)
    if not m:
        return None
    day, mon, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    if mon in MONTHS:
        return datetime(year, MONTHS.index(mon) + 1, day)
    return None


def pretty_date(dt):
    return f"{dt.day} de {MONTHS[dt.month-1]} de {dt.year}"


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Parseo de un post
# ---------------------------------------------------------------------------
def meta(soup, prop=None, name=None):
    if prop:
        t = soup.find("meta", attrs={"property": prop})
    else:
        t = soup.find("meta", attrs={"name": name})
    return t["content"].strip() if t and t.has_attr("content") else None


def parse_post(path, valid_slugs):
    slug = os.path.basename(path)[:-5]
    soup = BeautifulSoup(read(path), "html.parser")

    # --- Título ---
    title = meta(soup, prop="og:title")
    if not title:
        h = soup.select_one("h1.entry-title, h2.posttitle")
        title = h.get_text(strip=True) if h else slug
    title = re.sub(r'\s*[-«]\s*Días Extraños.*$', '', title).strip()
    title = re.sub(r'\s*Días Extraños\s*$', '', title).strip()

    # --- Fecha ---
    iso = meta(soup, prop="article:published_time")
    dt = None
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            dt = None
    if dt is None:
        t = soup.find("time", class_="entry-date")
        if t and t.has_attr("datetime"):
            try:
                dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                dt = None
    if dt is None:
        pd = soup.find("span", class_="postdate")
        if pd:
            dt = parse_spanish_date(pd.get_text(" ", strip=True))
    if dt is None:
        dt = datetime(2000, 1, 1)

    # --- Artículo / clases ---
    art = soup.find(id=re.compile(r'^post-\d+'))
    cats, tagslugs = [], []
    if art and art.has_attr("class"):
        for c in art["class"]:
            if c.startswith("category-"):
                cats.append(c[len("category-"):])
            elif c.startswith("tag-"):
                tagslugs.append(c[len("tag-"):])
    main_cats = [c for c in cats if c in CAT_NAMES]
    if not main_cats:
        main_cats = ["general"]
    # de-dup conservando orden
    main_cats = list(dict.fromkeys(main_cats))

    # --- Nombres de etiquetas desde los enlaces /tag/ ---
    tag_names = {}
    for a in soup.find_all("a", rel="tag"):
        href = a.get("href", "")
        tm = re.search(r'/tag/([^/]+)/', href)
        if tm:
            tag_names[tm.group(1)] = a.get_text(strip=True)
    tags = [tag_names.get(t, t.replace("-", " ").title()) for t in tagslugs]

    # --- Imagen destacada ---
    thumb = meta(soup, prop="og:image")

    # --- Descripción ---
    desc = meta(soup, name="description") or ""

    # --- Contenido ---
    content_el = soup.select_one("div.entry-content, div.postentry")
    content_html, excerpt = clean_content(content_el, valid_slugs) if content_el else ("", "")
    if not excerpt:
        excerpt = desc

    return {
        "slug": slug,
        "title": title,
        "dt": dt,
        "iso": dt.strftime("%Y-%m-%d"),
        "date_pretty": pretty_date(dt),
        "year": dt.year,
        "cats": main_cats,
        "tags": tags,
        "thumb": thumb,
        "excerpt": excerpt,
        "desc": desc or excerpt,
        "content": content_html,
    }


def clean_content(el, valid_slugs):
    # Trabajamos sobre una copia
    el = BeautifulSoup(str(el), "html.parser").find()

    # Eliminar comentarios
    for c in el.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()

    # Eliminar scripts, ins (adsense), estilos, noscript
    for tag in el.find_all(["script", "ins", "style", "noscript"]):
        tag.decompose()

    # Eliminar bloques sociales / relacionados / contenedores de anuncios
    for sel in [".addtoany_share_save_container", ".yarpp-related",
                ".sharedaddy", ".jp-relatedposts", ".a2a_kit"]:
        for tag in el.select(sel):
            tag.decompose()

    # Eliminar divs vacíos de "clear" y wrappers de adsense ya vacíos
    for div in el.find_all("div"):
        sty = div.get("style", "")
        if "clear:both" in sty.replace(" ", ""):
            div.decompose()

    # Procesar imágenes
    for img in el.find_all("img"):
        src = img.get("src", "")
        rel = upload_rel(src)
        for attr in ("srcset", "width", "height", "style", "sizes",
                     "class", "title", "loading", "decoding", "data-src"):
            if img.has_attr(attr):
                del img[attr]
        if rel:
            img["src"] = "/assets/uploads/" + rel
            img["loading"] = "lazy"
            # fallback a Wayback si la imagen no se descargó
            img["onerror"] = ("this.onerror=null;this.src='%s'" % src.replace("'", "%27"))
        else:
            img["src"] = strip_wayback(src)
            img["loading"] = "lazy"
        if not img.get("alt"):
            img["alt"] = ""

    # Procesar iframes (vídeos / embeds)
    for ifr in el.find_all("iframe"):
        ifr["src"] = strip_wayback(ifr.get("src", ""))
        for attr in ("style", "width", "height"):
            if ifr.has_attr(attr):
                del ifr[attr]
        ifr["loading"] = "lazy"
        wrapper = el.new_tag("div")
        wrapper["class"] = "embed"
        ifr.insert_before(wrapper)
        wrapper.append(ifr.extract())

    # Procesar enlaces
    for a in el.find_all("a"):
        href = a.get("href", "")
        if not href:
            continue
        seg = slugify_segment(href)
        rel_up = upload_rel(href) if "diasextranos.com" in strip_wayback(href) else None
        if seg and seg in valid_slugs:
            a["href"] = "/" + seg + "/"
            for attr in ("target", "rel", "title"):
                if a.has_attr(attr):
                    del a[attr]
        elif rel_up:
            a["href"] = "/assets/uploads/" + rel_up
            for attr in ("target", "rel", "title"):
                if a.has_attr(attr):
                    del a[attr]
        else:
            o = strip_wayback(href)
            a["href"] = o
            if o.startswith("http"):
                a["target"] = "_blank"
                a["rel"] = "noopener noreferrer"

    # Convertir wp-caption a figure
    for cap in el.select(".wp-caption"):
        if cap.has_attr("style"):
            del cap["style"]
        cap.name = "figure"
        cap["class"] = ["figure"]
        txt = cap.select_one(".wp-caption-text")
        if txt:
            txt.name = "figcaption"
            txt["class"] = ["figcaption"]

    # Limpiar atributos style residuales que rompen layout (en divs/figuras)
    for tag in el.find_all(["div", "figure", "span"]):
        if tag.has_attr("style"):
            del tag["style"]

    # Eliminar bloques vacíos (divs/p sin texto ni media)
    for _ in range(3):
        for tag in el.find_all(["div", "p", "span"]):
            if tag.find(["img", "iframe", "figure", "ul", "ol", "blockquote", "table"]):
                continue
            if tag.get_text(strip=True) == "":
                tag.decompose()

    # Excerpt: primer párrafo de texto real
    excerpt = ""
    for p in el.find_all("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 40:
            excerpt = t
            break
    if len(excerpt) > 200:
        excerpt = excerpt[:200].rsplit(" ", 1)[0] + "…"

    # El contenido interior del div (sin el div contenedor)
    inner = el.decode_contents().strip()
    return inner, excerpt


# ---------------------------------------------------------------------------
# Plantillas HTML
# ---------------------------------------------------------------------------
def esc(s):
    return htmllib.escape(s or "", quote=True)


def nav_html(active=""):
    links = []
    for slug in ACTIVE_CATS:
        cls = ' class="active"' if active == slug else ''
        links.append(f'<a href="/categoria/{slug}/"{cls}>{esc(CAT_NAMES[slug])}</a>')
    return "\n        ".join(links)


def page_shell(title, body, description="", canonical="", active="",
               og_image="", extra_head="", body_class=""):
    desc = esc(description or SITE_DESC)
    canon = canonical or SITE_URL
    ogimg = og_image or ""
    og_tag = f'<meta property="og:image" content="{esc(ogimg)}"/>' if ogimg else ""
    bc = f' class="{body_class}"' if body_class else ""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{esc(title)}</title>
<meta name="description" content="{desc}"/>
<link rel="canonical" href="{esc(canon)}"/>
<meta property="og:site_name" content="{esc(SITE_NAME)}"/>
<meta property="og:title" content="{esc(title)}"/>
<meta property="og:description" content="{desc}"/>
<meta property="og:url" content="{esc(canon)}"/>
<meta property="og:type" content="website"/>
{og_tag}
<meta name="theme-color" content="#111418"/>
<link rel="preconnect" href="https://web.archive.org"/>
<link rel="stylesheet" href="/assets/css/style.css"/>
<link rel="alternate" type="application/json" href="/posts.json"/>
{extra_head}
</head>
<body{bc}>
<a class="skip" href="#main">Saltar al contenido</a>
<header class="site-header">
  <div class="wrap header-inner">
    <div class="brand">
      <a href="/" class="brand-link">
        <span class="brand-title">{esc(SITE_NAME)}</span>
        <span class="brand-sub">{esc(SITE_DESC)}</span>
      </a>
    </div>
    <button class="nav-toggle" aria-label="Abrir menú" aria-expanded="false">
      <span></span><span></span><span></span>
    </button>
    <nav class="site-nav" aria-label="Secciones">
        {nav_html(active)}
    </nav>
  </div>
</header>
<main id="main" class="wrap">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p class="foot-brand">{esc(SITE_NAME)} · <span>{esc(SITE_DESC)}</span></p>
    <p class="foot-social">
      <a href="https://twitter.com/lennynero1976" target="_blank" rel="noopener">Twitter</a>
      <a href="https://www.instagram.com/lennynero_jpv/" target="_blank" rel="noopener">Instagram</a>
      <a href="https://www.youtube.com/user/lennynero1976" target="_blank" rel="noopener">YouTube</a>
    </p>
    <p class="foot-note">Archivo recuperado del blog original (2007–2018). Reconstruido como sitio estático.</p>
  </div>
</footer>
<script src="/assets/js/main.js" defer></script>
</body>
</html>
"""


def cat_chip(slug):
    return f'<a class="chip" href="/categoria/{slug}/">{esc(CAT_NAMES.get(slug, slug))}</a>'


def post_card(p):
    cats = " ".join(cat_chip(c) for c in p["cats"])
    thumb = ""
    if p["thumb"]:
        rel = upload_rel(p["thumb"])
        if rel:
            local = "/assets/uploads/" + rel
            fb = p["thumb"].replace("'", "%27")
            thumb = (f'<a class="card-media" href="/{p["slug"]}/">'
                     f'<img loading="lazy" alt="" src="{esc(local)}" '
                     f'onerror="this.onerror=null;this.src=\'{esc(fb)}\'"/></a>')
        else:
            thumb = (f'<a class="card-media" href="/{p["slug"]}/">'
                     f'<img loading="lazy" alt="" src="{esc(strip_wayback(p["thumb"]))}"/></a>')
    data = esc((p["title"] + " " + " ".join(CAT_NAMES.get(c, c) for c in p["cats"]) + " " + " ".join(p["tags"])).lower())
    return f"""<article class="card" data-search="{data}" data-cats="{esc(' '.join(p['cats']))}">
  {thumb}
  <div class="card-body">
    <div class="card-cats">{cats}</div>
    <h2 class="card-title"><a href="/{p['slug']}/">{esc(p['title'])}</a></h2>
    <time class="card-date" datetime="{p['iso']}">{esc(p['date_pretty'])}</time>
    <p class="card-excerpt">{esc(p['excerpt'])}</p>
  </div>
</article>"""


def render_post(p, valid):
    cats = " ".join(cat_chip(c) for c in p["cats"])
    tags = ""
    if p["tags"]:
        tags = ('<div class="post-tags"><span>Etiquetas:</span> '
                + ", ".join(esc(t) for t in p["tags"]) + "</div>")
    canon = f"{SITE_URL}/{p['slug']}/"
    body = f"""<article class="post">
  <header class="post-header">
    <div class="post-cats">{cats}</div>
    <h1 class="post-title">{esc(p['title'])}</h1>
    <div class="post-meta">
      <span class="post-author">{esc(AUTHOR)}</span>
      <span class="sep">·</span>
      <time datetime="{p['iso']}">{esc(p['date_pretty'])}</time>
    </div>
  </header>
  <div class="post-content">
{p['content']}
  </div>
  {tags}
  <nav class="post-foot-nav"><a href="/" class="back">← Volver al inicio</a></nav>
</article>"""
    return page_shell(f"{p['title']} · {SITE_NAME}", body,
                      description=p["desc"], canonical=canon,
                      active=p["cats"][0] if p["cats"] else "",
                      og_image=p["thumb"] or "")


def render_home(posts):
    chips = '<button class="filter active" data-cat="">Todo</button>' + "".join(
        f'<button class="filter" data-cat="{c}">{esc(CAT_NAMES[c])}</button>' for c in ACTIVE_CATS)
    cards = "\n".join(post_card(p) for p in posts)
    body = f"""<section class="hero">
  <h1 class="hero-title">{esc(SITE_NAME)}</h1>
  <p class="hero-sub">{esc(SITE_DESC)} — música, conciertos, cine y cultura.</p>
  <div class="search-wrap">
    <input type="search" id="search" placeholder="Buscar entre {len(posts)} entradas…" aria-label="Buscar"/>
  </div>
  <div class="filters">{chips}</div>
</section>
<p class="result-count" id="result-count"></p>
<section class="cards" id="cards">
{cards}
</section>
<p class="no-results" id="no-results" hidden>No se encontraron entradas.</p>"""
    return page_shell(f"{SITE_NAME} · {SITE_DESC}", body,
                      description=f"{SITE_DESC}. Archivo del blog de música, conciertos y cultura diasextranos.com.",
                      canonical=SITE_URL)


def render_category(slug, posts):
    cards = "\n".join(post_card(p) for p in posts)
    name = CAT_NAMES[slug]
    body = f"""<section class="page-head">
  <p class="crumb"><a href="/">Inicio</a> / Categoría</p>
  <h1 class="page-title">{esc(name)}</h1>
  <p class="page-sub">{len(posts)} {'entrada' if len(posts)==1 else 'entradas'}</p>
</section>
<section class="cards">
{cards}
</section>"""
    return page_shell(f"{name} · {SITE_NAME}", body,
                      description=f"Entradas de la categoría {name} en {SITE_NAME}.",
                      canonical=f"{SITE_URL}/categoria/{slug}/", active=slug)


def render_archive(posts):
    by_year = {}
    for p in posts:
        by_year.setdefault(p["year"], []).append(p)
    blocks = []
    for year in sorted(by_year, reverse=True):
        items = "\n".join(
            f'<li><time datetime="{p["iso"]}">{p["dt"].day:02d}/{p["dt"].month:02d}</time>'
            f'<a href="/{p["slug"]}/">{esc(p["title"])}</a></li>'
            for p in by_year[year])
        blocks.append(f'<section class="year-block"><h2 class="year">{year}</h2><ul class="arch-list">{items}</ul></section>')
    body = f"""<section class="page-head">
  <p class="crumb"><a href="/">Inicio</a> / Archivo</p>
  <h1 class="page-title">Archivo</h1>
  <p class="page-sub">{len(posts)} entradas desde {min(p['year'] for p in posts)} a {max(p['year'] for p in posts)}</p>
</section>
{''.join(blocks)}"""
    return page_shell(f"Archivo · {SITE_NAME}", body,
                      description="Todas las entradas de Días Extraños ordenadas por año.",
                      canonical=f"{SITE_URL}/archivo/")


def render_404():
    body = """<section class="page-head center">
  <h1 class="page-title big">404</h1>
  <p class="page-sub">No encontramos esta página.</p>
  <p><a class="btn" href="/">Volver al inicio</a></p>
</section>"""
    return page_shell(f"404 · {SITE_NAME}", body, canonical=f"{SITE_URL}/404")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def write_page(relpath, content):
    full = os.path.join(OUT, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.html")))
    valid_slugs = {os.path.basename(f)[:-5] for f in files}

    posts = [parse_post(f, valid_slugs) for f in files]
    posts.sort(key=lambda p: p["dt"], reverse=True)

    global ACTIVE_CATS
    ACTIVE_CATS = [c for c in CAT_ORDER if any(c in p["cats"] for p in posts)]

    # Posts individuales
    for p in posts:
        write_page(f"{p['slug']}/index.html", render_post(p, valid_slugs))

    # Home
    write_page("index.html", render_home(posts))

    # Categorías
    for slug in CAT_ORDER:
        cp = [p for p in posts if slug in p["cats"]]
        if cp:
            write_page(f"categoria/{slug}/index.html", render_category(slug, cp))

    # Archivo
    write_page("archivo/index.html", render_archive(posts))

    # 404
    write_page("404.html", render_404())

    # posts.json (para búsqueda / referencia)
    index = [{
        "slug": p["slug"], "title": p["title"], "date": p["iso"],
        "cats": p["cats"], "excerpt": p["excerpt"], "url": f"/{p['slug']}/",
    } for p in posts]
    write_page("posts.json", json.dumps(index, ensure_ascii=False, indent=0))

    # Copiar las imágenes disponibles localmente
    copied = 0
    if os.path.isdir(UPLOADS_LOCAL):
        for root, _, fnames in os.walk(UPLOADS_LOCAL):
            for fn in fnames:
                srcf = os.path.join(root, fn)
                rel = os.path.relpath(srcf, UPLOADS_LOCAL)
                dstf = os.path.join(ASSETS_UP, rel)
                os.makedirs(os.path.dirname(dstf), exist_ok=True)
                shutil.copy2(srcf, dstf)
                copied += 1

    # Volcar lista de URLs de imágenes para el descargador
    img_urls = {}
    for f in files:
        soup = BeautifulSoup(read(f), "html.parser")
        ce = soup.select_one("div.entry-content, div.postentry")
        targets = []
        if ce:
            targets += ce.find_all("img")
        og = soup.find("meta", attrs={"property": "og:image"})
        for img in targets:
            src = img.get("src", "")
            rel = upload_rel(src)
            if rel and src.startswith("http"):
                img_urls.setdefault(rel, src)
        if og and og.get("content"):
            rel = upload_rel(og["content"])
            if rel and og["content"].startswith("http"):
                img_urls.setdefault(rel, og["content"])
    with open(os.path.join(OUT, "_build", "image_urls.json"), "w", encoding="utf-8") as fh:
        json.dump(img_urls, fh, ensure_ascii=False, indent=0)

    print(f"Posts: {len(posts)}")
    print(f"Categorías generadas: {sum(1 for s in CAT_ORDER if any(s in p['cats'] for p in posts))}")
    print(f"Imágenes locales copiadas: {copied}")
    print(f"URLs de imágenes a descargar: {len(img_urls)}")
    # pequeño resumen de fechas dudosas
    bad = [p['slug'] for p in posts if p['dt'].year == 2000]
    if bad:
        print("Posts sin fecha fiable:", bad)


if __name__ == "__main__":
    main()
