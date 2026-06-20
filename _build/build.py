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
# Se rellenan en main() para los widgets del sidebar
TOTAL_POSTS = 0
ARCHIVE_YEARS = []

# Enlaces sociales (widget "Encuéntrame", como en el original)
SOCIAL_LINKS = [
    ("https://twitter.com/lennynero1976", "Twitter"),
    ("https://www.instagram.com/lennynero_jpv/", "Instagram"),
    ("https://www.youtube.com/user/lennynero1976", "YouTube"),
]

# Fuentes del tema F2 (las mismas que cargaba el blog en 2019: Bitter:700 + Gudea)
FONTS_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com"/>'
              '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>'
              '<link href="https://fonts.googleapis.com/css?family=Bitter:700|'
              'Gudea:400,700,400italic&amp;display=swap" rel="stylesheet"/>')

# Font Awesome 4.5.0 desde CDN (iconos de los botones de compartir, como en 2019)
FONTAWESOME_LINK = ('<link rel="stylesheet" '
                    'href="https://maxcdn.bootstrapcdn.com/font-awesome/4.5.0/css/font-awesome.min.css"/>')

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


def menu_html(active=""):
    """Menú horizontal principal del tema F2 (Inicio + categorías + Archivo)."""
    items = ['<li class="menu-item"><a href="/">Inicio</a></li>']
    for slug in ACTIVE_CATS:
        cls = ' class="menu-item current-menu-item"' if active == slug else ' class="menu-item"'
        items.append(f'<li{cls}><a href="/categoria/{slug}/">{esc(CAT_NAMES[slug])}</a></li>')
    ac = ' current-menu-item' if active == "archivo" else ''
    items.append(f'<li class="menu-item{ac}"><a href="/archivo/">Archivo</a></li>')
    return "\n          ".join(items)


def sidebar_html(active=""):
    """Área de widgets del sidebar derecho, replicando los del original."""
    # Widget: Buscar
    search = f"""<aside id="search-1" class="widget widget_search">
        <h2 class="widget-title">Buscar</h2>
        <form role="search" class="search-form" onsubmit="return false;">
          <label><span class="screen-reader-text">Buscar:</span>
          <input type="search" id="search" class="search-field" placeholder="Buscar entre {TOTAL_POSTS} entradas…" aria-label="Buscar"/></label>
        </form>
        <p class="search-feedback" id="result-count"></p>
      </aside>"""
    # Widget: Secciones (categorías)
    cat_items = "\n        ".join(
        f'<li class="cat-item{" current-cat" if active==c else ""}">'
        f'<a href="/categoria/{c}/">{esc(CAT_NAMES[c])}</a></li>'
        for c in ACTIVE_CATS)
    cats = f"""<aside id="categories-3" class="widget widget_categories">
        <h2 class="widget-title">Secciones</h2>
        <ul>
        {cat_items}
        </ul>
      </aside>"""
    # Widget: Archivo (por años)
    year_items = "\n        ".join(
        f'<li><a href="/archivo/#{y}">{y}</a></li>' for y in ARCHIVE_YEARS)
    arch = f"""<aside id="archives-3" class="widget widget_archive">
        <h2 class="widget-title">Archivo</h2>
        <ul>
        <li><a href="/archivo/">Todas las entradas</a></li>
        {year_items}
        </ul>
      </aside>"""
    # Widget: Encuéntrame (enlaces sociales)
    soc_items = "\n        ".join(
        f'<li><a href="{esc(url)}" target="_blank" rel="me noopener">{esc(name)}</a></li>'
        for url, name in SOCIAL_LINKS)
    social = f"""<aside id="social-1" class="widget widget_links">
        <h2 class="widget-title">Encuéntrame</h2>
        <ul class="xoxo blogroll">
        {soc_items}
        </ul>
      </aside>"""
    return "\n      ".join([search, cats, arch, social])


