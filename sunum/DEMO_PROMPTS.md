# 🎬 Demo Senaryosu ve Promptlar (10 dk)

> **Altın kural:** Canlı demoda **Claude** motorunu seç (hızlı, ~10–20 sn). Yerel model yavaş (~1–3 dk) — onu sadece "Lokal motor da var" demek için 1 kez aç.
> **Hazırlık (sunumdan önce):** API + Vite + Ollama + Postgres ayakta · tarayıcıda UI açık · boş bir `demo` klasörü hazır · motor = Claude · RAG açık.

---

## ⏱️ Akış (her adımda ne söyleyeceğin)

### 1) Tam hat — Python (≈2 dk)  → *pipeline'ın tamamını gösterir*
**Prompt (chat'e yapıştır):**
```
Bir banka hesabı sınıfı yaz: para yatırma, çekme ve bakiye sorgulama olsun.
Negatif bakiyeye düşmeyi engelle. pytest ile testlerini de yaz.
```
**Göster:** Sağda akış ilerlerken profil rozeti `python` → Developer kod yazıyor → Reviewer bulguları → **QA testleri gerçekten çalıştırıyor** (yeşil) → Supervisor onay → önizleme. Sonra **"Uygula"** butonuna bas.

---

### 2) Akıllı yönlendirme — Web (≈1.5 dk)  → *aynı sistem, farklı profil*
**Prompt:**
```
Uzay temalı, koyu arka planlı modern bir açılış sayfası (index.html) yap.
Başlık, kısa açıklama ve bir "Keşfet" butonu olsun. CSS dahil tek dosya.
```
**Göster:** Profil rozeti otomatik `static_web` oldu — "ben söylemedim, sınıflandırıcı dilden anladı." Üretilen sayfayı tarayıcıda aç.

---

### 3) Gerçek test çalıştırma — Node.js (≈1.5 dk)  → *Python'a özel değil*
**Prompt:**
```
Node.js ile bir "isPalindrome" fonksiyonu yaz ve node:test ile testlerini ekle.
```
**Göster:** Profil `node_js` · QA `node --test` ile gerçekten koşuyor. "Sandbox MCP araçlarıyla, sadece test komutları çalışıyor — keyfi komut yok."

---

### 4) Var olan dosyayı düzenleme (≈1.5 dk)  → *sıfırdan değil, düzenleme*
**Prompt (1. adımdaki index.html üstünde):**
```
index.html'deki "Keşfet" butonunun rengini turkuaz yap ve sayfanın altına
küçük bir telif (footer) satırı ekle. Geri kalan içeriğe dokunma.
```
**Göster:** Sadece istenen değişiklik yapıldı, içerik korundu (full-content edit). "Tam içerik güncelleme + apply token ile güvenli."

---

### 5) Lokal ↔ Claude motor geçişi (≈1.5 dk)  → *projenin kalbi*
- Motoru **Yerel (Ollama)**'ya çevir, basit bir prompt at:
```
Python'da iki sayının en büyük ortak bölenini bulan bir fonksiyon yaz.
```
**Söyle:** "Aynı sistemde iki motor var: Lokal (Ollama) ve Claude. İstek başına arayüzden seçiliyor — kalite gerekince Claude, hızlı denemelerde Lokal."

---

### 6) (Varsa zaman) Proje analizi (≈1 dk)  → *project profili*
**Prompt:**
```
Bu projenin mimarisini incele ve geliştirilebilecek 3 nokta öner.
```
**Göster:** Profil `project` — kod yazmaz, **danışman** olarak öneri verir.

---

## 🗣️ Kapanış cümlesi
> "Gerçek bir yazılım takımı gibi — analist, geliştirici, gözden geçiren, test ve entegratör — tek bir akışta. İki motor var: Lokal ve Claude, istek başına seçiliyor."

---

## 🆘 B-Planı (bir şey takılırsa)
- **Çok yavaş:** Motoru Claude'a al, max iterasyonu 2'ye düşür.
- **Takıldı sandın:** Sağ üstteki canlı sayaç çalışıyorsa sistem çalışıyordur — bekle, sayfayı yenileme.
- **Demo riski:** 1–4 promptlarının çıktısını **sunumdan önce 1 kez çalıştırıp** checkpoint'lerde bırak; canlıda donarsa geçmişten göster.
- **Servis kontrol:** `GET /api/health` → `{"status":"ok"}` ve `/api/capabilities` → `anthropicAvailable:true`.

## ✅ Demo öncesi 30 sn checklist
- [ ] API 8765, Vite 5173, Ollama 11434, Postgres 5434 ayakta
- [ ] `.env` içinde `ANTHROPIC_API_KEY` dolu (capabilities `anthropicAvailable:true`)
- [ ] Tarayıcıda boş `demo` projesi açık, motor = Claude, RAG açık
- [ ] 1–4 promptları kopyalamaya hazır (bu dosya)
