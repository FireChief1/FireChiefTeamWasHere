const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625
pres.author = "Erkut Ateş";
pres.title = "Yerel Çoklu-Agent Yazılım Geliştirme Takımı";

// ---- Palette (deep space) ----
const BG = "0A0E27";
const PANEL = "151B3D";
const CARD = "1C2349";
const ICE = "7AA2F7";   // primary accent
const MINT = "2DD4BF";  // secondary accent
const CORAL = "F7768E"; // highlight
const GOLD = "E0AF68";
const TEXT = "FFFFFF";
const MUTED = "A9B1D6";
const DIM = "6B73A6";

const HF = "Trebuchet MS"; // header font
const BF = "Calibri";       // body font
const MONO = "Consolas";

const W = 10, H = 5.625;
const FOOT = "Yerel Çoklu-Agent Yazılım Geliştirme Takımı";

const shadow = () => ({ type: "outer", color: "000000", blur: 8, offset: 3, angle: 135, opacity: 0.35 });

const STARS = [
  [0.6, 0.5, 0.03], [1.4, 1.2, 0.02], [2.3, 0.4, 0.025], [3.1, 1.6, 0.02],
  [4.0, 0.7, 0.03], [5.2, 0.3, 0.02], [6.1, 1.1, 0.025], [7.0, 0.5, 0.02],
  [8.2, 1.4, 0.03], [9.0, 0.6, 0.02], [9.4, 2.2, 0.025], [0.4, 2.8, 0.02],
  [8.7, 3.4, 0.03], [9.3, 4.6, 0.02], [0.7, 4.9, 0.025], [1.9, 5.1, 0.02],
  [3.4, 4.4, 0.02], [6.6, 5.0, 0.025], [7.8, 4.7, 0.02], [2.6, 2.9, 0.02],
];

let PAGE = 0;
function baseSlide(withStars = true, withFooter = true) {
  const s = pres.addSlide();
  s.background = { color: BG };
  if (withStars) {
    for (const [x, y, r] of STARS) {
      s.addShape(pres.shapes.OVAL, { x, y, w: r, h: r, fill: { color: "FFFFFF", transparency: 35 }, line: { type: "none" } });
    }
  }
  PAGE += 1;
  if (withFooter) {
    s.addText(FOOT, { x: 0.6, y: 5.32, w: 7.5, h: 0.25, fontFace: BF, fontSize: 8.5, color: DIM, margin: 0 });
    s.addText(String(PAGE), { x: 9.1, y: 5.3, w: 0.5, h: 0.27, fontFace: MONO, fontSize: 10, color: MUTED, align: "right", bold: true, margin: 0 });
  }
  return s;
}

function header(s, kicker, title) {
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.18, h: H, fill: { color: ICE }, line: { type: "none" } });
  s.addText(kicker.toUpperCase(), { x: 0.6, y: 0.3, w: 8.8, h: 0.3, fontFace: MONO, fontSize: 11, color: MINT, bold: true, charSpacing: 3, margin: 0 });
  s.addText(title, { x: 0.6, y: 0.58, w: 9.0, h: 0.66, fontFace: HF, fontSize: 29, color: TEXT, bold: true, margin: 0 });
}

function card(s, x, y, w, h, fill = CARD) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: "2A336B", width: 1 }, rectRadius: 0.08, shadow: shadow() });
}

// ============================================================
// SLIDE 1 — Title
// ============================================================
{
  const s = baseSlide(true, false);
  s.addShape(pres.shapes.OVAL, { x: 7.4, y: 2.3, w: 3.4, h: 3.4, fill: { color: ICE, transparency: 70 }, line: { type: "none" } });
  s.addShape(pres.shapes.OVAL, { x: 7.9, y: 2.8, w: 2.4, h: 2.4, fill: { color: MINT, transparency: 55 }, line: { type: "none" } });
  s.addShape(pres.shapes.OVAL, { x: 8.25, y: 3.15, w: 1.7, h: 1.7, fill: { color: "11183A" }, line: { color: ICE, width: 1.5 } });

  s.addText("BİTİRME PROJESİ", { x: 0.7, y: 1.2, w: 6, h: 0.35, fontFace: MONO, fontSize: 13, color: MINT, bold: true, charSpacing: 4, margin: 0 });
  s.addText("Yerel Çoklu-Agent\nYazılım Geliştirme Takımı", { x: 0.65, y: 1.6, w: 6.8, h: 1.6, fontFace: HF, fontSize: 38, color: TEXT, bold: true, lineSpacingMultiple: 0.95, margin: 0 });
  s.addText([
    { text: "Lokal modeller ve Claude ile çalışan,", options: { breakLine: true } },
    { text: "LangGraph tabanlı yapay zekâ geliştirici takımı", options: {} },
  ], { x: 0.7, y: 3.45, w: 6.5, h: 0.8, fontFace: BF, fontSize: 16, color: MUTED, margin: 0 });
  s.addText("Erkut Ateş", { x: 0.7, y: 4.8, w: 5, h: 0.35, fontFace: BF, fontSize: 14, color: ICE, bold: true, margin: 0 });

  const chips = ["LangGraph", "Ollama · Qwen2.5", "ChromaDB", "Postgres", "MCP", "React"];
  let cx = 0.7;
  for (const c of chips) {
    const cw = 0.32 + c.length * 0.085;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: cx, y: 5.15, w: cw, h: 0.32, fill: { color: PANEL }, line: { color: "2A336B", width: 1 }, rectRadius: 0.16 });
    s.addText(c, { x: cx, y: 5.15, w: cw, h: 0.32, fontFace: MONO, fontSize: 9, color: MUTED, align: "center", valign: "middle", margin: 0 });
    cx += cw + 0.12;
  }
}

