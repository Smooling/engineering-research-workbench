from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
PNG = ROOT / 'web' / 'favicon.png'
ICO = ROOT / 'build' / 'research-workstation.ico'

def icon(size=1024):
    s = lambda n: round(n * size / 256)
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    sh = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sd.rounded_rectangle((s(13), s(17), s(243), s(247)), radius=s(42), fill=(66, 91, 96, 62))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(s(7))))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((s(8), s(8), s(248), s(244)), radius=s(40), fill=(220, 232, 234, 255), outline=(164, 192, 195, 255), width=s(3))
    grid = (184, 208, 210, 170)
    for x in range(34, 232, 24):
        d.line((s(x), s(28), s(x), s(224)), fill=grid, width=s(1))
    for y in range(34, 226, 24):
        d.line((s(28), s(y), s(228), s(y)), fill=grid, width=s(1))
    sheet = [(s(48), s(39)), (s(173), s(39)), (s(207), s(73)), (s(207), s(211)), (s(48), s(211))]
    d.polygon(sheet, fill=(247, 244, 233, 255))
    d.line(sheet + [sheet[0]], fill=(212, 217, 207, 255), width=s(2), joint='curve')
    d.polygon([(s(173), s(39)), (s(173), s(73)), (s(207), s(73))], fill=(222, 231, 219, 255))
    d.line((s(173), s(39), s(173), s(73), s(207), s(73)), fill=(193, 204, 196, 255), width=s(2), joint='curve')
    for y, end in ((91, 177), (106, 188), (121, 165)):
        d.rounded_rectangle((s(67), s(y), s(end), s(y + 4)), radius=s(2), fill=(185, 196, 191, 255))
    trace = [(s(68), s(181)), (s(91), s(158)), (s(114), s(169)), (s(137), s(137)), (s(160), s(148)), (s(184), s(112))]
    d.line(trace, fill=(31, 157, 148, 255), width=s(7), joint='curve')
    for x, y in trace:
        r = s(6)
        d.ellipse((x-r, y-r, x+r, y+r), fill=(244, 193, 77, 255), outline=(33, 70, 75, 255), width=s(2))
    d.rounded_rectangle((s(59), s(54), s(88), s(70)), radius=s(5), fill=(31, 157, 148, 255))
    d.rectangle((s(67), s(58), s(80), s(61)), fill=(223, 246, 236, 255))
    d.rectangle((s(67), s(64), s(83), s(67)), fill=(223, 246, 236, 210))
    d.rounded_rectangle((s(11), s(11), s(245), s(241)), radius=s(37), outline=(255, 255, 255, 115), width=s(2))
    return im

master = icon()
sizes = [16, 24, 32, 48, 64, 128, 256]
frames = [master.resize((n, n), Image.Resampling.LANCZOS) for n in sizes]
frames[-1].save(PNG, format='PNG', optimize=True)
frames[-1].save(ICO, format='ICO', sizes=[(n, n) for n in sizes])
print(PNG)
print(ICO)
