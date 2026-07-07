#!/usr/bin/env python3
"""
Converts 'Noam Leshem Press Kit.dc.html' (Design Component format) into a
single self-contained offline HTML file: 'Noam Leshem.html'

What gets inlined:
  - Google Fonts (woff2 → base64)
  - FontAwesome brands + solid (woff2 → base64, only needed CSS kept)
  - TopoJSON client library
  - world-atlas/countries-110m.json (map data)
  - All display images from uploads/web/ (base64)

What stays external (needs internet to show):
  - SoundCloud embeds (iframe)
  - Instagram embeds (iframe)
  - Hero video (stays relative path; put file next to .html when sharing)
"""

import re, base64, os, json, sys, shutil
from urllib.request import urlopen, Request
from urllib.error import URLError

BASE   = os.path.dirname(os.path.abspath(__file__))
SRC    = os.path.join(BASE, 'Noam Leshem Press Kit.dc.html')
OUT    = os.path.join(BASE, 'Noam Leshem.html')

# `--web` builds an external-asset site into dist/ for hosting (e.g. Vercel),
# where the video is a real file (range requests work → plays on iPhone).
# Without the flag, behaviour is unchanged: a single inlined offline HTML file.
WEB       = '--web' in sys.argv
DIST      = os.path.join(BASE, 'dist')
ASSETS    = os.path.join(DIST, 'assets')
DOWNLOADS = os.path.join(DIST, 'downloads')
UPLOADS   = os.path.join(BASE, 'uploads')
if WEB:
    OUT = os.path.join(DIST, 'index.html')

# Absolute site URL (e.g. 'https://noamleshem.com'). Leave '' to use relative
# paths; set it so social-share previews (WhatsApp/Twitter) get an absolute image.
SITE_URL  = ''
META_DESC = ('Noam Leshem — Tel Aviv-based DJ & producer. Psytrance, deep techno '
             '& electronic. Press kit: bio, music, shows, photos, tech rider & booking.')

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
      'AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0.0.0 Safari/537.36')

def fetch(url, binary=False):
    req = Request(url, headers={'User-Agent': UA})
    with urlopen(req, timeout=20) as r:
        return r.read() if binary else r.read().decode('utf-8')

def b64(data):
    return base64.b64encode(data).decode()

def font_face_css(url_to_b64, css_text):
    """Replace url(...woff2) with data URIs in a CSS string."""
    def replacer(m):
        url = m.group(1).strip("'\"")
        if url in url_to_b64:
            mime = 'font/woff2' if url.endswith('.woff2') else 'font/woff'
            return f'url(data:{mime};base64,{url_to_b64[url]})'
        return m.group(0)
    return re.sub(r'url\(([^)]+)\)', replacer, css_text)

# ── 1. Read source ────────────────────────────────────────────────────────────
print('Reading source…')
with open(SRC, encoding='utf-8') as f:
    src = f.read()

# ── 2. Google Fonts ───────────────────────────────────────────────────────────
print('Downloading Google Fonts…')
GF_URL = ('https://fonts.googleapis.com/css2?'
          'family=Unbounded:wght@500;700;800;900'
          '&family=Space+Grotesk:wght@400;500;600;700'
          '&display=swap')
gf_css = fetch(GF_URL)
font_urls = re.findall(r'url\((https://fonts\.gstatic\.com[^)]+)\)', gf_css)
gf_b64 = {}
for u in set(font_urls):
    print(f'  font: {u.split("/")[-1]}')
    gf_b64[u] = b64(fetch(u, binary=True))
gf_inline = font_face_css(gf_b64, gf_css)

# ── 3. FontAwesome (brands + solid only) ─────────────────────────────────────
print('Downloading FontAwesome…')
FA_BASE = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/'
fa_css  = fetch(FA_BASE + 'all.min.css')
# Collect woff2 font URLs
fa_font_urls = re.findall(r'url\((\.\.\/webfonts\/[^)]+\.woff2)\)', fa_css)
fa_b64 = {}
for rel in set(fa_font_urls):
    fname = rel.split('/')[-1]
    # only download brands and solid (the two we actually use)
    if 'brands' not in fname and 'solid' not in fname:
        continue
    full = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/webfonts/' + fname
    print(f'  fa: {fname}')
    fa_b64[rel] = b64(fetch(full, binary=True))