// ============================================================
// SLIDE 2 — Problem & Thesis
// ============================================================
{
  const s = baseSlide();
  header(s, "Neden", "Problem ve Tezimiz");

  card(s, 0.6, 1.55, 4.25, 3.4, PANEL);
  s.addText("SORUN", { x: 0.85, y: 1.74, w: 3.8, h: 0.3, fontFace: MONO, fontSize: 11, color: CORAL, bold: true, charSpacing: 2, margin: 0 });
  s.addText([
    { text: "Tek bir AI çağrısı; plan, kod, gözden geçirme ve testi bir arada iyi yapamaz", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 12 } },
    { text: "Üretilen kod çoğu zaman doğrulanmadan teslim edilir", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 12 } },
    { text: "Görev türüne göre (Python, web, Node) farklı uzmanlık gerekir", options: { bullet: { code: "2022" } } },
  ], { x: 0.85, y: 2.14, w: 3.75, h: 2.7, fontFace: BF, fontSize: 14.5, color: MUTED, margin: 0 });

  card(s, 5.15, 1.55, 4.25, 3.4, CARD);
  s.addText("TEZİMİZ", { x: 5.4, y: 1.74, w: 3.8, h: 0.3, fontFace: MONO, fontSize: 11, color: MINT, bold: true, charSpacing: 2, margin: 0 });
  s.addText([
    { text: "Takım gibi", options: { bold: true, color: TEXT, breakLine: true, paraSpaceAfter: 8 } },
    { text: "uzman ajanlar bir hattı paylaşır", options: { color: MUTED, breakLine: true, paraSpaceAfter: 14 } },
    { text: "İki motor", options: { bold: true, color: TEXT, breakLine: true, paraSpaceAfter: 8 } },
    { text: "Lokal (Ollama) ve Claude — istek başına seçilir", options: { color: MUTED, breakLine: true, paraSpaceAfter: 14 } },
    { text: "Gerçekten çalışır", options: { bold: true, color: TEXT, breakLine: true, paraSpaceAfter: 8 } },
    { text: "üretilen kod test edilip öyle teslim edilir", options: { color: MUTED } },
  ], { x: 5.4, y: 2.14, w: 3.75, h: 2.7, fontFace: BF, fontSize: 15, margin: 0 });

  s.addText("“Gerçek bir yazılım takımı gibi — analist, geliştirici, gözden geçiren, test ve entegratör — hepsi tek bir akışta.”",
    { x: 0.6, y: 5.0, w: 8.8, h: 0.3, fontFace: BF, fontSize: 12, italic: true, color: ICE, align: "center", margin: 0 });
}

// ============================================================
// SLIDE 3 — Project in numbers (NEW, visual)
// ============================================================
{
  const s = baseSlide();
  header(s, "Bir Bakışta", "Rakamlarla Proje");

  const stats = [
    ["10", "düğümlü\nLangGraph hattı", ICE],
    ["15", "uzman\nAI ajanı", MINT],
    ["5", "dil / profil\ndesteği", GOLD],
    ["2", "motor\nLokal + Claude", CORAL],
    ["8", "MCP aracı\ndosya · git · test", ICE],
  ];
  const cw = 1.74, gx = 0.12, sx = 0.6, y = 1.7, ch = 2.05;
  stats.forEach((st, i) => {
    const x = sx + i * (cw + gx);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: ch, fill: { color: CARD }, line: { color: st[2], width: 1.25 }, rectRadius: 0.1, shadow: shadow() });
    s.addText(st[0], { x: x + 0.05, y: y + 0.28, w: cw - 0.1, h: 0.9, fontFace: HF, fontSize: 50, bold: true, color: st[2], align: "center", margin: 0 });
    s.addText(st[1], { x: x + 0.08, y: y + 1.25, w: cw - 0.16, h: 0.7, fontFace: BF, fontSize: 11.5, color: MUTED, align: "center", valign: "top", margin: 0 });
  });

  card(s, 0.6, 4.15, 8.8, 0.85, PANEL);
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 4.15, w: 0.1, h: 0.85, fill: { color: MINT }, line: { type: "none" } });
  s.addText([
    { text: "30+ hedefli iyileştirme ", options: { bold: true, color: TEXT } },
    { text: "tamamlandı — model dayanıklılığı, bağlam hijyeni, RAG kalitesi, LangGraph akışı, Node profili, dosya düzenleme, hibrit motor ve modern UI.", options: { color: MUTED } },
  ], { x: 0.9, y: 4.28, w: 8.35, h: 0.62, fontFace: BF, fontSize: 13.5, valign: "middle", margin: 0 });
}

