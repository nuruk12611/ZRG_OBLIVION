import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SIZE = 1024
img = Image.new("RGBA", (SIZE, SIZE), (10, 14, 23, 255))
draw = ImageDraw.Draw(img)

# 1. Dark Radial Gradient Background
center_x, center_y = SIZE // 2, SIZE // 2
for r in range(SIZE // 2 + 150, 0, -2):
    ratio = r / (SIZE // 2 + 150)
    # interpolate from dark center (20, 35, 60) to outer (8, 11, 18)
    cr = int(8 + (25 - 8) * (1 - ratio))
    cg = int(12 + (45 - 12) * (1 - ratio))
    cb = int(22 + (85 - 22) * (1 - ratio))
    draw.ellipse([center_x - r, center_y - r, center_x + r, center_y + r], fill=(cr, cg, cb, 255))

# 2. Glowing Tech Rings / Circles
glow_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
glow_draw = ImageDraw.Draw(glow_layer)

for i in range(12):
    alpha = int(180 - i * 14)
    width = 3 + i
    glow_draw.ellipse([center_x - 380 - i, center_y - 380 - i, center_x + 380 + i, center_y + 380 + i], outline=(0, 210, 255, alpha), width=2)
    glow_draw.ellipse([center_x - 410 - i, center_y - 410 - i, center_x + 410 + i, center_y + 410 + i], outline=(140, 60, 255, alpha // 2), width=1)

# Subtle cyber dots around ring
for angle in range(0, 360, 15):
    rad = math.radians(angle)
    dx = int(center_x + 380 * math.cos(rad))
    dy = int(center_y + 380 * math.sin(rad))
    glow_draw.ellipse([dx - 3, dy - 3, dx + 3, dy + 3], fill=(0, 255, 255, 220))

# 3. Futuristic Hexagon Shield
shield_pts = [
    (center_x, center_y - 320),
    (center_x + 280, center_y - 150),
    (center_x + 230, center_y + 190),
    (center_x, center_y + 340),
    (center_x - 230, center_y + 190),
    (center_x - 280, center_y - 150),
]

# Shield glow
for i in range(15, 0, -2):
    shield_glow = [(x + (x - center_x) * (i*0.015), y + (y - center_y) * (i*0.015)) for x, y in shield_pts]
    glow_draw.polygon(shield_glow, outline=(0, 180, 255, 40))

# Shield fill
draw.polygon(shield_pts, fill=(15, 22, 38, 230), outline=(0, 230, 255, 255))
draw.polygon(shield_pts, outline=(0, 255, 255, 255))

# Inner Shield border
inner_shield = [(center_x + (x - center_x) * 0.92, center_y + (y - center_y) * 0.92) for x, y in shield_pts]
draw.polygon(inner_shield, outline=(120, 80, 255, 180))

# 4. Stylized High-Tech Neon 'W'
# Coords for modern angular 'W'
w_top_y = center_y - 160
w_bot_y = center_y + 150
w_mid_y = center_y + 20

w_outer_left = center_x - 170
w_inner_left = center_x - 90
w_center = center_x
w_inner_right = center_x + 90
w_outer_right = center_x + 170

w_stroke_poly = [
    # Left wing
    (w_outer_left - 30, w_top_y),
    (w_inner_left - 10, w_bot_y),
    (w_center, w_mid_y - 20),
    (w_inner_right + 10, w_bot_y),
    (w_outer_right + 30, w_top_y),
    (w_outer_right - 10, w_top_y),
    (w_inner_right - 10, w_bot_y - 40),
    (w_center, w_mid_y + 40),
    (w_inner_left + 10, w_bot_y - 40),
    (w_outer_left + 10, w_top_y),
]

# Draw glowing W
for i in range(16, 0, -2):
    glow_draw.polygon(w_stroke_poly, fill=(0, 220, 255, 30))
    glow_draw.line(w_stroke_poly + [w_stroke_poly[0]], fill=(160, 50, 255, 60), width=i*2)

draw.polygon(w_stroke_poly, fill=(0, 240, 255, 255))

# Core white line inside W
w_centerlines = [
    (w_outer_left, w_top_y + 10),
    (w_inner_left, w_bot_y - 20),
    (w_center, w_mid_y),
    (w_inner_right, w_bot_y - 20),
    (w_outer_right, w_top_y + 10),
]
draw.line(w_centerlines, fill=(255, 255, 255, 255), width=8)

# 5. Glowing cyber accents (lightning / speed flares)
draw.polygon([(center_x - 40, center_y - 200), (center_x + 40, center_y - 200), (center_x, center_y - 260)], fill=(0, 255, 255, 255))

# 6. Typography at Bottom
# Load default font or draw clean geometric text
try:
    font_large = ImageFont.truetype("arialbd.ttf", 64)
    font_sub = ImageFont.truetype("arialbd.ttf", 36)
except:
    font_large = ImageFont.load_default()
    font_sub = ImageFont.load_default()

# Text: WELWES
text_main = "WELWES"
bbox = draw.textbbox((0, 0), text_main, font=font_large)
tw = bbox[2] - bbox[0]
draw.text((center_x - tw // 2, center_y + 200), text_main, font=font_large, fill=(255, 255, 255, 255))

# Text: VPN (in neon cyan pill badge)
text_sub = "VPN"
bbox_sub = draw.textbbox((0, 0), text_sub, font=font_sub)
sw = bbox_sub[2] - bbox_sub[0]
sh = bbox_sub[3] - bbox_sub[1]

pill_x1 = center_x - sw // 2 - 25
pill_y1 = center_y + 275
pill_x2 = center_x + sw // 2 + 25
pill_y2 = pill_y1 + sh + 16

draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=15, fill=(0, 210, 255, 255))
draw.text((center_x - sw // 2, pill_y1 + 8), text_sub, font=font_sub, fill=(10, 15, 28, 255))

# Composite glow layer with main image
glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=8))
final_img = Image.alpha_composite(img, glow_layer)

final_img.save(r"c:\Users\dev\Desktop\welwes_avatar.png", "PNG")
print("Avatar successfully saved to c:\\Users\\dev\\Desktop\\welwes_avatar.png!")