# Rewrite the font URLs that we downloaded; others stay as cdn urls (unused)
def fa_replacer(m):
    rel = m.group(1).strip("'\"")
    if rel in fa_b64:
        return f'url(data:font/woff2;base64,{fa_b64[rel]})'
    # For non-downloaded font formats (woff, ttf etc.) just keep original but
    # point to the CDN absolute URL so it resolves even if offline fails
    orig = rel.replace('../webfonts/', 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/webfonts/')
    return f'url({orig})'
fa_inline = re.sub(r'url\((\.\.\/webfonts\/[^)]+)\)', fa_replacer, fa_css)

# ── 4. TopoJSON library ───────────────────────────────────────────────────────
print('Downloading TopoJSON…')
topo_js = fetch('https://cdn.jsdelivr.net/npm/topojson-client@3/dist/topojson-client.min.js')

# ── 5. World atlas JSON ───────────────────────────────────────────────────────
print('Downloading world-atlas…')
atlas_json = fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json')

# ── 5b. Pre-render world map as static SVG (works in Quick Look / no-JS) ─────
print('Generating SVG world map…')

def _build_world_svg(atlas_json_str, W=800, H=400):
    import json as _j
    data = _j.loads(atlas_json_str)
    tr = data['transform']
    sc, tl = tr['scale'], tr['translate']
    arcs = data['arcs']
    LAT_MAX, LAT_MIN = 78, -56

    def decode_arc(idx):
        rev = idx < 0
        arc = arcs[~idx if rev else idx]
        x = y = 0
        pts = []
        for pt in arc:
            x += pt[0]; y += pt[1]
            pts.append((x * sc[0] + tl[0], y * sc[1] + tl[1]))
        return pts[::-1] if rev else pts

    def proj(lon, lat):
        return (lon + 180) / 360 * W, (LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * H

    def ring_d(ring_arcs):
        coords = []
        for i in ring_arcs: coords.extend(decode_arc(i))
        if not coords: return ''
        pts = [proj(lo, la) for lo, la in coords]
        return 'M' + 'L'.join(f'{x:.1f},{y:.1f}' for x, y in pts) + 'Z'

    def geo_d(geo):
        ds = []
        if geo['type'] == 'Polygon':
            for r in geo['arcs']: ds.append(ring_d(r))
        elif geo['type'] == 'MultiPolygon':
            for p in geo['arcs']:
                for r in p: ds.append(ring_d(r))
        return ' '.join(d for d in ds if d)

    # ISO numeric ids — must match data-country on .festival-row in the template
    highlighted = {376, 840, 356, 764, 300, 784, 620}
    normal, hl = [], []
    for geo in data['objects']['countries']['geometries']:
        gid = int(geo.get('id') or 0)
        d = geo_d(geo)
        if not d: continue
        (hl if gid in highlighted else normal).append((gid, d))

    # (label, lon, lat, label offset, ISO numeric country id)
    locs = [
        ('Tel Aviv',    34.78,  32.07, -10, 376),
        ('Hawaii',    -157.8,   21.3,  -10, 840),
        ('Los Angeles',-118.2,  34.05,  13, 840),
        ('Goa',         73.83,  15.5,  -10, 356),
        ('Thailand',   100.5,   13.75, -10, 764),
        ('Greece',      23.7,   37.98, -10, 300),
        ('Crete',       25.0,   35.3,   13, 300),
        ('Portugal',    -8.2,   39.4,  -10, 620),
        ('Dubai',       55.3,   25.2,  -10, 784),
    ]

    dots = []
    for label, lon, lat, dy, cid in locs:
        x, y = proj(lon, lat)
        dots.append(
            f'<g class="map-loc" data-country="{cid}">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="14" fill="rgba(255,30,140,0.08)"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="rgba(255,30,140,0.18)"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#FF1E8C"/>'
            f'<text x="{x:.1f}" y="{y+dy:.1f}" text-anchor="middle" '
            f'font-family="\'Space Grotesk\',sans-serif" font-size="9" '
            f'fill="rgba(244,242,248,0.75)">{label}</text>'
            f'</g>'
        )

    normal_svg = ''.join(f'<path class="map-country" data-country="{gid}" d="{d}" fill="#18152A" stroke="rgba(255,255,255,0.07)" stroke-width="0.3"/>' for gid, d in normal)
    hl_svg = ''.join(f'<path class="map-country" data-country="{gid}" d="{d}" fill="rgba(255,30,140,0.2)" stroke="rgba(255,30,140,0.5)" stroke-width="0.8"/>' for gid, d in hl)
    dots_svg = ''.join(dots)

    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:auto;display:block;">'
        f'<rect width="{W}" height="{H}" fill="#0C0A13"/>'
        f'{normal_svg}{hl_svg}{dots_svg}'
        f'</svg>'
    )

WORLD_SVG = _build_world_svg(atlas_json)
print(f'  SVG size: {len(WORLD_SVG)//1024}KB')

# ── 5c. Compress video path ───────────────────────────────────────────────────
VIDEO_PATH = os.path.join(BASE, '..', 'Noam Leshem press kit', 'uploads', 'NoamLeshem1_web.mp4')
VIDEO_PATH = os.path.normpath(VIDEO_PATH)

# ── 6. Base64-encode display images ──────────────────────────────────────────
# Inline the hero video as raw base64. It is decoded to a Blob URL at runtime
# (see the hero-video script below): data: URIs don't play in Safari/iOS WebKit,
# but blob: URLs do — and this keeps everything in a single offline file.
MOBILE_VIDEO_PATH = os.path.join(os.path.dirname(VIDEO_PATH), 'NoamLeshem1_mobile.mp4')
video_b64 = ''
have_mobile_video = False
if WEB:
    print('Copying video…')
    os.makedirs(DIST, exist_ok=True)
    if os.path.exists(VIDEO_PATH):
        shutil.copyfile(VIDEO_PATH, os.path.join(DIST, 'hero.mp4'))
        print(f'  hero.mp4 ({os.path.getsize(VIDEO_PATH)//1024}KB)')
    else:
        print('  video not found, skipping')
    if os.path.exists(MOBILE_VIDEO_PATH):
        shutil.copyfile(MOBILE_VIDEO_PATH, os.path.join(DIST, 'hero-mobile.mp4'))
        have_mobile_video = True
        print(f'  hero-mobile.mp4 ({os.path.getsize(MOBILE_VIDEO_PATH)//1024}KB)')
else:
    print('Encoding video…')
    if os.path.exists(VIDEO_PATH):
        with open(VIDEO_PATH, 'rb') as f:
            video_b64 = b64(f.read())
        print(f'  video: {os.path.getsize(VIDEO_PATH)//1024}KB')
    else:
        print('  video not found, skipping')

print('Copying images…' if WEB else 'Encoding images…')
WEB_DIR = os.path.join(BASE, 'uploads', 'web')
img_b64 = {}
web_imgs = set()
if WEB:
    os.makedirs(ASSETS, exist_ok=True)
for fname in os.listdir(WEB_DIR):
    ext = fname.rsplit('.', 1)[-1].lower()
    mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'png': 'image/png', 'webp': 'image/webp'}.get(ext)
    if not mime:
        continue
    path = os.path.join(WEB_DIR, fname)
    if WEB:
        shutil.copyfile(path, os.path.join(ASSETS, fname))
        web_imgs.add(fname.lower())
        print(f'  {fname}')
    else:
        with open(path, 'rb') as f:
            data = f.read()
        img_b64[fname.lower()] = f'data:{mime};base64,{b64(data)}'
        print(f'  {fname} ({len(data)//1024}KB)')