// ============================================================
// SLIDE 4 — High level architecture
// ============================================================
{
  const s = baseSlide();
  header(s, "Genel Bakış", "Sistem Mimarisi");

  function layer(x, y, w, h, title, sub, fill, accent) {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: accent, width: 1.25 }, rectRadius: 0.07, shadow: shadow() });
    s.addText(title, { x: x + 0.15, y: y + 0.09, w: w - 0.3, h: 0.3, fontFace: HF, fontSize: 13.5, bold: true, color: TEXT, align: "center", margin: 0 });
    s.addText(sub, { x: x + 0.1, y: y + 0.4, w: w - 0.2, h: h - 0.48, fontFace: BF, fontSize: 10, color: MUTED, align: "center", valign: "top", margin: 0 });
  }

  layer(2.6, 1.42, 4.8, 0.72, "React Arayüzü (Vite + TS)", "Proje seçici · Lokal/Claude anahtarı · RAG anahtarı · sohbet", PANEL, ICE);
  s.addShape(pres.shapes.LINE, { x: 5, y: 2.14, w: 0, h: 0.26, line: { color: ICE, width: 2, endArrowType: "triangle" } });
  layer(2.6, 2.42, 4.8, 0.68, "Yerel HTTP API (stdlib)", "127.0.0.1 · framework yok · projeye özel istek yönetimi", PANEL, MINT);
  s.addShape(pres.shapes.LINE, { x: 5, y: 3.1, w: 0, h: 0.26, line: { color: MINT, width: 2, endArrowType: "triangle" } });
  layer(2.6, 3.38, 4.8, 0.82, "LangGraph Orkestratörü", "10 düğümlü StateGraph · deterministik Supervisor döngüsü", CARD, GOLD);

  layer(0.4, 3.32, 2.0, 0.94, "LLM Havuzu", "Yetenek-bazlı\nOllama + Claude", PANEL, CORAL);
  s.addShape(pres.shapes.LINE, { x: 2.4, y: 3.79, w: 0.2, h: 0, line: { color: CORAL, width: 2, endArrowType: "triangle" } });
  layer(7.6, 3.32, 2.0, 0.94, "RAG · MCP", "ChromaDB bilgi\nGüvenli araçlar", PANEL, MINT);
  s.addShape(pres.shapes.LINE, { x: 7.6, y: 3.79, w: -0.2, h: 0, line: { color: MINT, width: 2, endArrowType: "triangle" } });

  s.addShape(pres.shapes.LINE, { x: 5, y: 4.2, w: 0, h: 0.26, line: { color: GOLD, width: 2, endArrowType: "triangle" } });
  layer(2.6, 4.48, 4.8, 0.66, "Kalıcılık", "Postgres (zaman çizelgesi · checkpoint · hafıza)  +  ChromaDB (vektör)", PANEL, ICE);
}

