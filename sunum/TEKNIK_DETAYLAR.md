# Yerel Çoklu-Agent Yazılım Geliştirme Takımı — Teknik Detaylar

## 1. Özet
Bu proje, kod yazma sürecini tek bir LLM çağrısına yıkmak yerine, her biri tek bir işte
uzmanlaşmış **birden çok yapay zekâ ajanını** bir hat (pipeline) üzerinde çalıştıran bir
sistemdir. Akış **LangGraph** ile orkestre edilir; modeller varsayılan olarak **yerelde
Ollama/Qwen2.5** üzerinde, istenirse istek başına **Claude (claude-sonnet-4-6)** üzerinde
çalışır. Bilgi getirimi için **ChromaDB tabanlı RAG**, kalıcılık için **Postgres**, dosya ve
test işlemleri için **MCP** kullanılır. Arayüz **React + TypeScript + Vite** ile yazılmıştır.

---

## 2. Mimari Katmanlar
```
React Arayüzü (Vite + TS)
        ↓
Yerel HTTP API (Python stdlib, 127.0.0.1:8765)
        ↓
LangGraph Orkestratörü (10 düğümlü StateGraph)
   ├── LLM Havuzu (yetenek-bazlı; Ollama + opsiyonel Claude)
   ├── RAG (ChromaDB)
   └── MCP Çalışma Alanı (dosya/git/test araçları)
        ↓
Kalıcılık: Postgres (yapısal) + ChromaDB (vektör)
```
API katmanı bilinçli olarak web framework içermez — yerel geliştirme API'sidir, her istek
kendi `asyncio.run()` döngüsünde çalışır; LLM havuzu süreç-genelinde **tek sefer** ısıtılır.

---

## 3. Çoklu-Agent Hattı (LangGraph)
`StateGraph` üzerinde doğrusal düğüm sırası:

`project_intake → project_brief → task_classifier → rag → analyst → developer →
reviewer → qa → supervisor → integrator`

**Koşullu kenar** yalnızca Supervisor'dadır:
- `SUCCESS` / `COMPLETED_WITH_WARNINGS` → `integrator`
- `RUNNING` → `developer` (geri-besleme döngüsü)
- `should_abort` / aksi → `END`
- `integrator → END`

### Ajanlar (15 sınıf)
Hepsi `BaseAgent` soyut sınıfından türer; her biri kendi **system prompt (persona)**,
**kullanıcı mesajı kurucusu** ve **yapısal çıktı şemasını** tanımlar.
- **Çekirdek (6):** Analyst (plan), Developer (Python kod), Reviewer (gözden geçirme),
  QA (pytest), ProjectChatRouter (niyet/dil yönlendirme), ProjectChatResponder (yanıt).
- **static_web (2):** StaticWebDeveloper, StaticWebReviewer.
- **node_js (3):** JavaScriptDeveloper, JavaScriptReviewer, JavaScriptQA (`node:test`).
- **docs (2):** DocsAdvisor, DocsAdvisorReviewer.
- **project (2):** ProjectAdvisor (kod yazmaz, danışman), ProjectAdvisorReviewer.

Profil ajanları çekirdek ajanlardan **kalıtımla** gelir; sadece persona/doğrulama farklıdır.

---

## 4. Deterministik Supervisor
Supervisor bir LLM değil, **kural tabanlı bir karar düğümüdür**. Sonsuz döngüyü ve gereksiz
maliyeti engeller:
- Yalnızca **BLOCKER + MAJOR** bulguları engel sayar; küçük uyarılar akışı durdurmaz.
- **İlerleme takibi:** sorun sayısı azalmıyorsa (salınım) durur.
- Turlar arasında **en iyi kod sürümünü saklar**.
- Testler geçtiyse, reviewer uyarısı kalsa bile `COMPLETED_WITH_WARNINGS` ile teslim eder.
- Tur sayısı `max_iterations` (varsayılan 3) ile sınırlıdır; recursion limit buradan türetilir.

---

## 5. LLM Havuzu
Yetenek-bazlı (capability) bir yönlendirme havuzudur:

| Yetenek | Model (yerel) | Kullanım |
|---------|---------------|----------|
| CHAT | qwen2.5:14b | sohbet / yönlendirme |
| CODER | qwen2.5-coder:14b | kod üretimi |
| REASONER | qwen2.5-coder:14b | derin analiz |
| VISION | qwen2.5vl:7b | görsel anlama |
| FALLBACK | qwen2.5:14b | bağımsız acil yedek |

- **Çift backend:** `code_backend` "ollama" (varsayılan) veya "anthropic". Anahtar varsa
  CODER/REASONER için `claude-coder` / `claude-reasoner` düğümleri eklenir. CHAT/VISION/
  FALLBACK her zaman yerel kalır.
- **İstek başına seçim:** Arayüzden gelen `prefer_backend` `pick_node`'a iletilir — yalnızca
  *hangi modelin* çağrıyı aldığını değiştirir, **grafiği/QA/RAG'i değiştirmez**.