def page_shell(title, body, description="", canonical="", active="",
               og_image="", extra_head="", body_class="one-sidebar-right medium-sidebar"):
    desc = esc(description or SITE_DESC)
    canon = canonical or SITE_URL
    ogimg = og_image or ""
    og_tag = f'<meta property="og:image" content="{esc(ogimg)}"/>' if ogimg else ""
    bc = f' class="{esc(body_class)}"' if body_class else ""
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
<meta name="theme-color" content="#6d97b7"/>
<link rel="preconnect" href="https://web.archive.org"/>
{FONTS_LINK}
{FONTAWESOME_LINK}
<link rel="stylesheet" href="/assets/css/f2-original.css"/>
<link rel="stylesheet" href="/assets/css/f2-adaptacion.css"/>
<link rel="stylesheet" media="print" href="/assets/css/f2-print.css"/>
<link rel="alternate" type="application/json" href="/posts.json"/>
{extra_head}
</head>
<body{bc}>
<div id="page" class="hfeed site">
  <a class="skip-link screen-reader-text" href="#content">Saltar al contenido</a>

  <header id="masthead" class="site-header" role="banner">
    <div class="site-branding">
      <h1 class="site-title"><a href="/" title="{esc(SITE_NAME)}" rel="home">{esc(SITE_NAME)}</a></h1>
      <h2 class="site-description">{esc(SITE_DESC)}</h2>
    </div><!-- .site-branding -->

    <nav id="site-navigation" class="site-navigation main-navigation" role="navigation">
      <button class="menu-toggle" aria-controls="primary-menu" aria-expanded="false">Menú</button>
      <div class="menu">
        <ul>
          {menu_html(active)}
        </ul>
      </div>
    </nav><!-- #site-navigation -->
  </header><!-- #masthead .site-header -->

  <div id="main" class="site-main">
    <div id="primary" class="content-area">
      <div id="content" class="site-content" role="main">
{body}
      </div><!-- #content .site-content -->
    </div><!-- #primary .content-area -->

    <div id="secondary" class="widget-area" role="complementary">
      <div id="sidebar-1" class="sidebar">
      {sidebar_html(active)}
      </div><!-- #sidebar-1 .sidebar -->
    </div><!-- #secondary .widget-area -->
  </div><!-- #main .site-main -->

  <footer id="colophon" class="site-footer" role="contentinfo">
    <div class="site-info">
      <div>&copy; {SITE_NAME} · {esc(SITE_DESC)}</div>
    </div>
    <div class="f2-credits">
      Archivo recuperado del blog original (2007–2018), reconstruido como sitio estático.
    </div><!-- .f2-credits -->
  </footer><!-- #colophon .site-footer -->
</div><!-- #page .site -->
<script src="/assets/js/main.js" defer></script>
</body>
</html>
"""


def cat_links(cats):
    return ", ".join(
        f'<a href="/categoria/{c}/" rel="category tag">{esc(CAT_NAMES.get(c, c))}</a>'
        for c in cats)


def featured_image(p, link=True):
    """Imagen destacada (.wp-post-image) con fallback a Wayback."""
    if not p["thumb"]:
        return ""
    rel = upload_rel(p["thumb"])
    if rel:
        local = "/assets/uploads/" + rel
        fb = p["thumb"].replace("'", "%27")
        img = (f'<img class="wp-post-image" loading="lazy" alt="{esc(p["title"])}" '
               f'src="{esc(local)}" onerror="this.onerror=null;this.src=\'{esc(fb)}\'"/>')
    else:
        img = (f'<img class="wp-post-image" loading="lazy" alt="{esc(p["title"])}" '
               f'src="{esc(strip_wayback(p["thumb"]))}"/>')
    if link:
        return f'<a class="featured-image" href="/{p["slug"]}/" aria-hidden="true" tabindex="-1">{img}</a>'
    return f'<div class="featured-image">{img}</div>'


def entry_summary(p):
    """Resumen de entrada para los listados (home y categorías), estilo F2."""
    data = esc((p["title"] + " " + " ".join(CAT_NAMES.get(c, c) for c in p["cats"])
                + " " + " ".join(p["tags"])).lower())
    classes = "post hentry format-standard " + " ".join("category-" + c for c in p["cats"])
    return f"""<article class="{classes}" data-search="{data}" data-cats="{esc(' '.join(p['cats']))}">
  <header class="entry-header">
    <h1 class="entry-title"><a href="/{p['slug']}/" rel="bookmark">{esc(p['title'])}</a></h1>
    <div class="entry-meta">
      Publicado por <span class="author vcard">{esc(AUTHOR)}</span> el
      <time class="entry-date" datetime="{p['iso']}">{esc(p['date_pretty'])}</time>
      <span class="sep"> · </span>
      <span class="cat-links">{cat_links(p['cats'])}</span>
    </div><!-- .entry-meta -->
  </header><!-- .entry-header -->
  {featured_image(p)}
  <div class="entry-summary">
    <p>{esc(p['excerpt'])}</p>
    <p><a class="more-link" href="/{p['slug']}/">Leer más &rarr;</a></p>
  </div><!-- .entry-summary -->
