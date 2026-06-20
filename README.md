# Días Extraños

Sitio estático que reemplaza el antiguo blog de WordPress **diasextranos.com**
(*Los Diarios de Lenny Nero*) — música, conciertos, cine y cultura.

El contenido (142 entradas, 2007–2018) se recuperó del archivo del blog y de la
Wayback Machine, y se reconstruyó como un sitio estático ligero en **HTML/CSS/JS
vanilla**, sin frameworks ni dependencias de build.

El diseño replica el tema **F2** de WordPress que usaba el blog original: misma
estructura DOM (`#page` › `#masthead` › `#main` › `#primary`/`#content` +
`#secondary`/`#sidebar-1` › `#colophon`), mismos selectores (`.hentry`,
`.entry-content`, `.entry-meta`, `.widget`, …) y el `style.css` del propio tema F2
como base, con un esquema de color azul, tipografías *Bitter* (títulos) y *Gudea*
(cuerpo) y maquetación de dos columnas (contenido + sidebar derecho de widgets).

## Estructura

```
/                       index.html        → portada: listado de entradas (.hentry)
/<slug>/                index.html        → cada entrada (artículo + comentarios meta)
/categoria/<slug>/      index.html        → archivo por categoría
/archivo/               index.html        → todas las entradas por año
/404.html                                 → página de error
/posts.json                               → índice de entradas (búsqueda / feeds)
/assets/css/style.css                     → tema F2 (base) + adaptaciones del sitio
/assets/js/main.js                        → menú responsive + buscador en cliente
/assets/uploads/                          → imágenes de los posts
/_build/                                  → scripts de generación (no se sirven)
```

## Regenerar el sitio

Los scripts del generador viven en `_build/` y solo necesitan Python 3 + BeautifulSoup4.

```bash
pip install beautifulsoup4
python3 _build/build.py            # genera todas las páginas y posts.json
python3 _build/download_images.py  # descarga (best-effort) imágenes desde Wayback
```

`build.py` parsea los HTML originales (dos temas distintos de WordPress),
limpia el contenido (anuncios, widgets sociales, restos de Wayback), reescribe
enlaces internos y embeds (YouTube, etc.) y emite el sitio estático.

Las imágenes que no se hayan podido descargar se cargan en tiempo de ejecución
desde la Wayback Machine mediante un fallback `onerror` en cada `<img>`.

## Despliegue en Vercel

El repositorio es un sitio estático puro. En Vercel:

- **Framework Preset:** Other
- **Build Command:** *(ninguno)*
- **Output Directory:** `.` (raíz del repositorio)

`vercel.json` activa `cleanUrls` y `trailingSlash` y cachea los assets.