- **Dayanıklılık:** devre kesici (circuit breaker, eşik 3), yeniden deneme (max 3),
  periyodik sağlık kontrolü (15 sn, kısıtlı), başlangıçta tek seferlik ısıtma.
- **Tekrarlanabilirlik:** `num_ctx=8192`, `num_predict=4096`, `seed=0` (router/reviewer için).

---

## 6. RAG (ChromaDB)
- Kaynak: `docs/` klasörü → **500 token** parça (50 token örtüşme).
- Gömme: **nomic-embed-text**, asimetrik önekler (`search_document:` / `search_query:`).
- Depo: **ChromaDB**, **cosine** uzaklık, kalıcı.
- İlgi eşiği: `rag_max_distance = 0.6` üstü parçalar elenir; `rag_top_k = 5`.
- **Profil filtresi:** her profile uygun kaynak kümesi seçilir.
- **Sürümlü indeks** (`RAG_INDEX_VERSION`): model değişince eski indeks geçersiz sayılır.
- Bilgi yoksa **zarif düşüş** — akış RAG'siz devam eder.
- İki koleksiyon: `knowledge` (genel bilgi) ve `project_memory` (projeye özel vektörler).

---

## 7. MCP Çalışma Alanı ve Güvenlik
LLM dosya sistemine doğrudan dokunmaz; tüm işlemler stdio MCP sunucusundaki sınırlı
araçlardan geçer:
`write_file, read_file, list_files, search_text, git_status, git_diff, run_pytest, run_node_tests`
- Tüm yollar **çalışma kökü** (workspace root) içine sınırlıdır — dizin dışına çıkış yok.
- Yalnızca **pytest / node test** çalıştırılabilir, keyfi komut yok; her teste **zaman aşımı**.
- Üretilen kod önce **önizlenir**, kullanıcı onaylayınca (apply token) uygulanır.

---

## 8. Akıllı Yönlendirme ve Profiller
5 profil: `python`, `static_web`, `node_js`, `docs`, `project`.

**2-aşamalı sınıflandırıcı:**
1. **Dil ekseni:** sohbet bir dil adı verirse profile eşlenir (js/ts/node → node_js, html/css →
   static_web, python → python).
2. **Anahtar kelime:** dil yoksa içerik sinyallerine bakılır.
- **Öncelik kuralı:** açık web sinyali, yanlış router dil tahminini ezer.
- Türkçe karakter normalizasyonu ile Türkçe/İngilizce komutları anlar.
- Hem **sıfırdan üretim** hem **var-olan dosyayı tam-içerik düzenleme** destekler.

---

## 9. Kalıcılık
**Postgres** (yapısal):
- `projects` (proje kaydı; maks 30), `project_checkpoints` (görev başına kod+test; proje başına
  son 20), `project_timeline_events` (olay kaydı), `project_memory_chunks` (hafıza metni +
  metadata; maks 200, önem-bazlı budama).
- **Projeler arası izolasyon:** her sorgu `WHERE p.path` ile filtrelenir — bağlam karışmaz.

**ChromaDB** (vektör): RAG bilgi vektörleri ve proje hafızasının arama vektörleri.
> Not: RAG belgeleri Postgres'te değil, ChromaDB'dedir. Postgres yapısal veriyi tutar.

---

## 10. Arayüz (Frontend)
- **React 19 + TypeScript + Vite** (güvenlik odaklı, ek bağımlılık yok).
- Proje seçici/dosya gezgini, **Lokal/Claude motor anahtarı** (istek başına, localStorage'da
  kalıcı), **RAG anahtarı**, max iterasyon kaydırıcısı, görsel ekleme.
- Uzay temalı koyu + açık tema, canlı geçen-süre sayacı, checkpoint/timeline gezintisi.
- Proje değişiminde durum temizliği + `activeProjectRef` guard ile geç gelen yanıtın yeni
  projeyi ezmesi engellenir.

---

## 11. Teknoloji Yığını
LangGraph · LangChain · Ollama (Qwen2.5 ailesi) · opsiyonel Anthropic Claude · ChromaDB ·
nomic-embed-text · PostgreSQL · MCP (Model Context Protocol) · React 19 · TypeScript · Vite ·
Python (pydantic-settings, httpx) · pytest · Node.js (`node:test`).

---

## 12. Öne Çıkan Mühendislik Kararları
- **Çoklu-agent + deterministik supervisor:** üretkenliği LLM'e, kontrolü kurallara bıraktık.
- **Yetenek-bazlı havuz + çift backend:** aynı akış, takılabilir "beyin" (yerel ↔ Claude).
- **Bağlam hijyeni:** hafıza budama/cap, gürültülü sohbet parçalarını indekslememe, projeler
  arası katı izolasyon.
- **Gerçek doğrulama:** üretilen kod sandbox'ta gerçekten test edilir; geçmezse tekrar denenir.
- **Güvenli varsayılanlar:** yerel-öncelikli, sınırlı MCP araçları, önizle-sonra-uygula akışı.