</article>"""


def share_buttons(p):
    """Botones de compartir, réplica HTML estática del plugin AddToAny (2019)."""
    import urllib.parse as up
    url = f"{SITE_URL}/{p['slug']}/"
    title = p["title"]
    u = up.quote(url, safe="")
    t = up.quote(title, safe="")
    tu = up.quote(f"{title} {url}", safe="")
    services = [
        ("facebook", "fa-facebook", "Compartir en Facebook",
         f"https://www.facebook.com/sharer/sharer.php?u={u}"),
        ("twitter", "fa-twitter", "Compartir en Twitter",
         f"https://twitter.com/intent/tweet?url={u}&text={t}"),
        ("whatsapp", "fa-whatsapp", "Compartir en WhatsApp",
         f"https://api.whatsapp.com/send?text={tu}"),
        ("telegram", "fa-paper-plane", "Compartir en Telegram",
         f"https://t.me/share/url?url={u}&text={t}"),
        ("email", "fa-envelope", "Compartir por correo",
         f"mailto:?subject={t}&body={tu}"),
    ]
    items = "\n        ".join(
        f'<li><a class="a2a_button a2a_button_{svc}" href="{esc(href)}" '
        f'target="_blank" rel="noopener nofollow" title="{esc(label)}" '
        f'aria-label="{esc(label)}"><i class="fa {icon}" aria-hidden="true"></i>'
        f'<span class="screen-reader-text">{esc(label)}</span></a></li>'
        for svc, icon, label, href in services)
    return f"""<div class="addtoany_share_save_container">
      <p class="a2a_label">Compartir</p>
      <ul class="a2a_kit a2a_kit_size_32 a2a_default_style">
        {items}
      </ul>
    </div><!-- .addtoany_share_save_container -->"""


def compute_related(posts, limit=4):
    """Asigna a cada post sus entradas relacionadas (estilo YARPP).

    Puntuación: etiquetas compartidas (×3) + categorías compartidas (×2);
    se desempata por proximidad de fecha. Si no hay coincidencias suficientes,
    se completa con las entradas más cercanas en el tiempo de la misma categoría.
    """
    for p in posts:
        ptags, pcats = set(p["tags"]), set(p["cats"])
        scored = []
        for q in posts:
            if q is p:
                continue
            score = 3 * len(ptags & set(q["tags"])) + 2 * len(pcats & set(q["cats"]))
            if score > 0:
                gap = abs((p["dt"] - q["dt"]).days)
                scored.append((-score, gap, q))
        scored.sort(key=lambda x: (x[0], x[1]))
        related = [q for _, _, q in scored[:limit]]
        # Completar con vecinos por fecha si faltan
        if len(related) < limit:
            chosen = set(id(x) for x in related) | {id(p)}
            rest = sorted((q for q in posts if id(q) not in chosen),
                          key=lambda q: abs((p["dt"] - q["dt"]).days))
            related += rest[:limit - len(related)]
        p["related"] = related


def related_thumb(q):
    """Miniatura de una entrada relacionada (o placeholder con icono)."""
    if q.get("thumb"):
        rel = upload_rel(q["thumb"])
        if rel:
            local = "/assets/uploads/" + rel
            fb = q["thumb"].replace("'", "%27")
            return (f'<img loading="lazy" alt="{esc(q["title"])}" src="{esc(local)}" '
                    f'onerror="this.onerror=null;this.src=\'{esc(fb)}\'"/>')
        return (f'<img loading="lazy" alt="{esc(q["title"])}" '
                f'src="{esc(strip_wayback(q["thumb"]))}"/>')
    return ('<span class="yarpp-thumb-placeholder">'
            '<i class="fa fa-music" aria-hidden="true"></i></span>')


def related_html(p):
    """Bloque de entradas relacionadas, réplica del plugin YARPP (2019)."""
    rel = p.get("related") or []
    if not rel:
        return ""
    items = "\n      ".join(
        f'<li>'
        f'<a class="yarpp-thumb" href="/{q["slug"]}/">{related_thumb(q)}</a>'
        f'<a class="yarpp-title" href="/{q["slug"]}/">{esc(q["title"])}</a>'
        f'<span class="yarpp-date">{esc(q["date_pretty"])}</span>'
        f'</li>'
        for q in rel)
    return f"""<div class="yarpp-related">
    <h3>Entradas relacionadas</h3>
    <ul class="yarpp-related-list">
      {items}
    </ul>
  </div><!-- .yarpp-related -->"""


def render_post(p, prev=None, nxt=None):
    cat = f'<span class="cat-links">Publicado en&nbsp;{cat_links(p["cats"])}</span>'
    tags = ""
    if p["tags"]:
        tags = ('<span class="sep"> | </span><span class="tag-links">Etiquetado&nbsp;'
                + ", ".join(esc(t) for t in p["tags"]) + "</span>")
    nav_prev = (f'<div class="nav-previous"><a href="/{prev["slug"]}/" rel="prev">'
                f'&laquo; {esc(prev["title"])}</a></div>') if prev else ''
    nav_next = (f'<div class="nav-next"><a href="/{nxt["slug"]}/" rel="next">'
                f'{esc(nxt["title"])} &raquo;</a></div>') if nxt else ''
    canon = f"{SITE_URL}/{p['slug']}/"
    body = f"""<article id="post-{p['slug']}" class="post hentry format-standard">
  <header class="entry-header">
    <h1 class="entry-title">{esc(p['title'])}</h1>
    <div class="entry-meta">
      Publicado por <span class="author vcard">{esc(AUTHOR)}</span> el
      <time class="entry-date" datetime="{p['iso']}">{esc(p['date_pretty'])}</time>
    </div><!-- .entry-meta -->
  </header><!-- .entry-header -->

  <div class="entry-content">
{p['content']}
  </div><!-- .entry-content -->

  <footer class="entry-meta">
    {cat}
    {tags}
    {share_buttons(p)}
  </footer><!-- .entry-meta -->