def img_data(fname):
    key = fname.lower()
    return img_b64.get(key, fname)

# ── 7. Extract template + CSS + JS from the .dc.html ─────────────────────────
print('Extracting template…')

# Extract content inside <x-dc>…</x-dc>
tpl_m = re.search(r'<x-dc[^>]*>(.*?)</x-dc>', src, re.S)
tpl_raw = tpl_m.group(1).strip()

# Extract <helmet> block and the rest of the body
helmet_m = re.search(r'<helmet[^>]*>(.*?)</helmet>', tpl_raw, re.S)
helmet_html = helmet_m.group(1).strip() if helmet_m else ''
# Body = everything after </helmet>
body_start = tpl_raw.find('</helmet>') + len('</helmet>')
body_html = tpl_raw[body_start:].strip()

# Extract inline <style> from helmet
style_m = re.search(r'<style>(.*?)</style>', helmet_html, re.S)
page_css = style_m.group(1) if style_m else ''

# Extract component script
script_m = re.search(r'<script[^>]+data-dc-script[^>]*>(.*?)</script>', src, re.S)
component_js_raw = script_m.group(1).strip() if script_m else ''

# ── 8. Remove ref="{{ rootRef }}" from the root div ───────────────────────────
body_html = re.sub(r'\s*ref="\{\{\s*rootRef\s*\}\}"', '', body_html)

