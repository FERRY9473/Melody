import aiohttp
import aiofiles
import gc
from io import BytesIO
from pathlib import Path
from py_yt import VideosSearch
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

from Melody.utils.fonts import get_font_path

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)


def truncate_text(text, font, max_width, draw):
    """Memotong teks jika melebihi max_width dan menambahkan ..."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while draw.textlength(text + "...", font=font) > max_width:
        text = text[:-1]
        if not text:
            break
    return text + "..." if text else ""


def draw_rounded_rect(draw, xy, radius, fill):
    """Membuat persegi panjang dengan sudut melengkung"""
    x0, y0, x1, y1 = xy
    draw.rectangle([(x0, y0 + radius), (x1, y1 - radius)], fill=fill)
    draw.rectangle([(x0 + radius, y0), (x1 - radius, y1)], fill=fill)
    draw.pieslice([(x0, y0), (x0 + radius * 2, y0 + radius * 2)], 180, 270, fill=fill)
    draw.pieslice([(x1 - radius * 2, y0), (x1, y0 + radius * 2)], 270, 360, fill=fill)
    draw.pieslice([(x0, y1 - radius * 2), (x0 + radius * 2, y1)], 90, 180, fill=fill)
    draw.pieslice([(x1 - radius * 2, y1 - radius * 2), (x1, y1)], 0, 90, fill=fill)


async def gen_thumb(videoid: str):
    """
    Menghasilkan thumbnail dengan:
    - Thumbnail persegi panjang BESAR (640x360) di atas judul
    - Judul 1 baris (lebar maksimal 1100px)
    - Artist/channel di bawah judul
    - Progress bar 10% dengan waktu di bawah (rata dengan ujung bar)
    - Kontrol playback (play, prev, next, shuffle, repeat)
    """
    output_path = CACHE_DIR / f"melody_{videoid}.jpg"
    if output_path.exists():
        return str(output_path)

    # --- Ambil data video ---
    url = f"https://www.youtube.com/watch?v={videoid}"
    try:
        results = VideosSearch(url, limit=1)
        result = (await results.next())["result"][0]
        title = result.get("title", "Unknown Title")
        duration = result.get("duration", "0:00")
        channel = result.get("channel", {}).get("name", "Unknown Channel")
        thumb_url = result.get("thumbnails", [{}])[0].get("url", "")
    except Exception as e:
        print(f"[gen_thumb] Info fetch error: {e}")
        title = "Melody Player"
        duration = "0:00"
        channel = "Melody"
        thumb_url = ""

    # --- Download thumbnail video untuk background blur ---
    temp_thumb = CACHE_DIR / f"temp_{videoid}.jpg"
    if thumb_url:
        async with aiohttp.ClientSession() as session:
            async with session.get(thumb_url) as resp:
                if resp.status == 200:
                    async with aiofiles.open(temp_thumb, "wb") as f:
                        await f.write(await resp.read())

    # --- Buat background blur dari thumbnail ---
    try:
        bg_img = Image.open(temp_thumb).convert("RGB")
        bg_img = bg_img.resize((1280, 720))
        bg_img = bg_img.filter(ImageFilter.BoxBlur(20))
        enhancer = ImageEnhance.Brightness(bg_img)
        bg_img = enhancer.enhance(0.6)
    except Exception as e:
        print(f"[gen_thumb] Gagal buat background blur, pakai solid: {e}")
        bg_img = Image.new("RGB", (1280, 720), "#121212")

    draw = ImageDraw.Draw(bg_img)

    # --- Load font menggunakan sistem Melody ---
    try:
        title_font_path = await get_font_path("Montserrat-Bold", "bold")
        artist_font_path = await get_font_path("Poppins-SemiBold", "regular")
        progress_font_path = await get_font_path("Poppins-Regular", "regular")
        tiny_font_path = await get_font_path("Poppins-Light", "regular")

        f_title = ImageFont.truetype(title_font_path, 42) if title_font_path else ImageFont.load_default()
        f_artist = ImageFont.truetype(artist_font_path, 26) if artist_font_path else ImageFont.load_default()
        f_progress = ImageFont.truetype(progress_font_path, 20) if progress_font_path else ImageFont.load_default()
        f_tiny = ImageFont.truetype(tiny_font_path, 18) if tiny_font_path else ImageFont.load_default()

        f_fallback_title = ImageFont.truetype(
            await get_font_path("NotoSans-Bold", "bold") or "", 42
        ) if await get_font_path("NotoSans-Bold", "bold") else f_title
        f_fallback_artist = ImageFont.truetype(
            await get_font_path("NotoSans-Regular", "regular") or "", 26
        ) if await get_font_path("NotoSans-Regular", "regular") else f_artist
    except Exception as e:
        print(f"[gen_thumb] Font error: {e}")
        f_title = f_artist = f_progress = f_tiny = f_fallback_title = f_fallback_artist = ImageFont.load_default()

    center_x = 1280 // 2

    # Helper untuk teks dengan fallback
    def draw_text_with_fallback(xy, text, primary_font, fallback_font, fill):
        try:
            draw.text(xy, text, font=primary_font, fill=fill)
        except UnicodeEncodeError:
            draw.text(xy, text, font=fallback_font, fill=fill)
        except:
            draw.text(xy, text, font=fallback_font, fill=fill)

    # --- THUMBNAIL PERSEGI PANJANG BESAR (640x360) ---
    thumb_small = None
    if thumb_url:
        async with aiohttp.ClientSession() as session:
            async with session.get(thumb_url) as resp:
                if resp.status == 200:
                    thumb_data = await resp.read()
                    thumb_small = Image.open(BytesIO(thumb_data)).convert("RGB")
    
    if thumb_small:
        # Resize ke ukuran 640x360 (lebih besar 1x lagi)
        thumb_width = 640
        thumb_height = 360
        thumb_small = thumb_small.resize((thumb_width, thumb_height))
        # Buat sudut melengkung
        mask = Image.new("L", (thumb_width, thumb_height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (thumb_width, thumb_height)], radius=20, fill=255)
        thumb_small.putalpha(mask)
        # Posisi di tengah
        thumb_x = center_x - (thumb_width // 2)
        thumb_y = 30
        bg_img.paste(thumb_small, (thumb_x, thumb_y), thumb_small)
        title_y_start = thumb_y + thumb_height + 30
    else:
        title_y_start = 120

    # --- JUDUL 1 BARIS ---
    max_title_width = 900
    title_text = truncate_text(title.strip(), f_fallback_title, max_title_width, draw)
    title_w = draw.textlength(title_text, font=f_fallback_title)
    draw_text_with_fallback((center_x - title_w // 2, title_y_start), title_text, f_title, f_fallback_title, "#FFFFFF")

    # --- Artist / Channel ---
    artist_y = title_y_start + 60
    artist_text = channel.strip()
    artist_w = draw.textlength(artist_text, font=f_fallback_artist)
    draw_text_with_fallback((center_x - artist_w // 2, artist_y), artist_text, f_artist, f_fallback_artist, "#B3B3B3")

    # --- PROGRESS BAR (10%) ---
    progress_y = artist_y + 55
    bar_width = 900
    bar_start_x = center_x - (bar_width // 2)
    progress_percent = 0.20
    progress_width = int(bar_width * progress_percent)

    # Background bar (abu-abu)
    draw.rectangle([bar_start_x, progress_y, bar_start_x + bar_width, progress_y + 8], fill="#3E3E3E")
    # Progress bar (hijau)
    draw.rectangle([bar_start_x, progress_y, bar_start_x + progress_width, progress_y + 8], fill="#1DB954")
    # Lingkaran kecil di ujung progress
    circle_radius = 9
    draw.ellipse(
        [
            bar_start_x + progress_width - circle_radius,
            progress_y - circle_radius + 3,
            bar_start_x + progress_width + circle_radius,
            progress_y + circle_radius + 3,
        ],
        fill="#1DB954",
    )

    # --- Waktu di BAWAH progress bar ---
    time_y = progress_y + 22

    # Waktu kiri (00:00)
    draw.text((bar_start_x, time_y), "00:20", font=f_progress, fill="#B3B3B3")

    # Waktu kanan (duration)
    right_text_width = draw.textlength(duration, font=f_progress)
    draw.text((bar_start_x + bar_width - right_text_width, time_y), duration, font=f_progress, fill="#B3B3B3")

    # --- KONTROL PLAYBACK ---
    ctrl_y = progress_y + 70

    # Play Button (Green Circle)
    cr_large = 40
    draw.ellipse(
        [(center_x - cr_large, ctrl_y - cr_large), (center_x + cr_large, ctrl_y + cr_large)],
        fill="#1DB954",
    )
    # Play Icon (Triangle)
    tri_w = 26
    tri_h = 30
    offset_x = 4
    draw.polygon(
        [
            (center_x - tri_w // 2 + offset_x, ctrl_y - tri_h // 2),
            (center_x - tri_w // 2 + offset_x, ctrl_y + tri_h // 2),
            (center_x + tri_w // 2 + offset_x, ctrl_y),
        ],
        fill="black",
    )

    # Previous Button
    prev_x = center_x - 110
    p_tri_w, p_tri_h = 18, 22
    draw.polygon(
        [
            (prev_x + p_tri_w // 2, ctrl_y - p_tri_h // 2),
            (prev_x + p_tri_w // 2, ctrl_y + p_tri_h // 2),
            (prev_x - p_tri_w // 2, ctrl_y),
        ],
        fill="#FFFFFF",
    )
    draw.rectangle(
        [
            (prev_x - p_tri_w // 2 - 5, ctrl_y - p_tri_h // 2),
            (prev_x - p_tri_w // 2, ctrl_y + p_tri_h // 2),
        ],
        fill="#FFFFFF",
    )

    # Next Button
    next_x = center_x + 110
    draw.polygon(
        [
            (next_x - p_tri_w // 2, ctrl_y - p_tri_h // 2),
            (next_x - p_tri_w // 2, ctrl_y + p_tri_h // 2),
            (next_x + p_tri_w // 2, ctrl_y),
        ],
        fill="#FFFFFF",
    )
    draw.rectangle(
        [
            (next_x + p_tri_w // 2, ctrl_y - p_tri_h // 2),
            (next_x + p_tri_w // 2 + 5, ctrl_y + p_tri_h // 2),
        ],
        fill="#FFFFFF",
    )

    # Shuffle & Repeat pseudo-icons
    shuf_str = "SHUFFLE"
    rep_str = "REPEAT"
    draw.text((center_x - 220, ctrl_y - 8), shuf_str, font=f_tiny, fill="#B3B3B3")
    draw.text((center_x + 170, ctrl_y - 8), rep_str, font=f_tiny, fill="#B3B3B3")

    # --- Simpan hasil ---
    bg_img.save(output_path, "JPEG", quality=85, optimize=True)
    bg_img.close()

    # Bersihkan file sementara
    if temp_thumb.exists():
        temp_thumb.unlink()

    gc.collect()
    return str(output_path)