// ============================================================
// SLIDE 5 — Agent pipeline
// ============================================================
{
  const s = baseSlide();
  header(s, "Çekirdek · Akış", "LangGraph Akış Diyagramı");

  const nodes = [
    ["1", "Intake", ICE],
    ["2", "Brief", ICE],
    ["3", "Classifier", MINT],
    ["4", "RAG", MINT],
    ["5", "Analyst", GOLD],
    ["6", "Developer", CORAL],
    ["7", "Reviewer", CORAL],
    ["8", "QA", MINT],
    ["9", "Supervisor", GOLD],
    ["10", "Integrator", ICE],
  ];
  const bw = 0.82, bh = 1.0, gap = 0.12, startX = 0.4, laneY = 2.55;
  const step = bw + gap;
  const cX = (i) => startX + i * step + bw / 2;
  const midY = laneY + bh / 2;

  // nodes
  nodes.forEach((n, i) => {
    const x = startX + i * step;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: laneY, w: bw, h: bh, fill: { color: CARD }, line: { color: n[2], width: 1.5 }, rectRadius: 0.08, shadow: shadow() });
    s.addShape(pres.shapes.OVAL, { x: cX(i) - 0.16, y: laneY + 0.13, w: 0.32, h: 0.32, fill: { color: n[2] }, line: { type: "none" } });
    s.addText(n[0], { x: cX(i) - 0.16, y: laneY + 0.13, w: 0.32, h: 0.32, fontFace: HF, fontSize: 11, bold: true, color: BG, align: "center", valign: "middle", margin: 0 });
    s.addText(n[1], { x: x + 0.02, y: laneY + 0.52, w: bw - 0.04, h: 0.42, fontFace: HF, fontSize: 9.5, bold: true, color: TEXT, align: "center", valign: "top", margin: 0 });
  });

  // linear arrows between nodes (i -> i+1); highlight Supervisor -> Integrator
  for (let i = 0; i < 9; i++) {
    const ax = startX + i * step + bw;
    const approved = i === 8; // Supervisor -> Integrator
    s.addShape(pres.shapes.LINE, { x: ax, y: midY, w: gap, h: 0, line: { color: approved ? MINT : DIM, width: approved ? 2 : 1.5, endArrowType: "triangle" } });
  }

  // feedback loop: Supervisor (9) -> Developer (6), arc above the lane
  const devCx = cX(5), supCx = cX(8), arcY = 2.05;
  s.addShape(pres.shapes.LINE, { x: supCx, y: arcY, w: 0, h: laneY - arcY, line: { color: GOLD, width: 1.75 } });
  s.addShape(pres.shapes.LINE, { x: devCx, y: arcY, w: supCx - devCx, h: 0, line: { color: GOLD, width: 1.75 } });
  s.addShape(pres.shapes.LINE, { x: devCx, y: arcY, w: 0, h: laneY - arcY, line: { color: GOLD, width: 1.75, endArrowType: "triangle" } });
  s.addText("Sorun var (RUNNING) → yeniden dene · en fazla 3 tur", { x: devCx - 0.6, y: 1.66, w: supCx - devCx + 1.2, h: 0.3, fontFace: BF, fontSize: 11, italic: true, color: GOLD, align: "center", margin: 0 });

  // Integrator -> END (down) + END pill
  const intCx = cX(9), endX = intCx - 0.45, endY = 4.18;
  s.addShape(pres.shapes.LINE, { x: intCx, y: laneY + bh, w: 0, h: endY - (laneY + bh), line: { color: MINT, width: 2, endArrowType: "triangle" } });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: endX, y: endY, w: 0.9, h: 0.5, fill: { color: PANEL }, line: { color: ICE, width: 1.5 }, rectRadius: 0.1, shadow: shadow() });
  s.addText("END", { x: endX, y: endY, w: 0.9, h: 0.5, fontFace: MONO, fontSize: 12, bold: true, color: ICE, align: "center", valign: "middle", margin: 0 });

  // abort path: Supervisor -> END (down then right)
  s.addShape(pres.shapes.LINE, { x: supCx, y: laneY + bh, w: 0, h: (endY + 0.25) - (laneY + bh), line: { color: CORAL, width: 1.75 } });
  s.addShape(pres.shapes.LINE, { x: supCx, y: endY + 0.25, w: endX - supCx, h: 0, line: { color: CORAL, width: 1.75, endArrowType: "triangle" } });

  // legend: supervisor's three conditional branches
  s.addText("SUPERVISOR KARARI  ·  koşullu kenar", { x: 0.5, y: 3.95, w: 6, h: 0.28, fontFace: MONO, fontSize: 10, bold: true, color: MINT, charSpacing: 1, margin: 0 });
  const legend = [
    [MINT, "SUCCESS / uyarılı", "→  Integrator → END"],
    [GOLD, "RUNNING", "→  Developer'a dön (döngü)"],
    [CORAL, "iptal / max tur", "→  END"],
  ];
  legend.forEach((lg, i) => {
    const y = 4.32 + i * 0.3;
    s.addShape(pres.shapes.OVAL, { x: 0.55, y: y + 0.03, w: 0.16, h: 0.16, fill: { color: lg[0] }, line: { type: "none" } });
    s.addText([
      { text: lg[1] + "  ", options: { bold: true, color: TEXT } },
      { text: lg[2], options: { color: MUTED } },
    ], { x: 0.82, y: y - 0.04, w: 5.3, h: 0.3, fontFace: BF, fontSize: 11.5, valign: "middle", margin: 0 });
  });
}

// ============================================================
// SLIDE 6 — Deterministic Supervisor
// ============================================================
{
  const s = baseSlide();
  header(s, "Kontrol", "Deterministik Supervisor");
  s.addText("LLM değil — kural tabanlı bir karar düğümü. Sonsuz döngüyü ve maliyeti önler.",
    { x: 0.6, y: 1.45, w: 8.8, h: 0.35, fontFace: BF, fontSize: 15, color: MUTED, margin: 0 });

  const items = [
    ["Sadece kritik sayar", "Yalnızca BLOCKER + MAJOR bulguları engel sayar; küçük uyarılar akışı durdurmaz.", CORAL],
    ["İlerleme takibi", "Sorun sayısı azalmıyorsa (salınım) durur — boşa tur harcamaz.", GOLD],
    ["En iyi denemeyi korur", "Turlar arasında en iyi kod sürümünü saklar; kötüye gitmez.", MINT],
    ["Testler geçtiyse teslim", "Reviewer uyarısı kalsa da testler yeşilse “uyarılarla tamamlandı” olur.", ICE],
  ];
  const cw = 4.25, ch = 1.4, gx = 0.3, gy = 0.3, sx = 0.6, sy = 2.0;
  items.forEach((it, i) => {
    const x = sx + (i % 2) * (cw + gx);
    const y = sy + Math.floor(i / 2) * (ch + gy);
    card(s, x, y, cw, ch);
    s.addShape(pres.shapes.RECTANGLE, { x, y: y + 0.12, w: 0.08, h: ch - 0.24, fill: { color: it[2] }, line: { type: "none" } });
    s.addText(it[0], { x: x + 0.28, y: y + 0.16, w: cw - 0.5, h: 0.4, fontFace: HF, fontSize: 16, bold: true, color: TEXT, margin: 0 });
    s.addText(it[1], { x: x + 0.28, y: y + 0.58, w: cw - 0.5, h: 0.7, fontFace: BF, fontSize: 12.5, color: MUTED, margin: 0 });
  });
}