</article>

{related_html(p)}

<nav class="site-navigation post-navigation" role="navigation">
  {nav_prev}
  {nav_next}
</nav>"""
    return page_shell(f"{p['title']} · {SITE_NAME}", body,
                      description=p["desc"], canonical=canon,
                      active=p["cats"][0] if p["cats"] else "",
                      og_image=p["thumb"] or "",
                      body_class="single single-post one-sidebar-right medium-sidebar")


def render_home(posts):
    entries = "\n".join(entry_summary(p) for p in posts)
    body = f"""<header class="page-header">
  <h1 class="page-title">Entradas recientes</h1>
  <span>{len(posts)} entradas · usa el buscador del lateral para filtrar</span>
</header>
<div id="entries">
{entries}
</div>
<p class="no-results" id="no-results" hidden>No se encontraron entradas.</p>"""
    return page_shell(f"{SITE_NAME} · {SITE_DESC}", body,
                      description=f"{SITE_DESC}. Archivo del blog de música, conciertos y cultura diasextranos.com.",
                      canonical=SITE_URL,
                      body_class="home blog one-sidebar-right medium-sidebar")


def render_category(slug, posts):
    entries = "\n".join(entry_summary(p) for p in posts)
    name = CAT_NAMES[slug]
    body = f"""<header class="page-header">
  <h1 class="page-title">Archivo de la categoría: <span>{esc(name)}</span></h1>
  <span>{len(posts)} {'entrada' if len(posts)==1 else 'entradas'}</span>
