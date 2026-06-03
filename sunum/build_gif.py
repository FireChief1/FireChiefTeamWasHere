"""Animated LangGraph flow GIF for LinkedIn — space theme, matches slide 5."""
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 600
BG = (10, 14, 39)
CARD = (28, 35, 73)
PANEL = (21, 27, 61)
ICE = (122, 162, 247)
MINT = (45, 212, 191)
CORAL = (247, 118, 142)
GOLD = (224, 175, 104)
TEXT = (255, 255, 255)
MUTED = (169, 177, 214)
DIM = (70, 78, 120)
BORDERDIM = (42, 51, 107)

FB = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FR = "/System/Library/Fonts/Supplemental/Arial.ttf"
fTitle = ImageFont.truetype(FB, 34)
fKick = ImageFont.truetype(FB, 16)
fNode = ImageFont.truetype(FB, 17)
fNum = ImageFont.truetype(FB, 18)
fLbl = ImageFont.truetype(FB, 17)
fLeg = ImageFont.truetype(FR, 16)
fLegB = ImageFont.truetype(FB, 16)
fFoot = ImageFont.truetype(FR, 13)

NODES = [
    ("1", "Intake", ICE), ("2", "Brief", ICE), ("3", "Classifier", MINT),
    ("4", "RAG", MINT), ("5", "Analyst", GOLD), ("6", "Developer", CORAL),
    ("7", "Reviewer", CORAL), ("8", "QA", MINT), ("9", "Supervisor", GOLD),
    ("10", "Integrator", ICE),
]
N = len(NODES)

# layout
BW, BH, GAP = 100, 112, 16
START_X = (W - (N * BW + (N - 1) * GAP)) // 2
LANE_Y = 280
def nx(i): return START_X + i * (BW + GAP)
def ncx(i): return nx(i) + BW // 2
MID_Y = LANE_Y + BH // 2

# static starfield
STARS = [(60, 70), (180, 130), (300, 50), (430, 110), (560, 60), (700, 120),
         (840, 80), (980, 50), (1100, 120), (140, 480), (320, 520), (520, 500),
         (760, 520), (980, 500), (1120, 470), (60, 420), (1040, 200), (90, 230)]


def lerp(c1, c2, t):
    return tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))


def rrect(d, box, radius, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_base(d):
    d.rectangle([0, 0, W, H], fill=BG)
    for x, y in STARS:
        d.ellipse([x, y, x + 2, y + 2], fill=(90, 100, 150))
    # accent bar + header
    d.rectangle([0, 0, 8, H], fill=ICE)
    d.text((40, 30), "ÇEKİRDEK · AKIŞ", font=fKick, fill=MINT)
    d.text((40, 54), "LangGraph Akış Diyagramı", font=fTitle, fill=TEXT)
    d.text((40, H - 32), "Yerel Çoklu-Agent Yazılım Geliştirme Takımı", font=fFoot, fill=DIM)


def draw_node(d, i, lit):
    num, name, accent = NODES[i]
    x = nx(i)
    bcol = lerp(BORDERDIM, accent, lit)
    fillc = lerp(PANEL, CARD, lit)
    rrect(d, [x, LANE_Y, x + BW, LANE_Y + BH], 12, fill=fillc, outline=bcol, width=2)
    # number circle
    cx, cy, r = ncx(i), LANE_Y + 28, 18
    circ = lerp(DIM, accent, lit)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=circ)
    tb = d.textbbox((0, 0), num, font=fNum)
    d.text((cx - (tb[2] - tb[0]) / 2, cy - (tb[3] - tb[1]) / 2 - 2), num, font=fNum, fill=BG)
    # name
    namec = lerp(DIM, TEXT, lit)
    tb = d.textbbox((0, 0), name, font=fNode)
    d.text((cx - (tb[2] - tb[0]) / 2, LANE_Y + 64), name, font=fNode, fill=namec)


def draw_arrow(d, x1, y1, x2, y2, color, width=3, head=9):
    d.line([x1, y1, x2, y2], fill=color, width=width)
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    for s in (-1, 1):
        a = ang + s * 2.6
        d.line([x2, y2, x2 + head * math.cos(a), y2 + head * math.sin(a)], fill=color, width=width)


def lane_arrow(d, i, lit):
    # arrow from node i to node i+1
    x1 = nx(i) + BW
    x2 = nx(i + 1)
    col = lerp(BORDERDIM, MINT if i == 8 else DIM, lit)
    if lit > 0.05:
        draw_arrow(d, x1, MID_Y, x2 - 2, MID_Y, col, width=3 if i == 8 else 2, head=8)


frames = []

