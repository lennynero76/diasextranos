# Días Extraños

Sitio estático que reemplaza el antiguo blog de WordPress **diasextranos.com**
(*Los Diarios de Lenny Nero*) — música, conciertos, cine y cultura.

El contenido (142 entradas, 2007–2018) se recuperó del archivo del blog y de la
Wayback Machine, y se reconstruyó como un sitio estático ligero en **HTML/CSS/JS
vanilla**, sin frameworks ni dependencias de build.

El diseño replica el tema **F2** de WordPress que usaba el blog original: misma
estructura DOM (`#page` › `#masthead` › `#main` › `#primary`/`#content` +
`#secondary`/`#sidebar-1` › `#colophon`), mismos selectores (`.hentry`,
`.entry-content`, `.entry-meta`, `.widget`, …) y el `style.css` real del tema F2
v2.2.3 como base (`f2-original.css`), con un esquema de color azul, tipografías
*Bitter* (títulos) y *Gudea* (cuerpo), *Font Awesome 4.5.0* para los iconos y
maquetación de dos columnas (contenido + sidebar derecho de widgets).

Se replican como HTML estático los plugins que el blog usaba en 2019: los botones
de compartir de **AddToAny** (`.addtoany_share_save_container`) y las entradas
relacionadas de **YARPP** (`.yarpp-related`) al pie de cada entrada, además del
widget de enlaces sociales (*Social Links Sidebar*) en el lateral.

## Estructura

```
/                       index.html        → portada: listado de entradas (.hentry)
/<slug>/                index.html        → cada entrada (artículo + comentarios meta)
/categoria/<slug>/      index.html        → archivo por categoría
/archivo/               index.html        → todas las entradas por año
/404.html                                 → página de error
/posts.json                               → índice de entradas (búsqueda / feeds)
/assets/css/f2-original.css               → style.css real del tema F2 v2.2.3 (base)
/assets/css/f2-adaptacion.css             → adaptaciones + plugins (AddToAny, YARPP)
/assets/css/f2-print.css                  → print.css del tema F2
/assets/themes/f2/images/                 → imágenes del tema F2 (noise.png)
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