</header>
<div id="entries">
{entries}
</div>
<p class="no-results" id="no-results" hidden>No se encontraron entradas.</p>"""
    return page_shell(f"{name} · {SITE_NAME}", body,
                      description=f"Entradas de la categoría {name} en {SITE_NAME}.",
                      canonical=f"{SITE_URL}/categoria/{slug}/", active=slug,
                      body_class="archive category one-sidebar-right medium-sidebar")


def render_archive(posts):
    by_year = {}
    for p in posts:
        by_year.setdefault(p["year"], []).append(p)
    blocks = []
    for year in sorted(by_year, reverse=True):
        items = "\n".join(
            f'<li><time datetime="{p["iso"]}">{p["dt"].day:02d}/{p["dt"].month:02d}</time> '
            f'<a href="/{p["slug"]}/">{esc(p["title"])}</a></li>'
            for p in by_year[year])
        blocks.append(f'<section class="year-block" id="{year}">'
                      f'<h2 class="year">{year}</h2>'
                      f'<ul class="arch-list">{items}</ul></section>')
    body = f"""<header class="page-header">
  <h1 class="page-title">Archivo</h1>
  <span>{len(posts)} entradas desde {min(p['year'] for p in posts)} a {max(p['year'] for p in posts)}</span>
</header>
{''.join(blocks)}"""
    return page_shell(f"Archivo · {SITE_NAME}", body,
                      description="Todas las entradas de Días Extraños ordenadas por año.",
                      canonical=f"{SITE_URL}/archivo/", active="archivo",
                      body_class="archive one-sidebar-right medium-sidebar")


def render_404():
    body = """<header class="page-header">
  <h1 class="page-title">404 — No encontrado</h1>
  <span>No encontramos esta página.</span>
</header>
<p>La página que buscas no existe o se ha movido. <a href="/">Volver al inicio</a>.</p>
<p><a class="btn" href="/">Volver al inicio</a></p>"""
    return page_shell(f"404 · {SITE_NAME}", body, canonical=f"{SITE_URL}/404",
                      body_class="error404 one-sidebar-right medium-sidebar")


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

    global ACTIVE_CATS, TOTAL_POSTS, ARCHIVE_YEARS
    ACTIVE_CATS = [c for c in CAT_ORDER if any(c in p["cats"] for p in posts)]
    TOTAL_POSTS = len(posts)
    ARCHIVE_YEARS = sorted({p["year"] for p in posts}, reverse=True)

    # Entradas relacionadas (plugin YARPP) para cada post
    compute_related(posts)

    # Posts individuales (con navegación anterior/siguiente)
    # posts está ordenado de más reciente a más antiguo
    for i, p in enumerate(posts):
        nxt = posts[i - 1] if i > 0 else None              # entrada más reciente
        prev = posts[i + 1] if i + 1 < len(posts) else None  # entrada más antigua
        write_page(f"{p['slug']}/index.html", render_post(p, prev=prev, nxt=nxt))

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
