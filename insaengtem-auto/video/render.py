import os, sys, json, math, subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
# 폰트: 환경변수 INSAENGTEM_FONT_BLACK / _BOLD / _MEDIUM 으로 덮어쓰기 가능.
# 없으면 Noto CJK(리눅스) → 맑은 고딕(Windows) → 애플SD산돌(맥) → WenQuanYi 순으로 자동 탐색.
_CANDS = {
    'black': ['/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc', 'C:/Windows/Fonts/malgunbd.ttf',
              '/System/Library/Fonts/AppleSDGothicNeo.ttc', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'],
    'bold': ['/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 'C:/Windows/Fonts/malgunbd.ttf',
             '/System/Library/Fonts/AppleSDGothicNeo.ttc', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'],
    'medium': ['/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc', 'C:/Windows/Fonts/malgun.ttf',
               '/System/Library/Fonts/AppleSDGothicNeo.ttc', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'],
}
def _pick(kind):
    env = os.environ.get('INSAENGTEM_FONT_' + kind.upper())
    if env: return env
    for c in _CANDS[kind]:
        if os.path.exists(c): return c
    raise SystemExit('한글 폰트를 찾지 못했습니다. INSAENGTEM_FONT_%s 환경변수로 경로를 지정하세요.' % kind.upper())
FB, FD, FM = _pick('black'), _pick('bold'), _pick('medium')
def _index(path):
    # Noto CJK .ttc 는 index 1 이 KR. 그 외 폰트는 0
    return 1 if 'NotoSansCJK' in path else 0
_fc = {}
def font(path, size):
    k = (path, size)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(path, size, index=_index(path))
    return _fc[k]

def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def eo(t): t = clamp(t); return 1 - (1 - t) ** 3
def eob(t):
    t = clamp(t); c1 = 1.70158; c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
def hexc(h, a=255):
    h = h.lstrip('#'); return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)

def fit_font(path, size, text, maxw):
    f = font(path, size)
    while f.getlength(text) > maxw and size > 20:
        size -= 2; f = font(path, size)
    return f

def text_layer(text, f, fill, pad=0, bg=None, radius=0, stroke=0, stroke_fill=None):
    bb = f.getbbox(text)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    im = Image.new('RGBA', (int(tw + pad * 2 + stroke * 2), int(th + pad * 2 + stroke * 2)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if bg:
        d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=radius, fill=bg)
    d.text((pad + stroke - bb[0], pad + stroke - bb[1]), text, font=f, fill=fill,
           stroke_width=stroke, stroke_fill=stroke_fill)
    return im

def paste_t(base, layer, cx, cy, scale=1.0, alpha=1.0, dx=0, dy=0):
    if alpha <= 0.01 or scale <= 0.01: return
    l = layer
    if abs(scale - 1) > 0.002:
        l = l.resize((max(1, int(l.width * scale)), max(1, int(l.height * scale))), Image.LANCZOS)
    if alpha < 0.999:
        a = l.getchannel('A').point(lambda v: int(v * alpha))
        l = l.copy(); l.putalpha(a)
    base.alpha_composite(l, (int(cx - l.width / 2 + dx), int(cy - l.height / 2 + dy)))

def card_img(path, width, crop_bottom=26, crop=None, radius=48, border=None):
    im = Image.open(path).convert('RGBA')
    if crop: im = im.crop(crop)
    else: im = im.crop((0, 0, im.width, im.height - crop_bottom))
    h = int(im.height * width / im.width)
    im = im.resize((width, h), Image.LANCZOS)
    m = Image.new('L', im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, width - 1, h - 1], radius=radius, fill=255)
    im.putalpha(m)
    pad = 40
    out = Image.new('RGBA', (width + pad * 2, h + pad * 2), (0, 0, 0, 0))
    sh = Image.new('RGBA', out.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 14, pad + width, pad + h + 14], radius=radius, fill=(0, 0, 0, 120))
    sh = sh.filter(ImageFilter.GaussianBlur(18))
    out.alpha_composite(sh)
    if border:
        bd = Image.new('RGBA', out.size, (0, 0, 0, 0))
        ImageDraw.Draw(bd).rounded_rectangle([pad - 8, pad - 8, pad + width + 7, pad + h + 7], radius=radius + 8, fill=border)
        out.alpha_composite(bd)
    out.alpha_composite(im, (pad, pad))
    return out

def make_bg(th):
    bg = Image.new('RGBA', (W, H), hexc(th['bg']))
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-300, 500, W + 300, 1700], fill=hexc(th['glow'], 110))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    bg.alpha_composite(glow)
    grid = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    for x in range(0, W, 60): g.line([(x, 0), (x, H)], fill=hexc(th['grid'], 18), width=2)
    for y in range(0, H, 60): g.line([(0, y), (W, y)], fill=hexc(th['grid'], 18), width=2)
    bg.alpha_composite(grid)
    return bg