# ── 9. Rewrite image src paths to base64, remove lazy loading ─────────────────
def rewrite_img_src(m):
    src_attr = m.group(0)
    fname_m = re.search(r'uploads/web/([^"\']+)', src_attr)
    if not fname_m:
        return src_attr
    fname = fname_m.group(1)
    key = fname.lower()
    if WEB:
        return src_attr.replace(f'uploads/web/{fname}', f'assets/{fname}')
    if key in img_b64:
        return src_attr.replace(f'uploads/web/{fname}', img_b64[key])
    return src_attr
body_html = re.sub(r'src="uploads/web/[^"]*"', rewrite_img_src, body_html)
if WEB:
    # Copy the full-res press photos referenced by the download buttons and
    # point the links at dist/downloads/ so they resolve on the live site.
    os.makedirs(DOWNLOADS, exist_ok=True)
    print('Copying download photos…')
    for name in sorted(set(re.findall(r'href="uploads/([^"/]+)"', body_html))):
        srcp = os.path.join(UPLOADS, name)
        if os.path.exists(srcp):
            shutil.copyfile(srcp, os.path.join(DOWNLOADS, name))
            print(f'  download: {name} ({os.path.getsize(srcp)//1024}KB)')
    body_html = re.sub(r'href="uploads/([^"/]+)"', r'href="downloads/\1"', body_html)
else:
    # Remove lazy loading — data URIs are already in memory, lazy just delays display
    body_html = body_html.replace(' loading="lazy"', '').replace(' decoding="async"', '')

# Replace <canvas id="worldMap"> with pre-rendered SVG — works in Quick Look, WKWebView, everywhere
body_html = re.sub(
    r'<canvas id="worldMap"[^>]*></canvas>',
    WORLD_SVG,
    body_html
)

# Replace <video> with embedded compressed video (or static poster if video not available)
poster_fname = 'IMG_9426.JPG'
poster_data = img_b64.get(poster_fname.lower(), '')
HERO_STYLE = 'position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center;opacity:.85;filter:saturate(.8) brightness(.9);'
if WEB:
    # External video; the <source> is added by the hero script (which also picks
    # the mobile variant). poster shows until it loads.
    poster_web = f'assets/{poster_fname}' if poster_fname.lower() in web_imgs else ''
    body_html = re.sub(
        r'<video[^>]*>.*?</video>',
        (
            f'<video id="heroVid" autoplay muted loop playsinline preload="metadata"'
            + (f' poster="{poster_web}"' if poster_web else '')
            + f' style="{HERO_STYLE}"></video>'
        ),
        body_html, flags=re.S
    )
elif video_b64:
    # No src= here on purpose: WebKit (Safari/iOS) can't play data: URIs.
    # The base64 sits in data-vsrc and is turned into a blob: URL by JS at load.
    # poster= shows meanwhile, and stays if JS is blocked (e.g. Quick Look).
    body_html = re.sub(
        r'<video[^>]*>.*?</video>',
        (
            f'<video id="heroVid" autoplay muted loop playsinline'
            + (f' poster="{poster_data}"' if poster_data else '')
            + f' style="{HERO_STYLE}" data-vsrc="{video_b64}"></video>'
        ),
        body_html, flags=re.S
    )