// ============================================================
// SLIDE 7 — LLM Pool
// ============================================================
{
  const s = baseSlide();
  header(s, "Beyin", "Yetenek-Bazlı LLM Havuzu");

  const caps = [
    ["CHAT", "Sohbet / yönlendirme", "qwen2.5:14b"],
    ["CODER", "Kod üretimi", "qwen2.5-coder:14b"],
    ["REASONER", "Derin analiz", "qwen2.5-coder:14b"],
    ["VISION", "Görsel anlama", "qwen2.5vl:7b"],
    ["FALLBACK", "Acil yedek", "qwen2.5:14b"],
  ];
  const cw = 1.74, gx = 0.12, sx = 0.6, y = 1.5;
  caps.forEach((c, i) => {
    const x = sx + i * (cw + gx);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: 1.25, fill: { color: CARD }, line: { color: ICE, width: 1 }, rectRadius: 0.08, shadow: shadow() });
    s.addText(c[0], { x: x + 0.1, y: y + 0.12, w: cw - 0.2, h: 0.32, fontFace: MONO, fontSize: 12.5, bold: true, color: MINT, align: "center", margin: 0 });
    s.addText(c[1], { x: x + 0.08, y: y + 0.46, w: cw - 0.16, h: 0.42, fontFace: BF, fontSize: 11, color: MUTED, align: "center", margin: 0 });
    s.addText(c[2], { x: x + 0.06, y: y + 0.92, w: cw - 0.12, h: 0.28, fontFace: MONO, fontSize: 8.5, color: MUTED, align: "center", margin: 0 });
  });

  card(s, 0.6, 3.0, 4.25, 1.5, CARD);
  s.addText("YEREL (Varsayılan)", { x: 0.85, y: 3.14, w: 3.8, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: MINT, margin: 0 });
  s.addText([
    { text: "Ollama · Qwen2.5 ailesi", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 6 } },
    { text: "Tamamen yerelde çalışır", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 6 } },
    { text: "code_backend = \"ollama\"", options: { bullet: { code: "2022" } } },
  ], { x: 0.85, y: 3.48, w: 3.75, h: 1.0, fontFace: BF, fontSize: 13, color: MUTED, margin: 0 });

  card(s, 5.15, 3.0, 4.25, 1.5, CARD);
  s.addText("CLAUDE (Opsiyonel)", { x: 5.4, y: 3.14, w: 3.8, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: GOLD, margin: 0 });
  s.addText([
    { text: "claude-sonnet-4-6 — yüksek kalite", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 6 } },
    { text: "Arayüzden istek başına seçilir", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 6 } },
    { text: "API anahtarı yoksa otomatik kapalı", options: { bullet: { code: "2022" } } },
  ], { x: 5.4, y: 3.48, w: 3.75, h: 1.0, fontFace: BF, fontSize: 13, color: MUTED, margin: 0 });

  s.addText([
    { text: "Dayanıklılık: ", options: { bold: true, color: ICE } },
    { text: "devre kesici (circuit breaker) · yeniden deneme · sağlık kontrolü · tek seferlik ısıtma", options: { color: MUTED } },
  ], { x: 0.6, y: 4.68, w: 8.8, h: 0.35, fontFace: BF, fontSize: 12.5, align: "center", margin: 0 });
}