def check_icon(size, color, fg):
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([0, 0, size - 1, size - 1], fill=color)
    w = max(6, size // 9)
    d.line([(size * .27, size * .53), (size * .44, size * .69), (size * .74, size * .35)], fill=fg, width=w, joint='curve')
    return im

def overlay(frame, th, gt, total):
    d = ImageDraw.Draw(frame)
    d.rectangle([0, 0, int(W * clamp(gt / total)), 12], fill=hexc(th['accent']))
    ad = text_layer('광고', font(FD, 34), hexc('#FFFFFF'), pad=14, bg=hexc('#000000', 150), radius=18)
    frame.alpha_composite(ad, (56, 88))
    br = text_layer('인생템연구소', font(FD, 34), hexc(th['sub']), pad=14, bg=hexc(th['pill'], 170), radius=18)
    frame.alpha_composite(br, (W - 56 - br.width, 88))

# ---------- scenes ----------
def scene_hook(c, th, t, dur):
    f = c['bg'].copy()
    ks = 1.10 - 0.10 * eo(t / dur)
    a = eo(t / 0.35)
    paste_t(f, c['card_big'], W / 2, c.get('hook_card_y',1290), scale=ks, alpha=a, dy=(1 - a) * 120)
    tag = c['L']['tag']
    s = eob((t - 0.0) / 0.4)
    paste_t(f, tag, W / 2, 300, scale=0.6 + 0.4 * s, alpha=clamp(t / 0.2))
    for i, (ly, lay) in enumerate(c['L']['hook']):
        tt = (t - 0.10 - i * 0.14) / 0.42
        s = eob(tt)
        paste_t(f, lay, W / 2, ly, scale=0.5 + 0.5 * s, alpha=clamp(tt * 3))
    return f

def scene_math(c, th, t, dur):
    f = c['bg'].copy()
    L = c['L']
    paste_t(f, L['m_label'], W / 2, 400, scale=0.6 + 0.4 * eob(t / 0.35), alpha=clamp(t / 0.15))
    a = eo((t - 0.2) / 0.4)
    paste_t(f, L['m_formula'], W / 2, 560, alpha=a, dy=(1 - a) * 40)
    # count-up big number
    p = eo((t - 0.55) / 1.1)
    if p > 0:
        val = c['data']['math']['value']
        cur = int(round(val * p))
        txt = c['data']['math']['fmt'].format(f'{cur:,}')
        big = text_layer(txt, fit_font(FB, 210, txt, 980), hexc(th['accent']), stroke=6, stroke_fill=hexc(th['stroke']))
        bump = 1 + 0.08 * math.sin(clamp((t - 1.65) / 0.3) * math.pi)
        paste_t(f, big, W / 2, 820, scale=bump, alpha=clamp(p * 4))
    a = eo((t - 1.8) / 0.4)
    paste_t(f, L['m_sub'], W / 2, 1040, alpha=a, dy=(1 - a) * 30)
    a = eo((t - 0.3) / 0.5)
    paste_t(f, c['card_small'], W / 2, 1320, alpha=a, dy=(1 - a) * 80, scale=1.0 + 0.03 * (t / dur))
    return f

def scene_usp(c, th, t, dur):
    f = c['bg'].copy()
    L = c['L']
    paste_t(f, L['u_title'], W / 2, 380, scale=0.6 + 0.4 * eob(t / 0.35), alpha=clamp(t / 0.15))
    for i, row in enumerate(L['u_rows']):
        tt = (t - 0.35 - i * 0.5) / 0.4
        a = eo(tt)
        paste_t(f, row, W / 2, 580 + i * 215, alpha=clamp(tt * 2), dx=-(1 - a) * 700)
    a = eo((t - 2.0) / 0.5)
    paste_t(f, c['card_small'], W / 2, 1400, alpha=a, dy=(1 - a) * 80, scale=0.85)
    return f

def scene_offer(c, th, t, dur):
    f = c['bg'].copy()
    L = c['L']
    a = eo(t / 0.35)
    paste_t(f, c['card_mid'], W / 2, 610, alpha=a, scale=0.9 + 0.1 * a)
    if c['data']['offer']['type'] == 'price':
        a = eo((t - 0.25) / 0.35)
        paste_t(f, L['o_orig'], W / 2, 980, alpha=a)
        s = eob((t - 0.45) / 0.45)
        paste_t(f, L['o_price'], W / 2, 1110, scale=0.4 + 0.6 * s, alpha=clamp((t - 0.45) / 0.1))
        a = eo((t - 0.8) / 0.35)
        paste_t(f, L['o_note'], W / 2, 1245, alpha=a)
    else:
        for i, row in enumerate(L['o_rows']):
            tt = (t - 0.25 - i * 0.22) / 0.35
            a = eo(tt)
            paste_t(f, row, W / 2, 985 + i * 112, alpha=clamp(tt * 2), dx=(1 - a) * 400)
    pt = t - 1.0
    if pt > 0:
        pulse = 1 + 0.045 * math.sin(pt * 2 * math.pi * 1.3)
        paste_t(f, L['o_cta'], W / 2, 1420, scale=eob(pt / 0.4) * pulse, alpha=clamp(pt / 0.15))
    return f

SCENES = [('hook', scene_hook, 2.5), ('math', scene_math, 4.0), ('usp', scene_usp, 5.0), ('offer', scene_offer, 3.5)]

def build_layers(data, th):
    L = {}
    L['tag'] = text_layer(data['tag'], font(FD, 40), hexc(th['tag_fg']), pad=18, bg=hexc(th['tag_bg']), radius=24)
    hook = []
    y = 470
    for line in data['hook']:
        txt, size, style = line['t'], line['s'], line.get('style', 'plain')
        fnt = fit_font(FB, size, txt, 960)
        if style == 'mark':
            lay = text_layer(txt, fnt, hexc(th['mark_fg']), pad=16, bg=hexc(th['mark_bg']), radius=20)
        elif style == 'accent':
            lay = text_layer(txt, fnt, hexc(th['accent']), stroke=5, stroke_fill=hexc(th['stroke']))
        else:
            lay = text_layer(txt, fnt, hexc(th['fg']), stroke=4, stroke_fill=hexc(th['stroke']))
        y += lay.height / 2
        hook.append((y, lay))
        y += lay.height / 2 + 14
    L['hook'] = hook
    m = data['math']
    L['m_label'] = text_layer(m['label'], font(FD, 46), hexc(th['tag_fg']), pad=18, bg=hexc(th['tag_bg']), radius=24)
    L['m_formula'] = text_layer(m['formula'], fit_font(FD, 70, m['formula'], 960), hexc(th['fg']))
    L['m_sub'] = text_layer(m['sub'], fit_font(FM, 50, m['sub'], 960), hexc(th['sub']))
    u = data['usp']
    L['u_title'] = text_layer(u['title'], fit_font(FB, 84, u['title'], 960), hexc(th['fg']), stroke=4, stroke_fill=hexc(th['stroke']))
    rows = []
    for r in u['rows']:
        rw, rh = 940, 180
        im = Image.new('RGBA', (rw + 40, rh + 40), (0, 0, 0, 0))
        sh = Image.new('RGBA', im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([20, 30, 20 + rw, 30 + rh], radius=40, fill=(0, 0, 0, 90))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)))
        ImageDraw.Draw(im).rounded_rectangle([20, 20, 20 + rw, 20 + rh], radius=40, fill=hexc(th['row_bg']))
        ic = check_icon(104, hexc(th['accent']), hexc(th['row_bg']))
        im.alpha_composite(ic, (60, 20 + (rh - 104) // 2))
        f1 = fit_font(FB, 58, r[0], rw - 230)
        t1 = text_layer(r[0], f1, hexc(th['row_fg']))
        if len(r) > 1 and r[1]:
            f2 = fit_font(FM, 38, r[1], rw - 230)
            t2 = text_layer(r[1], f2, hexc(th['row_sub']))
            tot = t1.height + 10 + t2.height
            y0 = 20 + (rh - tot) // 2
            im.alpha_composite(t1, (200, y0)); im.alpha_composite(t2, (202, y0 + t1.height + 10))
        else:
            im.alpha_composite(t1, (200, 20 + (rh - t1.height) // 2))
        rows.append(im)
    L['u_rows'] = rows
    o = data['offer']
    if o['type'] == 'price':
        orig = text_layer(o['orig'], font(FM, 54), hexc(th['sub']))
        d = ImageDraw.Draw(orig)
        # strike only the price part
        d.line([(orig.width * o.get('strike_from', 0.0), orig.height * 0.55), (orig.width, orig.height * 0.55)], fill=hexc(th['sub']), width=5)
        L['o_orig'] = orig
        L['o_price'] = text_layer(o['price'], fit_font(FB, 150, o['price'], 980), hexc(th['accent']), stroke=6, stroke_fill=hexc(th['stroke']))
        L['o_note'] = text_layer(o['note'], fit_font(FD, 46, o['note'], 960), hexc(th['fg']))
    else:
        rows = []
        for i, (a, b, c2) in enumerate(o['rows']):
            hi = i == len(o['rows']) - 1
            rw, rh = 900, 96
            im = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
            ImageDraw.Draw(im).rounded_rectangle([0, 0, rw - 1, rh - 1], radius=30, fill=hexc(th['accent'] if hi else th['row_bg']))
            fg = hexc(th['mark_fg'] if hi else th['row_fg'])
            ta = text_layer(a, font(FB, 46), fg); tb = text_layer(b, font(FD, 42), fg); tc = text_layer(c2, font(FB, 46), fg)
            im.alpha_composite(ta, (40, (rh - ta.height) // 2))
            im.alpha_composite(tb, (300, (rh - tb.height) // 2))
            im.alpha_composite(tc, (rw - 40 - tc.width, (rh - tc.height) // 2))
            rows.append(im)
        L['o_rows'] = rows
    # CTA button with up-arrow
    ctxt = o['cta']
    fc = fit_font(FB, 54, ctxt, 760)
    tl = text_layer(ctxt, fc, hexc(th['cta_fg']))
    bw, bh = tl.width + 190, 132
    btn = Image.new('RGBA', (bw + 40, bh + 40), (0, 0, 0, 0))
    sh = Image.new('RGBA', btn.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([20, 32, 20 + bw, 32 + bh], radius=66, fill=(0, 0, 0, 120))
    btn.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)))
    bd = ImageDraw.Draw(btn)
    bd.rounded_rectangle([20, 20, 20 + bw, 20 + bh], radius=66, fill=hexc(th['cta_bg']))
    btn.alpha_composite(tl, (20 + 60, 20 + (bh - tl.height) // 2))
    ax, ay = 20 + bw - 90, 20 + bh // 2
    bd.polygon([(ax, ay - 30), (ax - 28, ay + 4), (ax + 28, ay + 4)], fill=hexc(th['cta_fg']))
    bd.rectangle([ax - 10, ay, ax + 10, ay + 30], fill=hexc(th['cta_fg']))
    L['o_cta'] = btn
    return L

def render(cfg_path, outdir):
    data = json.load(open(cfg_path))
    th = data['theme']
    c = {'data': data}
    c['bg'] = make_bg(th)
    img = data['image']; crop = data.get('crop')
    c['card_big'] = card_img(img, 820, crop=crop, border=hexc(th['card_border']) if th.get('card_border') else None)
    c['card_mid'] = card_img(img, 700, crop=crop, border=hexc(th['card_border']) if th.get('card_border') else None)
    c['card_small'] = card_img(img, 560, crop=crop, radius=40)
    c['L'] = build_layers(data, th)
    last=c['L']['hook'][-1]; c['hook_card_y']=int(last[0]+last[1].height/2+40+c['card_big'].height/2-40)
    total = sum(s[2] for s in SCENES)
    os.makedirs(outdir, exist_ok=True)
    only = sys.argv[3] if len(sys.argv) > 3 else None
    gt0 = 0.0
    files = []
    for name, fn, dur in SCENES:
        out = os.path.join(outdir, f'{name}.mp4')
        files.append(out)
        n = int(round(dur * FPS))
        if only == 'stills':
            for tt in [dur * 0.95]:
                fr = fn(c, th, tt, dur); overlay(fr, th, gt0 + tt, total)
                fr.convert('RGB').save(os.path.join(outdir, f'still_{name}.jpg'), quality=90)
            gt0 += dur; continue
        tmp = out + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', str(FPS), tmp], stdin=subprocess.PIPE)
        for i in range(n):
            tt = i / FPS
            fr = fn(c, th, tt, dur)
            overlay(fr, th, gt0 + tt, total)
            p.stdin.write(fr.convert('RGB').tobytes())
        p.stdin.close()
        if p.wait() == 0: os.replace(tmp, out)
        else: raise SystemExit('ffmpeg failed ' + name)
        gt0 += dur
    if only == 'stills': return
    lst = os.path.join(outdir, 'list.txt')
    open(lst, 'w').write(''.join(f"file '{os.path.abspath(x)}'\n" for x in files))
    silent = os.path.join(outdir, 'video_silent.mp4')
    subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', silent])

if __name__ == '__main__':
    render(sys.argv[1], sys.argv[2])
