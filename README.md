# Días Extraños

Sitio estático que reemplaza el antiguo blog de WordPress **diasextranos.com**
(*Los Diarios de Lenny Nero*) — música, conciertos, cine y cultura.

El contenido (142 entradas, 2007–2018) se recuperó del archivo del blog y de la
Wayback Machine, y se reconstruyó como un sitio estático ligero en **HTML/CSS/JS
vanilla**, sin frameworks ni dependencias de build.

## Estructura

```
/                       index.html        → portada con buscador y filtros
/<slug>/                index.html        → cada entrada
/categoria/<slug>/      index.html        → listado por categoría
/archivo/               index.html        → todas las entradas por año
/404.html                                 → página de error
/posts.json                               → índice de entradas (búsqueda / feeds)
/assets/css/style.css                     → estilos (tema claro/oscuro automático)
/assets/js/main.js                        → menú móvil + buscador en cliente
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