// ============================================================
// SLIDE 8 — RAG
// ============================================================
{
  const s = baseSlide();
  header(s, "Bilgi", "RAG — Bağlamla Beslenen Üretim");

  card(s, 0.6, 1.55, 4.4, 3.45, PANEL);
  s.addText("NASIL ÇALIŞIR", { x: 0.85, y: 1.72, w: 4, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: MINT, margin: 0 });
  const flow = [
    ["Belgeler", "docs/ → 500 token'lık parçalar"],
    ["Gömme (embed)", "nomic-embed-text · asimetrik önekler"],
    ["ChromaDB", "kalıcı vektör deposu · cosine uzaklık"],
    ["İlgi filtresi", "uzaklık > 0.6 olan parçalar elenir"],
    ["Profil filtresi", "profile göre kaynak seçimi"],
  ];
  flow.forEach((f, i) => {
    const y = 2.14 + i * 0.55;
    s.addShape(pres.shapes.OVAL, { x: 0.9, y: y + 0.02, w: 0.26, h: 0.26, fill: { color: ICE }, line: { type: "none" } });
    s.addText(String(i + 1), { x: 0.9, y: y + 0.02, w: 0.26, h: 0.26, fontFace: HF, fontSize: 10, bold: true, color: BG, align: "center", valign: "middle", margin: 0 });
    s.addText([
      { text: f[0] + "  ", options: { bold: true, color: TEXT } },
      { text: f[1], options: { color: MUTED } },
    ], { x: 1.28, y: y - 0.04, w: 3.6, h: 0.4, fontFace: BF, fontSize: 12, valign: "middle", margin: 0 });
  });

  card(s, 5.25, 1.55, 4.15, 1.62, CARD);
  s.addText("İki Koleksiyon", { x: 5.5, y: 1.7, w: 3.7, h: 0.3, fontFace: HF, fontSize: 15, bold: true, color: TEXT, margin: 0 });
  s.addText([
    { text: "knowledge — ", options: { bold: true, color: ICE } },
    { text: "kodlama standartları, mimari, güvenlik", options: { color: MUTED, breakLine: true, paraSpaceAfter: 6 } },
    { text: "project_memory — ", options: { bold: true, color: MINT } },
    { text: "projeye özel anlamsal hafıza (maks 200 parça)", options: { color: MUTED } },
  ], { x: 5.5, y: 2.1, w: 3.65, h: 1.0, fontFace: BF, fontSize: 12.5, margin: 0 });

  card(s, 5.25, 3.38, 4.15, 1.62, CARD);
  s.addText("Güvenli Tasarım", { x: 5.5, y: 3.53, w: 3.7, h: 0.3, fontFace: HF, fontSize: 15, bold: true, color: TEXT, margin: 0 });
  s.addText([
    { text: "Sürümlü indeks — model değişince güvenli", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 5 } },
    { text: "Bilgi yoksa zarif düşüş, akış sürer", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 5 } },
    { text: "Gürültülü sohbet parçaları indekslenmez", options: { bullet: { code: "2022" } } },
  ], { x: 5.5, y: 3.88, w: 3.65, h: 1.05, fontFace: BF, fontSize: 11, color: MUTED, margin: 0 });
}

// ============================================================
// SLIDE 9 — MCP & Security
// ============================================================
{
  const s = baseSlide();
  header(s, "Eylem", "MCP Çalışma Alanı ve Güvenlik");
  s.addText("LLM dosya sistemine doğrudan dokunmaz — her şey sınırlandırılmış MCP araçlarından geçer.",
    { x: 0.6, y: 1.45, w: 8.8, h: 0.35, fontFace: BF, fontSize: 15, color: MUTED, margin: 0 });

  const tools = ["write_file", "read_file", "list_files", "search_text", "git_status", "git_diff", "run_pytest", "run_node_tests"];
  const bw = 2.05, bh = 0.62, gx = 0.18, gy = 0.18, sx = 0.6, sy = 2.0;
  tools.forEach((t, i) => {
    const x = sx + (i % 4) * (bw + gx);
    const y = sy + Math.floor(i / 4) * (bh + gy);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: bw, h: bh, fill: { color: CARD }, line: { color: "2A336B", width: 1 }, rectRadius: 0.06 });
    s.addText(t + "()", { x, y, w: bw, h: bh, fontFace: MONO, fontSize: 12.5, color: ICE, align: "center", valign: "middle", margin: 0 });
  });

  card(s, 0.6, 3.8, 8.8, 1.25, PANEL);
  s.addText("GÜVENLİK SINIRLARI", { x: 0.85, y: 3.94, w: 8, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: CORAL, margin: 0 });
  s.addText([
    { text: "Tüm yollar çalışma kökü içinde — dizin dışına çıkış yok", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 4 } },
    { text: "Sadece pytest / node test çalıştırılabilir — keyfi komut yok · her teste zaman aşımı", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 4 } },
    { text: "Üretilen kod önce önizlenir, kullanıcı onaylayınca uygulanır (apply token)", options: { bullet: { code: "2022" } } },
  ], { x: 0.85, y: 4.28, w: 8.4, h: 0.72, fontFace: BF, fontSize: 12.5, color: MUTED, margin: 0 });
}