elif poster_data:
    body_html = re.sub(
        r'<video[^>]*>.*?</video>',
        f'<img src="{poster_data}" style="{HERO_STYLE}" alt="Noam Leshem">',
        body_html, flags=re.S
    )

# Replace SoundCloud iframes with offline-safe cards that include the embedded thumbnail
from urllib.parse import unquote, urlencode

def fetch_sc_thumbnail(track_url):
    """Returns base64 data URI for the SoundCloud track artwork, or '' on failure."""
    try:
        oembed_url = f'https://soundcloud.com/oembed?url={track_url}&format=json'
        req = Request(oembed_url, headers={'User-Agent': UA})
        data = json.loads(urlopen(req, timeout=10).read())
        thumb_url = data.get('thumbnail_url', '')
        # Request the large artwork version
        thumb_url = re.sub(r'-large\.jpg', '-t500x500.jpg', thumb_url)
        if not thumb_url:
            return ''
        req2 = Request(thumb_url, headers={'User-Agent': UA})
        img_bytes = urlopen(req2, timeout=10).read()
        mime = 'image/jpeg' if thumb_url.lower().endswith('.jpg') else 'image/png'
        return f'data:{mime};base64,{base64.b64encode(img_bytes).decode()}'
    except Exception as e:
        print(f'  SC thumb failed for {track_url}: {e}')
        return ''

def make_sc_card(track_url, thumb_data):
    if thumb_data:
        thumb_html = f'<img src="{thumb_data}" style="width:100%;height:100%;object-fit:cover;">'
    else:
        thumb_html = (
            '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;'
            'height:100%;gap:8px;">'
            '<svg width="40" height="40" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" opacity=".4">'
            '<path d="M2 26c0-2.2 1.8-4 4-4s4 1.8 4 4v8c0 2.2-1.8 4-4 4s-4-1.8-4-4v-8zm8-5c0-2.2 1.8-4 4-4s4 1.8 4 4v14c0 2.2-1.8 4-4 4s-4-1.8-4-4V21zm8-7c0-2.2 1.8-4 4-4s4 1.8 4 4v22c0 2.2-1.8 4-4 4s-4-1.8-4-4V14zm8 3c0-2.2 1.8-4 4-4 1.4 0 2.6.7 3.3 1.8C34.6 12.7 37.1 12 40 12c4.4 0 8 3.6 8 8v14c0 4.4-3.6 8-8 8H26c-2.2 0-4-1.8-4-4V17z" fill="#FF5500"/></svg>'
            '<span style="font-family:\'Space Grotesk\',sans-serif;font-size:11px;color:rgba(244,242,248,.35);">Open in browser to play</span>'
            '</div>'
        )
    badge_html = (
        '<span style="position:absolute;left:10px;bottom:10px;width:32px;height:32px;border-radius:999px;'
        'background:#FF5500;display:flex;align-items:center;justify-content:center;'
        'box-shadow:0 4px 14px rgba(0,0,0,.4);pointer-events:none;">'
        '<i class="fa-brands fa-soundcloud" style="color:#FFFFFF;font-size:15px;"></i></span>'
    )
    return (
        f'<div style="height:220px;border-radius:11px;overflow:hidden;position:relative;background:#0C0A13;">'
        f'{thumb_html}{badge_html}'
        f'</div>'
    )

# Find all SoundCloud iframes, fetch thumbnails, replace
if not WEB:
    print('Fetching SoundCloud thumbnails…')
def replace_sc_iframe(m):
    iframe_src = re.search(r'src="([^"]*soundcloud[^"]*)"', m.group(0))
    if not iframe_src:
        return make_sc_card('', '')
    # Extract the track URL from the player URL params
    player_url = iframe_src.group(1)
    url_match = re.search(r'[?&]url=([^&"]+)', player_url)
    track_url = unquote(url_match.group(1)) if url_match else ''
    print(f'  {track_url}')
    thumb = fetch_sc_thumbnail(track_url) if track_url else ''
    return make_sc_card(track_url, thumb)

