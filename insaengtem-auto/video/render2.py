import os, sys, json, math, subprocess
from PIL import Image, ImageDraw, ImageFilter
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as R
from render import W, H, FPS, FB, FD, FM, font, fit_font, text_layer, paste_t, hexc, eo, eob, clamp, card_img, make_bg, check_icon, overlay

# ---------- cover / thumbnail ----------
def build_cover(data, th, cv):
    img = Image.open(data['image']).convert('RGB')
    crop = data.get('crop')
    img = img.crop(crop) if crop else img.crop((0, 0, img.width, img.height - 26))
    # blurred full-bleed background
    s = max(W / img.width, H / img.height) * 1.15
    bg = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(28)).convert('RGBA')
    dark = Image.new('RGBA', (W, H), hexc(th['bg'], 175))
    bg.alpha_composite(dark)
    vig = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(vig).rectangle([0, 0, W, 560], fill=(0, 0, 0, 120))
    bg.alpha_composite(vig.filter(ImageFilter.GaussianBlur(120)))
    lay = {'bg': bg}
    lay['card'] = card_img(data['image'], 900, crop=crop, radius=56, border=hexc(th['accent']))
    lay['top'] = text_layer(cv['top'], fit_font(FB, 86, cv['top'], 960), hexc('#FFFFFF'), pad=22, bg=hexc('#000000', 170), radius=30)
    lay['big'] = text_layer(cv['big'], fit_font(FB, 200, cv['big'], 1000), hexc(th['accent']), stroke=12, stroke_fill=hexc('#000000'))
    # sticker
    D = 290
    st = Image.new('RGBA', (D + 40, D + 40), (0, 0, 0, 0))
    sd = ImageDraw.Draw(st)
    sd.ellipse([24, 30, 24 + D, 30 + D], fill=(0, 0, 0, 110))
    st = st.filter(ImageFilter.GaussianBlur(6))
    sd = ImageDraw.Draw(st)
    sd.ellipse([16, 16, 16 + D, 16 + D], fill=hexc('#FF3B30'), outline=hexc('#FFFFFF'), width=10)
    lines = cv['sticker'].split('\n')
    fs = 74 if len(lines) == 1 else 62
    tls = [text_layer(l, fit_font(FB, fs, l, D - 70), hexc('#FFFFFF')) for l in lines]
    tot = sum(t.height for t in tls) + 8 * (len(tls) - 1)
    y = 16 + (D - tot) // 2
    for t in tls:
        st.alpha_composite(t, (16 + (D - t.width) // 2, y)); y += t.height + 8
    lay['sticker'] = st
    lay['strip'] = text_layer('사기 전 체크 · 인생템연구소', font(FD, 40), hexc(th['accent']), pad=16, bg=hexc('#000000', 160), radius=24)
    return lay

def draw_cover(cv, t, dur):
    f = cv['bg'].copy()
    z = 1.0 + 0.04 * (t / dur)
    # keep background zoom subtle by scaling a center crop
    if z > 1.001:
        bw, bh = int(W / z), int(H / z)
        f = f.crop(((W - bw) // 2, (H - bh) // 2, (W - bw) // 2 + bw, (H - bh) // 2 + bh)).resize((W, H), Image.BILINEAR)
    cs = 1.0 + 0.03 * math.sin(min(t, 0.5) / 0.5 * math.pi) * 0  # static first frame
    paste_t(f, cv['card'], W / 2, 1150, scale=1.0 + 0.025 * eo(t / dur))
    paste_t(f, cv['top'], W / 2, 360)
    pulse = 1.0 + 0.06 * math.sin(clamp((t - 0.15) / 0.35) * math.pi)
    paste_t(f, cv['big'], W / 2, 545, scale=pulse)
    ang = -12 + 5 * math.sin(t * 2 * math.pi * 1.4)
    st = cv['sticker'].rotate(ang, resample=Image.BICUBIC, expand=True)
    paste_t(f, st, 865, 820, scale=1.0 + 0.05 * math.sin(t * 2 * math.pi * 1.4 + 1))
    paste_t(f, cv['strip'], W / 2, 1610)
    return f

def scene_cover(c, th, t, dur):
    return draw_cover(c['cover'], t, dur)

# ---------- quiz ----------
def build_quiz(data, th):
    q = data['quiz']
    L = {}
    L['q_title'] = text_layer(q['question'], fit_font(FB, 86, q['question'], 980), hexc(th['fg']), stroke=5, stroke_fill=hexc(th['stroke']))
    L['q_hint'] = text_layer('3초 안에 골라보세요', font(FD, 44), hexc(th['sub']))
    opts = []
    for i, o in enumerate(q['options']):
        opts.append(o)
    L['opts'] = opts
    L['note'] = text_layer(q['note'], fit_font(FB, 54, q['note'], 960), hexc(th['mark_fg']), pad=20, bg=hexc(th['mark_bg']), radius=26)
    L['stamp'] = make_stamp(th)
    return L

def make_stamp(th):
    im = Image.new('RGBA', (300, 140), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([6, 6, 294, 134], radius=26, outline=hexc('#FF3B30'), width=12, fill=hexc('#FFFFFF', 235))
    t = text_layer('정답!', font(FB, 72), hexc('#FF3B30'))
    im.alpha_composite(t, ((300 - t.width) // 2, (140 - t.height) // 2))
    return im

def opt_card(th, letter, main, right, state):
    rw, rh = 940, 190
    win = state == 'win'
    im = Image.new('RGBA', (rw + 40, rh + 40), (0, 0, 0, 0))
    sh = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([20, 32, 20 + rw, 32 + rh], radius=40, fill=(0, 0, 0, 100))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(im)
    bgc = hexc(th['accent']) if win else hexc(th['row_bg'])
    if state == 'lose': bgc = hexc(th['row_bg'], 150)
    d.rounded_rectangle([20, 20, 20 + rw, 20 + rh], radius=40, fill=bgc)
    fg = hexc(th['mark_fg'] if win else th['row_fg'])
    cc = hexc(th['row_fg']) if win else hexc(th['accent'])
    d.ellipse([56, 20 + (rh - 110) // 2, 166, 20 + (rh + 110) // 2], fill=cc)
    lt = text_layer(letter, font(FB, 64), hexc(th['accent']) if win else hexc(th['row_bg']))
    im.alpha_composite(lt, (111 - lt.width // 2, 20 + (rh - lt.height) // 2))
    mt = text_layer(main, fit_font(FB, 64, main, 370), fg)
    im.alpha_composite(mt, (200, 20 + (rh - mt.height) // 2))
    rt = text_layer(right or ' ', fit_font(FB, 60, right or ' ', 300), fg)
    im.alpha_composite(rt, (20 + rw - 50 - rt.width, 20 + (rh - rt.height) // 2))
    return im

def scene_quiz_opts(c, th, t, dur):
    f = c['bg'].copy(); L = c['Q']
    paste_t(f, L['q_title'], W / 2, 400, scale=0.6 + 0.4 * eob(t / 0.35), alpha=clamp(t / 0.15))
    n = len(L['opts'])
    for i, o in enumerate(L['opts']):
        tt = (t - 0.3 - i * 0.3) / 0.35
        a = eo(tt)
        card = c['optc'][(i, 'q')]
        paste_t(f, card, W / 2, 620 + i * 230, alpha=clamp(tt * 2), dx=(1 - a) * 700)
    rem = max(0.0, 1 - clamp((t - 1.2) / (dur - 1.3)))
    by = 620 + n * 230 + 40
    d = ImageDraw.Draw(f)
    d.rounded_rectangle([140, by, 140 + 800, by + 18], radius=9, fill=hexc(th['sub'], 80))
    d.rounded_rectangle([140, by, 140 + int(800 * rem), by + 18], radius=9, fill=hexc(th['accent']))
    paste_t(f, L['q_hint'], W / 2, by + 75, alpha=clamp((t - 1.0) / 0.3))
    return f

def scene_quiz_reveal(c, th, t, dur):
    f = c['bg'].copy(); L = c['Q']; q = c['data']['quiz']
    paste_t(f, L['q_title'], W / 2, 400)
    n = len(L['opts'])
    win = q['answer']
    for i, o in enumerate(L['opts']):
        shown = t > 0.25 + i * 0.4
        if t > 1.7:
            st = 'win' if i == win else 'lose'
        else:
            st = 'rev' if shown else 'q'
        card = c['optc'][(i, st)]
        sc = 1.0
        if i == win and t > 1.7: sc = 1.0 + 0.05 * eob((t - 1.7) / 0.35)
        paste_t(f, card, W / 2, 620 + i * 230, scale=sc)
    if t > 1.85:
        s = eob((t - 1.85) / 0.35)
        stamp = L['stamp'].rotate(-10, resample=Image.BICUBIC, expand=True)
        paste_t(f, stamp, 210, 620 + win * 230 - 105, scale=1.6 - 0.6 * s, alpha=clamp((t - 1.85) / 0.12))
    a = eo((t - 2.3) / 0.4)
    paste_t(f, L['note'], W / 2, 620 + n * 230 + 70, alpha=a, dy=(1 - a) * 30)
    return f

# ---------- reasons ----------
def build_reasons(data, th):
    out = []
    for i, (head, sub) in enumerate(data['reasons']):
        num = text_layer(f'{i + 1:02d}', font(FB, 230), hexc(th['accent']), stroke=8, stroke_fill=hexc(th['stroke']))
        hd = text_layer(head, fit_font(FB, 100, head, 980), hexc(th['fg']), stroke=5, stroke_fill=hexc(th['stroke']))
        sb = text_layer(sub, fit_font(FD, 54, sub, 960), hexc(th['mark_fg']), pad=18, bg=hexc(th['mark_bg']), radius=24) if sub else None
        out.append((num, hd, sb))
    return out

def make_reason_scene(idx):
    def fn(c, th, t, dur):
        f = c['bg'].copy()
        num, hd, sb = c['RS'][idx]
        paste_t(f, num, W / 2, 430, scale=0.5 + 0.5 * eob(t / 0.35), alpha=clamp(t / 0.12))
        a = eo((t - 0.2) / 0.35)
        paste_t(f, hd, W / 2, 650, alpha=a, dy=(1 - a) * 50)
        if sb is not None:
            a = eo((t - 0.45) / 0.35)
            paste_t(f, sb, W / 2, 790, alpha=a, dy=(1 - a) * 30)
        a = eo((t - 0.3) / 0.45)
        paste_t(f, c['card_mid'], W / 2, 1220, alpha=a, scale=0.92 + 0.08 * a + 0.03 * (t / dur))
        return f
    return fn

SCENE_FN = {
    'cover': scene_cover, 'math': R.scene_math, 'usp': R.scene_usp, 'offer': R.scene_offer,
    'quiz_opts': scene_quiz_opts, 'quiz_reveal': scene_quiz_reveal,
    'reason0': make_reason_scene(0), 'reason1': make_reason_scene(1), 'reason2': make_reason_scene(2),
}
PLANS = {
    'v1': [('cover', 2.5), ('math', 4.0), ('usp', 5.0), ('offer', 3.5)],
    'v2': [('cover', 2.5), ('quiz_opts', 3.0), ('quiz_reveal', 3.5), ('usp', 3.0), ('offer', 3.0)],
    'v3': [('cover', 2.5), ('reason0', 3.0), ('reason1', 3.0), ('reason2', 3.0), ('offer', 3.5)],
}

def render(cfg_path, variant, outdir, mode='video'):
    base = json.load(open(cfg_path))
    data = dict(base); data.update(base['variants'][variant])
    th = data['theme']
    c = {'data': data}
    c['bg'] = make_bg(th)
    crop = data.get('crop')
    c['card_mid'] = card_img(data['image'], 700, crop=crop, border=hexc(th['card_border']))
    c['card_small'] = card_img(data['image'], 560, crop=crop, radius=40)
    c['L'] = R.build_layers(data, th)
    c['cover'] = build_cover(data, th, data['cover'])
    if 'quiz' in data:
        c['Q'] = build_quiz(data, th)
        c['optc'] = {}
        for i, o in enumerate(data['quiz']['options']):
            c['optc'][(i, 'q')] = opt_card(th, 'ABC'[i], o[0], '?', 'q')
            for st in ['rev', 'win', 'lose']:
                c['optc'][(i, st)] = opt_card(th, 'ABC'[i], o[0], o[1], st)
    if 'reasons' in data:
        c['RS'] = build_reasons(data, th)
    plan = PLANS[data.get('layout', variant)]   # v4~v6 는 layout(v1/v2/v3) 재사용 + 다른 훅·커버
    total = sum(d for _, d in plan)
    os.makedirs(outdir, exist_ok=True)
    # thumbnail (3:4 grid-safe content inside 9:16 frame)
    cov = draw_cover(c['cover'], 0, 2.5)
    cov.alpha_composite(text_layer('광고', font(FD, 34), hexc('#FFFFFF'), pad=14, bg=hexc('#000000', 150), radius=18), (56, 88))
    cov.convert('RGB').save(os.path.join(outdir, 'cover_9x16.jpg'), quality=92)
    cov.convert('RGB').crop((0, 240, 1080, 1680)).save(os.path.join(outdir, 'cover_3x4.jpg'), quality=92)
    if mode == 'stills':
        gt = 0
        for name, dur in plan:
            fr = SCENE_FN[name](c, th, dur * 0.93, dur)
            if name != 'cover': overlay(fr, th, gt + dur * 0.93, total)
            fr.convert('RGB').save(os.path.join(outdir, f'still_{name}.jpg'), quality=88)
            gt += dur
        return
    files = []; gt0 = 0.0
    for name, dur in plan:
        out = os.path.join(outdir, f'{name}.mp4'); files.append(out)
        tmp = out + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', str(FPS), tmp], stdin=subprocess.PIPE)
        for i in range(int(round(dur * FPS))):
            tt = i / FPS
            fr = SCENE_FN[name](c, th, tt, dur)
            if name != 'cover': overlay(fr, th, gt0 + tt, total)
            else:
                # cover still shows the ad label
                ad = text_layer('광고', font(FD, 34), hexc('#FFFFFF'), pad=14, bg=hexc('#000000', 150), radius=18)
                fr.alpha_composite(ad, (56, 88))
            p.stdin.write(fr.convert('RGB').tobytes())
        p.stdin.close()
        if p.wait() != 0: raise SystemExit('ffmpeg failed ' + name)
        os.replace(tmp, out); gt0 += dur
    lst = os.path.join(outdir, 'list.txt')
    open(lst, 'w').write(''.join(f"file '{os.path.abspath(x)}'\n" for x in files))
    subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', os.path.join(outdir, 'video_silent.mp4')])
    json.dump({'plan': plan}, open(os.path.join(outdir, 'plan.json'), 'w'))

if __name__ == '__main__':
    render(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else 'video')