// ============================================================
// SLIDE 10 — Routing / profiles
// ============================================================
{
  const s = baseSlide();
  header(s, "Esneklik", "Akıllı Yönlendirme · 5 Profil");

  const profs = [
    ["python", "Python kodu + pytest", ICE],
    ["static_web", "HTML / CSS / JS sayfalar", MINT],
    ["node_js", "Node.js + node:test", GOLD],
    ["docs", "Dokümantasyon / Markdown", CORAL],
    ["project", "Proje analizi / refactor", ICE],
  ];
  const cw = 1.74, gx = 0.12, sx = 0.6, y = 1.5;
  profs.forEach((p, i) => {
    const x = sx + i * (cw + gx);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: 1.15, fill: { color: CARD }, line: { color: p[2], width: 1.25 }, rectRadius: 0.08, shadow: shadow() });
    s.addText(p[0], { x: x + 0.06, y: y + 0.18, w: cw - 0.12, h: 0.4, fontFace: MONO, fontSize: 12.5, bold: true, color: p[2], align: "center", margin: 0 });
    s.addText(p[1], { x: x + 0.08, y: y + 0.58, w: cw - 0.16, h: 0.5, fontFace: BF, fontSize: 10.5, color: MUTED, align: "center", margin: 0 });
  });

  card(s, 0.6, 2.95, 4.25, 2.05, PANEL);
  s.addText("2-AŞAMALI SINIFLANDIRICI", { x: 0.85, y: 3.1, w: 3.9, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: MINT, margin: 0 });
  s.addText([
    { text: "Aşama 1 — Dil ekseni: ", options: { bold: true, color: TEXT } },
    { text: "dil adı verilirse profile eşlenir", options: { color: MUTED, breakLine: true, paraSpaceAfter: 6 } },
    { text: "Aşama 2 — Anahtar kelime: ", options: { bold: true, color: TEXT } },
    { text: "dil yoksa içerik sinyaline bakılır", options: { color: MUTED, breakLine: true, paraSpaceAfter: 6 } },
    { text: "Öncelik: ", options: { bold: true, color: GOLD } },
    { text: "açık web sinyali yanlış dili ezer", options: { color: MUTED } },
  ], { x: 0.85, y: 3.42, w: 3.8, h: 1.55, fontFace: BF, fontSize: 11.5, margin: 0 });

  card(s, 5.15, 2.95, 4.25, 2.05, CARD);
  s.addText("ÇOK DİLLİ + DÜZENLEME", { x: 5.4, y: 3.1, w: 3.9, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: GOLD, margin: 0 });
  s.addText([
    { text: "Türkçe ve İngilizce komutları anlar", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 6 } },
    { text: "Sıfırdan dosya üretebilir", options: { bullet: { code: "2022" }, breakLine: true, paraSpaceAfter: 6 } },
    { text: "Var olan dosyaları düzenleyebilir (tam içerik)", options: { bullet: { code: "2022" } } },
  ], { x: 5.4, y: 3.42, w: 3.8, h: 1.55, fontFace: BF, fontSize: 11.5, color: MUTED, margin: 0 });
}

// ============================================================
// SLIDE 11 — Persistence & context hygiene
// ============================================================
{
  const s = baseSlide();
  header(s, "Hafıza", "Kalıcılık ve Bağlam Hijyeni");

  const cols = [
    ["Zaman Çizelgesi", "Her proje için olay kaydı (sohbet, eylem). Projeye göre ayrılır.", ICE],
    ["Checkpoint'ler", "Görev başına kod + test sonucu. Proje başına son 20 saklanır.", MINT],
    ["Anlamsal Hafıza", "Özetlenmiş bağlam. Maks 200 parça, önem-bazlı budama.", GOLD],
  ];
  const cw = 2.85, gx = 0.13, sx = 0.6, sy = 1.55, ch = 1.85;
  cols.forEach((c, i) => {
    const x = sx + i * (cw + gx);
    card(s, x, sy, cw, ch);
    s.addShape(pres.shapes.RECTANGLE, { x, y: sy, w: cw, h: 0.1, fill: { color: c[2] }, line: { type: "none" } });
    s.addText(c[0], { x: x + 0.2, y: sy + 0.26, w: cw - 0.4, h: 0.45, fontFace: HF, fontSize: 16, bold: true, color: TEXT, margin: 0 });
    s.addText(c[1], { x: x + 0.2, y: sy + 0.78, w: cw - 0.4, h: 0.95, fontFace: BF, fontSize: 12.5, color: MUTED, margin: 0 });
  });

  card(s, 0.6, 3.65, 8.8, 1.4, PANEL);
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 3.65, w: 0.1, h: 1.4, fill: { color: CORAL }, line: { type: "none" } });
  s.addText("PROJELER ARASI İZOLASYON", { x: 0.9, y: 3.8, w: 8, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: CORAL, margin: 0 });
  s.addText([
    { text: "Her sorgu WHERE p.path ile projeye filtrelenir — bir projenin bağlamı başka projeye karışmaz. ", options: { color: MUTED } },
    { text: "Hem ekranda hem model bağlamında doğrulandı.", options: { color: TEXT, bold: true } },
  ], { x: 0.9, y: 4.15, w: 8.3, h: 0.85, fontFace: BF, fontSize: 14, margin: 0 });
}