if not WEB:
    # Online, keep the real interactive SoundCloud players; offline, swap for static cards.
    # The badge <span> after </iframe> (added for platform branding) is optional here
    # since this regex also needs to match the pre-badge markup structure.
    body_html = re.sub(
        r'<div[^>]+border-radius:11px[^>]*><iframe[^>]+soundcloud[^>]*></iframe>(?:<span[^>]*>.*?</span>)?</div>',
        replace_sc_iframe,
        body_html
    )

# ── 10. Convert component class → standalone IIFE ───────────────────────────
# Strip the class wrapper; turn methods into plain functions
js_body = component_js_raw

# Replace `this.root` → `root`, also remove the `const root = this.root;` line
js_body = js_body.replace('this.root', 'root')
# Remove the now-self-referential `const root = root;` line inside componentDidMount
js_body = re.sub(r'\n\s*const root = root;\n', '\n', js_body)
# Replace `this.props.pink` → `pink`
js_body = js_body.replace('this.props.pink', 'pink')
# Replace `this.props.lime` → `lime`
js_body = js_body.replace('this.props.lime', 'lime')
# Replace `this.props.neonGlow` → `true`
js_body = re.sub(r'this\.props\.neonGlow\b', 'true', js_body)
# Replace `this._worldTopo` → `_worldTopo`
js_body = js_body.replace('this._worldTopo', '_worldTopo')
# Replace `this._mapResizeTimer` → `_mapResizeTimer`
js_body = js_body.replace('this._mapResizeTimer', '_mapResizeTimer')
# Replace `this._drawMap` → `_drawMap`
js_body = js_body.replace('this._drawMap', '_drawMap')
# Replace `this._geoPath` → `_geoPath`
js_body = js_body.replace('this._geoPath', '_geoPath')
# Catch-all: any remaining `this.methodName(` → `methodName(`
# (handles this.initBPMPulse(), this.initWorldMap(), etc.)
js_body = re.sub(r'\bthis\.([a-zA-Z_][a-zA-Z0-9_]*)\(', r'\1(', js_body)

# Convert method declarations to function declarations
# handles both `  methodName(args) {` and `  async methodName(args) {`
METHODS = 'componentDidMount|initBPMPulse|initWorldMap|_drawMap|_geoPath|initParticles|initGlitch|initLightbox'
def method_to_fn(m):
    indent  = m.group(1)
    async_  = 'async ' if m.group(2) else ''
    name    = m.group(3)
    args    = m.group(4)
    return f'{indent}{async_}function {name}({args}) {{'
js_body = re.sub(
    r'^(  )(async\s+)?(' + METHODS + r')\(([^)]*)\)\s*\{',
    method_to_fn, js_body, flags=re.MULTILINE
)

# Strip class wrapper lines
lines = js_body.split('\n')
inner = []
skip_first = True
skip_last_brace = True
for line in lines:
    if skip_first and re.match(r'^class Component', line.strip()):
        skip_first = False
        continue
    inner.append(line)
# Remove last closing brace of the class
for i in range(len(inner)-1, -1, -1):
    if inner[i].strip() == '}':
        inner.pop(i)
        break
# Remove renderVals method (not needed standalone) and any remaining class-style methods
clean = []
skip = False
for line in inner:
    if re.match(r'\s*(function renderVals|renderVals)\(\)', line):
        skip = True
    if skip:
        if line.strip() == '}':
            skip = False
        continue
    clean.append(line)
# De-indent by 2 spaces
standalone_js = '\n'.join(
    line[2:] if line.startswith('  ') else line
    for line in clean
)

# Replace the entire try/catch block that fetches world atlas with inline data
# The .then(r => r.json()) has nested parens that break simple [^)]+ regexes, so match the whole try{}catch{} block
standalone_js = re.sub(
    r"try\s*\{[^}]*await fetch[^}]*_worldTopo[^}]*\}\s*catch\([^)]*\)\s*\{[^}]*return;[^}]*\}",
    "_worldTopo = WORLD_ATLAS;",
    standalone_js, flags=re.S
)
standalone_js = re.sub(
    r"try\s*\{[^}]*_worldTopo[^}]*await fetch[^}]*\}\s*catch\([^)]*\)\s*\{[^}]*return;[^}]*\}",
    "_worldTopo = WORLD_ATLAS;",
    standalone_js, flags=re.S
)
# Fix canvas.offsetHeight being 0 on iOS when aspect-ratio CSS isn't supported on <canvas>.
# Fall back to computing height from the 2:1 ratio if offsetHeight is 0.
standalone_js = standalone_js.replace(
    'const H = canvas.offsetHeight;',
    'const H = canvas.offsetHeight || (canvas.offsetWidth / 2);'
)