# Phase 1: reveal nodes one by one with a small glow ramp
RAMP = 4  # frames per node transition
lit = [0.0] * N
arr = [0.0] * (N - 1)

def render():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    draw_base(d)
    # arrows first (under nodes)
    for i in range(N - 1):
        lane_arrow(d, i, arr[i])
    for i in range(N):
        draw_node(d, i, lit[i])
    return img, d

# intro: all dim
img, d = render()
frames.append(img.copy())

for i in range(N):
    # ramp arrow into node i (except first)
    for f in range(RAMP):
        t = (f + 1) / RAMP
        if i > 0:
            arr[i - 1] = t
        lit[i] = t
        img, d = render()
        frames.append(img.copy())
    # hold 1
    img, d = render()
    frames.append(img.copy())

# Phase 2: feedback loop Supervisor(8) -> Developer(5), gold arc above
def render_full(loop_t=0.0, branch_t=0.0):
    img, d = render()
    dev_cx, sup_cx = ncx(5), ncx(8)
    arc_y = LANE_Y - 56
    if loop_t > 0:
        # draw arc progressively: up, across, down
        col = GOLD
        # vertical up from supervisor
        d.line([sup_cx, LANE_Y, sup_cx, arc_y], fill=col, width=3)
        # horizontal (animated length)
        cur_x = sup_cx + (dev_cx - sup_cx) * min(1.0, loop_t)
        d.line([sup_cx, arc_y, cur_x, arc_y], fill=col, width=3)
        if loop_t >= 1.0:
            draw_arrow(d, dev_cx, arc_y, dev_cx, LANE_Y - 2, col, width=3, head=9)
            d.text((dev_cx - 30, arc_y - 28), "RUNNING → yeniden dene (en fazla 3 tur)",
                   font=fLbl, fill=GOLD)
    if branch_t > 0:
        # Integrator(9) -> END  and Supervisor abort -> END
        int_cx, sup_cx = ncx(9), ncx(8)
        end_x, end_y, ew, eh = int_cx - 55, 460, 110, 56
        # integrator down to END
        d.line([int_cx, LANE_Y + BH, int_cx, end_y], fill=MINT, width=3)
        draw_arrow(d, int_cx, end_y - 14, int_cx, end_y - 2, MINT, width=3, head=9)
        # abort supervisor -> END (down then right)
        d.line([sup_cx, LANE_Y + BH, sup_cx, end_y + 26], fill=CORAL, width=3)
        draw_arrow(d, sup_cx, end_y + 26, end_x - 2, end_y + 26, CORAL, width=3, head=9)
        # END pill
        rrect(d, [end_x, end_y, end_x + ew, end_y + eh], 12, fill=PANEL, outline=ICE, width=2)
        tb = d.textbbox((0, 0), "END", font=fLbl)
        d.text((end_x + ew / 2 - (tb[2] - tb[0]) / 2, end_y + eh / 2 - 11), "END", font=fLbl, fill=ICE)
    # legend (appears with branch)
    if branch_t > 0:
        lx, ly = 40, 420
        d.text((lx, ly), "SUPERVISOR KARARI", font=fLegB, fill=MINT)
        rows = [(MINT, "SUCCESS / uyarılı", "→ Integrator → END"),
                (GOLD, "RUNNING", "→ Developer'a dön (döngü)"),
                (CORAL, "iptal / max tur", "→ END")]
        for k, (c, a, b) in enumerate(rows):
            yy = ly + 30 + k * 26
            d.ellipse([lx, yy + 3, lx + 12, yy + 15], fill=c)
            d.text((lx + 22, yy), a, font=fLegB, fill=TEXT)
            w_a = d.textbbox((0, 0), a, font=fLegB)[2]
            d.text((lx + 28 + w_a, yy), b, font=fLeg, fill=MUTED)
    return img

# loop arc animation
for f in range(6):
    frames.append(render_full(loop_t=(f + 1) / 6))
# hold loop
for _ in range(3):
    frames.append(render_full(loop_t=1.0))
# branch + END appear
for f in range(5):
    frames.append(render_full(loop_t=1.0, branch_t=(f + 1) / 5))
# final hold
for _ in range(14):
    frames.append(render_full(loop_t=1.0, branch_t=1.0))

# durations: faster reveal, slower holds
durations = []
for idx, _ in enumerate(frames):
    durations.append(90)
durations[-14:] = [110] * 14  # final hold a touch slower

frames[0].save(
    "sunum/langgraph_flow.gif",
    save_all=True,
    append_images=frames[1:],
    duration=durations,
    loop=0,
    optimize=True,
    disposal=2,
)
print("WROTE sunum/langgraph_flow.gif frames:", len(frames))