// ============================================================
// SLIDE 12 — What we built (NEW, explicit accomplishments)
// ============================================================
{
  const s = baseSlide();
  header(s, "Emeğimiz", "Neler Geliştirdik");

  const items = [
    ["Çoklu-Agent Hattı", "10 düğüm · 15 ajan · 5 profil (Python / Web / Node.js / Docs / Proje)", ICE],
    ["Kod Üretimi + Düzenleme", "Sıfırdan dosya üretimi ve var-olan dosyayı tam-içerik düzenleme", MINT],
    ["Gerçek Test Çalıştırma", "pytest ve node:test sandbox'ta koşar; en iyi deneme korunur", GOLD],
    ["Bağlam Hijyeni & Hafıza", "Projeye özel hafıza, budama/cap, projeler arası izolasyon (M1–M6)", CORAL],
    ["RAG Kalitesi", "Cosine + ilgi eşiği + embed önekleri + sürüm koruması (R1–R6)", ICE],
    ["Dayanıklı LLM Havuzu", "Devre kesici · gerçek fallback · seed · bağlam penceresi (8 düzeltme)", MINT],
    ["Hibrit Motor", "İstek başına Lokal (Ollama) ↔ Claude geçişi", GOLD],
    ["Modern Uzay Temalı UI", "Responsive · tema anahtarı · canlı sayaç · proje gezgini", CORAL],
  ];
  const cw = 4.3, ch = 0.82, gx = 0.2, gy = 0.16, sx = 0.6, sy = 1.5;
  items.forEach((it, i) => {
    const x = sx + (i % 2) * (cw + gx);
    const y = sy + Math.floor(i / 2) * (ch + gy);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: ch, fill: { color: CARD }, line: { color: "2A336B", width: 1 }, rectRadius: 0.07, shadow: shadow() });
    s.addShape(pres.shapes.OVAL, { x: x + 0.16, y: y + 0.27, w: 0.28, h: 0.28, fill: { color: it[2] }, line: { type: "none" } });
    s.addText("✓", { x: x + 0.16, y: y + 0.27, w: 0.28, h: 0.28, fontFace: HF, fontSize: 12, bold: true, color: BG, align: "center", valign: "middle", margin: 0 });
    s.addText(it[0], { x: x + 0.56, y: y + 0.1, w: cw - 0.7, h: 0.32, fontFace: HF, fontSize: 13.5, bold: true, color: TEXT, margin: 0 });
    s.addText(it[1], { x: x + 0.56, y: y + 0.42, w: cw - 0.7, h: 0.36, fontFace: BF, fontSize: 10.5, color: MUTED, margin: 0 });
  });
}

// ============================================================
// SLIDE 13 — Closing + Demo
// ============================================================
{
  const s = baseSlide(true, false);
  s.addShape(pres.shapes.OVAL, { x: -2.6, y: 3.7, w: 3.0, h: 3.0, fill: { color: ICE, transparency: 78 }, line: { type: "none" } });
  s.addShape(pres.shapes.OVAL, { x: -2.3, y: 4.05, w: 2.2, h: 2.2, fill: { color: MINT, transparency: 65 }, line: { type: "none" } });

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.18, h: H, fill: { color: ICE }, line: { type: "none" } });
  s.addText("KAPANIŞ", { x: 0.6, y: 0.5, w: 8.8, h: 0.3, fontFace: MONO, fontSize: 12, color: MINT, bold: true, charSpacing: 3, margin: 0 });
  s.addText("Özetle", { x: 0.6, y: 0.8, w: 9, h: 0.65, fontFace: HF, fontSize: 29, color: TEXT, bold: true, margin: 0 });

  const points = [
    ["Çoklu-agent yazılım takımı", "10 düğümlü LangGraph hattı, deterministik supervisor"],
    ["İki motor seçeneği", "Lokal (Ollama) ve Claude — istek başına seçilir"],
    ["Gerçekten çalışan kod", "pytest / node:test ile doğrulama + dosya düzenleme"],
    ["Güvenli ve dayanıklı", "MCP sandbox, devre kesici, projeye özel hafıza"],
  ];
  points.forEach((p, i) => {
    const y = 1.6 + i * 0.72;
    s.addShape(pres.shapes.OVAL, { x: 0.7, y: y + 0.04, w: 0.3, h: 0.3, fill: { color: MINT }, line: { type: "none" } });
    s.addText("✓", { x: 0.7, y: y + 0.04, w: 0.3, h: 0.3, fontFace: HF, fontSize: 13, bold: true, color: BG, align: "center", valign: "middle", margin: 0 });
    s.addText([
      { text: p[0] + "  —  ", options: { bold: true, color: TEXT } },
      { text: p[1], options: { color: MUTED } },
    ], { x: 1.15, y: y, w: 8.2, h: 0.45, fontFace: BF, fontSize: 14.5, valign: "middle", margin: 0 });
  });

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 4.7, w: 4.4, h: 0.6, fill: { color: MINT }, line: { type: "none" }, shadow: shadow() });
  s.addText("CANLI DEMO  →", { x: 0.6, y: 4.7, w: 4.4, h: 0.6, fontFace: HF, fontSize: 18, bold: true, color: BG, align: "center", valign: "middle", margin: 0 });
  s.addText("Teşekkürler", { x: 5.2, y: 4.7, w: 4.2, h: 0.6, fontFace: HF, fontSize: 18, bold: true, color: ICE, align: "right", valign: "middle", margin: 0 });
}

pres.writeFile({ fileName: "sunum/CodeTeam_Sunum.pptx" }).then((f) => console.log("WROTE", f, "pages:", PAGE));