# Make draw() use ResizeObserver for reliable first-paint on any machine.
# Replace the resize-only listener line with ResizeObserver + resize fallback.
standalone_js = standalone_js.replace(
    "window.addEventListener('resize', () => { clearTimeout(_mapResizeTimer); _mapResizeTimer = setTimeout(draw, 80); });",
    (
        "// ResizeObserver triggers draw the moment the canvas gets its CSS dimensions\n"
        "  if (typeof ResizeObserver !== 'undefined') {\n"
        "    new ResizeObserver(function() { draw(); }).observe(canvas);\n"
        "  }\n"
        "  window.addEventListener('resize', () => { clearTimeout(_mapResizeTimer); _mapResizeTimer = setTimeout(draw, 80); });"
    )
)

# Verify the replacement worked
if 'fetch(' in standalone_js and 'world-atlas' in standalone_js:
    print('WARNING: world-atlas fetch() was NOT replaced — map will fail offline!')
else:
    print('  Map fetch() replaced with WORLD_ATLAS data ✓')

# ── 11. Assemble ─────────────────────────────────────────────────────────────
print('Assembling web site…' if WEB else 'Assembling standalone HTML…')

# Shared page logic (identical for both builds).
PAGE_LOGIC = f'''<script>
/* ── Page logic ── */
(function() {{
  var root = document.getElementById('top');
  var pink = '#FF1E8C';
  var lime = '#C8FF00';
  var _worldTopo = null;
  var _mapResizeTimer = null;

{standalone_js}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', componentDidMount);
  }} else {{
    componentDidMount();
  }}

  // Backup: re-trigger map after full page load in case layout wasn't ready at DOMContentLoaded.
  // initWorldMap is idempotent — safe to call twice.
  window.addEventListener('load', function() {{ initWorldMap(); }});
}})();
</script>'''

# The map ships as a pre-rendered static SVG (see _build_world_svg above), so the canvas-based
# hover logic in the .dc.html source (which needs topojson + a live <canvas>) never runs here.
# This wires the same festival-list interaction directly to that SVG's tagged elements instead.
FESTIVAL_MAP_JS = '''<script>
(function() {
  var rows = document.querySelectorAll('.festival-row');
  if (!rows.length) return;
  var canHover = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  var pinned = null;
  function mapEls(id) {
    return document.querySelectorAll('.map-country[data-country="' + id + '"], .map-loc[data-country="' + id + '"]');
  }
  function highlight(row) {
    document.querySelectorAll('.map-country.map-pop, .map-loc.map-pop').forEach(function(el) { el.classList.remove('map-pop'); });
    rows.forEach(function(r) {
      r.classList.toggle('is-active', r === row);
      r.setAttribute('aria-pressed', r === row ? 'true' : 'false');
    });
    if (row) mapEls(row.getAttribute('data-country')).forEach(function(el) { el.classList.add('map-pop'); });
  }
  rows.forEach(function(row) {
    row.addEventListener('mouseenter', function() { if (canHover) highlight(row); });
    row.addEventListener('mouseleave', function() { if (canHover) highlight(pinned); });
    row.addEventListener('focus', function() { highlight(row); });
    row.addEventListener('blur', function() { highlight(pinned); });
    row.addEventListener('click', function() { pinned = (pinned === row) ? null : row; highlight(pinned); });
    row.addEventListener('keydown', function(e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); } });
  });
})();
</script>'''

if WEB:
    og_image = (SITE_URL.rstrip('/') + '/assets/' + poster_fname) if SITE_URL else 'assets/' + poster_fname
    mobile_src = "small ? 'hero-mobile.mp4' : 'hero.mp4'" if have_mobile_video else "'hero.mp4'"
    standalone = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Noam Leshem — Press Kit 2026</title>
<meta name="description" content="{META_DESC}">
<meta property="og:type" content="website">
<meta property="og:title" content="Noam Leshem — Press Kit 2026">
<meta property="og:description" content="{META_DESC}">
<meta property="og:image" content="{og_image}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Noam Leshem — Press Kit 2026">
<meta name="twitter:description" content="{META_DESC}">
<meta name="twitter:image" content="{og_image}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Unbounded:wght@500;700;800;900&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<script src="https://cdn.jsdelivr.net/npm/topojson-client@3/dist/topojson-client.min.js"></script>
<style>
/* ── Page CSS ── */
{page_css}
/* ── Reveal fallback if JS is slow ── */
[data-reveal]{{opacity:1!important;transform:none!important;}}
</style>
</head>
<body>
{body_html}

<script>
/* ── Hero video: external file (range-supported → plays on iPhone) ──
   Picks the lighter mobile variant on small screens; poster shows until load. */
(function() {{
  var v = document.getElementById('heroVid');
  if (!v) return;
  var small = window.matchMedia && window.matchMedia('(max-width:860px)').matches;
  var s = document.createElement('source');
  s.type = 'video/mp4';
  s.src = {mobile_src};
  v.appendChild(s);
  v.load();
  v.muted = true;
  var p = v.play();
  if (p && p.catch) p.catch(function() {{
    var resume = function() {{
      v.play();
      document.removeEventListener('touchstart', resume);
      document.removeEventListener('click', resume);
    }};
    document.addEventListener('touchstart', resume);
    document.addEventListener('click', resume);
  }});
}})();
</script>
<script>var WORLD_ATLAS = null;</script>
{PAGE_LOGIC}
{FESTIVAL_MAP_JS}
</body>
</html>'''
else:
    standalone = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Noam Leshem — Press Kit 2026</title>
<style>
/* ── Google Fonts ── */
{gf_inline}
</style>
<style>
/* ── FontAwesome ── */
{fa_inline}
</style>
<style>
/* ── Page CSS ── */
{page_css}
/* ── Standalone safety: reveal content even if JS is slow or blocked ── */
[data-reveal]{{opacity:1!important;transform:none!important;}}
</style>
<script>
/* ── TopoJSON ── */
{topo_js}
</script>
</head>
<body>
{body_html}

<script>
/* ── Hero video: decode inlined base64 → blob: URL ──
   WebKit (Safari/iOS, WhatsApp in-app browser) refuses to play video from a
   data: URI, but plays a blob: URL fine. This keeps the page a single file. */
(function() {{
  var v = document.getElementById('heroVid');
  if (!v) return;
  var b64 = v.getAttribute('data-vsrc');
  if (b64) {{
    try {{
      var bin = atob(b64), n = bin.length, bytes = new Uint8Array(n);
      for (var i = 0; i < n; i++) bytes[i] = bin.charCodeAt(i);
      var url = URL.createObjectURL(new Blob([bytes], {{ type: 'video/mp4' }}));
      // iOS plays blob video only via a <source> child, not via v.src (WebKit bug 232076).
      var s = document.createElement('source');
      s.type = 'video/mp4';
      s.src = url;
      v.appendChild(s);
      v.load();
    }} catch (e) {{}}
    v.removeAttribute('data-vsrc');
  }}
  v.muted = true;
  var p = v.play();
  if (p && p.catch) p.catch(function() {{
    var resume = function() {{
      v.play();
      document.removeEventListener('touchstart', resume);
      document.removeEventListener('click', resume);
    }};
    document.addEventListener('touchstart', resume);
    document.addEventListener('click', resume);
  }});
}})();
</script>
<script>
/* ── World atlas (embedded, offline) ── */
var WORLD_ATLAS = {atlas_json};
</script>
{PAGE_LOGIC}
{FESTIVAL_MAP_JS}
</body>
</html>'''


os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(standalone)

size_kb = os.path.getsize(OUT) // 1024
print(f'\n✓  Written: {OUT}')
print(f'   File size: {size_kb} KB')
