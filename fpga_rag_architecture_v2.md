# FPGA Helper Dev Tool — RAG Mimari Tasarımı v2
## "Why-Aware" Mühendislik Hafızası — İster-Odaklı Model

---

## Değişiklik Özeti (v1 → v2)

```
DEĞİŞEN:
  ✗ LLM Rationale Inference (Aşama 3) → KALDIRILDI
  ✓ Yerine: Kullanıcı İster Yükleme + Otomatik Eşleştirme
  ✓ Karma format desteği (yapılandırılmış + serbest metin)
  ✓ Otomatik ister ↔ component eşleştirme motoru

AYNI KALAN:
  • 3 katmanlı mimari (Vector + Graph + Req Tree)
  • Node/Edge veri modeli
  • Özyinelemeli gereksinim kırınımı
  • Çapraz referans sistemi
  • Halüsinasyon önleme katmanları
  • Sorgu routing ve yanıt şablonu
```

**Temel tasarım prensibi:**
"Why" bilgisinin tek güvenilir kaynağı, o kararı alan mühendistir.
LLM "neden" tahmini yapmaz. LLM'in görevi:
  (a) yüklenen isterlerden yapısal bilgi çıkarmak (parse),
  (b) isterleri proje entity'leriyle eşleştirmek (match),
  (c) eşleştirme sonuçlarını sorgulanabilir hale getirmek (serve).

---

## 1. Güncellenmiş Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                  GÜNCELLENMİŞ BESLEME PİPELINE'I               │
│                                                                 │
│  AŞAMA 1: PROJE TARAMA (Otomatik)                              │
│  ┌─────────────────────────────────────────────┐                │
│  │ Girdi: Proje dizini                         │                │
│  │   src/, bd/, constraints/, ip/, sim/,       │                │
│  │   reports/, scripts/, .git/                 │                │
│  │                                             │                │
│  │ Çıktı: Dosya manifest + metadata            │                │
│  │ (değişiklik yok)                            │                │
│  └──────────────────┬──────────────────────────┘                │
│                     │                                           │
│                     ▼                                           │
│  AŞAMA 2: ENTITY EXTRACTION (Otomatik)                         │
│  ┌─────────────────────────────────────────────┐                │
│  │ Proje dosyalarından yapısal bilgi çıkar:    │                │
│  │   .v/.sv/.vhd → modüller, portlar, FSM      │                │
│  │   .tcl (BD)   → IP blokları, bağlantılar    │                │
│  │   .xdc        → clock, pin, exception        │                │
│  │   .xci        → IP config + parametreler     │                │
│  │   reports/    → WNS, kaynak, DRC sonuçları   │                │
│  │   .git log    → değişiklik kronolojisi       │                │
│  │   yorumlar    → TODO/FIXME/HACK              │                │
│  │                                              │                │
│  │ Çıktı: COMPONENT, CONSTRAINT, EVIDENCE,     │                │
│  │        ISSUE node'ları + aralarındaki        │                │
│  │        DEPENDS_ON, CONSTRAINED_BY edge'leri  │                │
│  │                                              │                │
│  │ NOT: Bu aşama "ne var?" sorusuna cevap verir.│                │
│  │      "Neden var?" sorusunu SORMAZ.           │                │
│  └──────────────────┬──────────────────────────┘                │
│                     │                                           │
│                     ▼                                           │
│  ══════════════════════════════════════════════════════          │
│  AŞAMA 3: İSTER YÜKLEME (Kullanıcı — SEN)            ◄── YENİ │
│  ══════════════════════════════════════════════════════          │
│  ┌─────────────────────────────────────────────┐                │
│  │                                              │                │
│  │ SEN şu bilgileri yüklüyorsun:               │                │
│  │                                              │                │
│  │   a) Gereksinimler (requirement tree)        │                │
│  │      → ne isteniyor + neden isteniyor         │                │
│  │      → kabul kriterleri                       │                │
│  │      → gereksinim kırınımları                 │                │
│  │                                              │                │
│  │   b) Tasarım kararları (decision records)     │                │
│  │      → ne seçildi + neden seçildi            │                │
│  │      → alternatifler + neden elendi          │                │
│  │      → bilinen riskler                       │                │
│  │                                              │                │
│  │   c) Kısıtlar ve gerekçeleri                 │                │
│  │      → bu kısıt neden var                    │                │
│  │      → nereden geliyor (spec, board, müşteri)│                │
│  │                                              │                │
│  │ FORMAT: Karma (aşağıda detaylandırıldı)      │                │
│  │   • Yapılandırılmış: YAML, JSON              │                │
│  │   • Serbest metin: Markdown, PDF, Word       │                │
│  │   • İkisi bir arada: MD içinde YAML blokları │                │
│  │                                              │                │
│  │ Çıktı: REQUIREMENT, DECISION, CONSTRAINT     │                │
│  │        node'ları + DECOMPOSES_TO,             │                │
│  │        MOTIVATED_BY edge'leri                 │                │
│  │        (tümü confidence=HIGH çünkü kaynağı    │                │
│  │         mühendis)                             │                │
│  └──────────────────┬──────────────────────────┘                │
│                     │                                           │
│                     ▼                                           │
│  ══════════════════════════════════════════════════════          │
│  AŞAMA 4: OTOMATİK EŞLEŞTİRME                        ◄── YENİ │
│  ══════════════════════════════════════════════════════          │
│  ┌─────────────────────────────────────────────┐                │
│  │                                              │                │
│  │ Aşama 2'nin çıktısı (entity'ler) ile        │                │
│  │ Aşama 3'ün çıktısı (isterler) eşleştirilir  │                │
│  │                                              │                │
│  │ Detay: Bölüm 2'de açıklanıyor               │                │
│  │                                              │                │
│  │ Çıktı: IMPLEMENTS, VERIFIED_BY,             │                │
│  │        CONSTRAINED_BY edge'leri               │                │
│  └──────────────────┬──────────────────────────┘                │
│                     │                                           │
│                     ▼                                           │
│  AŞAMA 5: ÇAPRAZ REFERANS TESPİTİ (Otomatik)                   │
│  ┌─────────────────────────────────────────────┐                │
│  │ (v1 ile aynı — 4 boyutlu çapraz referans)   │                │
│  │ Yapısal benzerlik, problem benzerliği,       │                │
│  │ gereksinim benzerliği, pattern tekrarı       │                │
│  │                                              │                │
│  │ Çıktı: ANALOGOUS_TO, CONTRADICTS,           │                │
│  │        INFORMED_BY, REUSES_PATTERN edge'leri │                │
│  └──────────────────┬──────────────────────────┘                │
│                     │                                           │
│                     ▼                                           │
│  AŞAMA 6: GRAPH + VECTOR COMMIT                                │
│  ┌─────────────────────────────────────────────┐                │
│  │ Tüm node'lar ve edge'ler:                   │                │
│  │   → Graph DB'ye yazılır                      │                │
│  │   → Metin içerikleri Vector DB'ye embed       │                │
│  │   → Provenance kaydı: kaynak dosya,          │                │
│  │     aşama, zaman damgası                     │                │
│  └─────────────────────────────────────────────┘                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline'daki Sorumluluk Dağılımı

```
┌────────────────────┬─────────────┬──────────────────────────────┐
│ Aşama              │ Kim Yapıyor │ Ne Üretiyor                  │
├────────────────────┼─────────────┼──────────────────────────────┤
│ 1. Proje Tarama    │ Otomatik    │ Dosya haritası               │
│ 2. Entity Extract  │ Otomatik    │ Component, Constraint,       │
│                    │             │ Evidence, Issue node'ları     │
│ 3. İster Yükleme   │ SEN         │ Requirement, Decision        │
│                    │             │ node'ları + "why" bilgisi     │
│ 4. Eşleştirme     │ Otomatik    │ IMPLEMENTS, VERIFIED_BY       │
│                    │             │ edge'leri                     │
│ 5. Çapraz Referans │ Otomatik    │ Projeler arası edge'ler      │
│ 6. Commit          │ Otomatik    │ Graph + Vector DB yazımı     │
└────────────────────┴─────────────┴──────────────────────────────┘
```

---

## 2. Otomatik Eşleştirme Motoru (Aşama 4 — Detay)

Bu, mimarinin en kritik otomatik bileşeni. İsterleri (senden) entity'lerle (projeden) eşleştiriyor.

### 2.1 Eşleştirme Stratejileri

```
┌─────────────────────────────────────────────────────────────┐
│              OTOMATİK EŞLEŞTİRME MOTORU                    │
│                                                             │
│  Girdi A: İster node'ları (Aşama 3)                        │
│    Requirement, Decision, Constraint                        │
│    → hepsinde metin var (yapılandırılmış veya serbest)      │
│                                                             │
│  Girdi B: Entity node'ları (Aşama 2)                       │
│    Component, Constraint, Evidence                          │
│    → hepsinde teknik tanımlayıcılar var                     │
│                                                             │
│  ────────────────────────────────────────────                │
│                                                             │
│  STRATEJİ 1: İsim/Tanımlayıcı Eşleştirme (Exact/Fuzzy)    │
│  ┌─────────────────────────────────────────┐                │
│  │ İster metninde geçen teknik terimler    │                │
│  │ entity listesindeki isimlerle eşleşir:  │                │
│  │                                         │                │
│  │ İster: "AXI DMA, scatter-gather modunda  │                │
│  │        çalışacak"                        │                │
│  │                     ↓ eşleşir           │                │
│  │ Entity: Component{name: "axi_dma_0",    │                │
│  │         type: IP_core,                   │                │
│  │         vlnv: "xilinx:ip:axi_dma:7.1",  │                │
│  │         params: {sg_mode: true}}         │                │
│  │                                         │                │
│  │ Yöntem:                                 │                │
│  │   a) İster metninden NER (Named Entity   │                │
│  │      Recognition) ile teknik terimleri   │                │
│  │      çıkar: IP adları, modül adları,     │                │
│  │      protokol adları, parametre adları   │                │
│  │   b) Entity listesindeki name, vlnv,     │                │
│  │      interface alanlarıyla exact match   │                │
│  │   c) Fuzzy match (Levenshtein, alias DB) │                │
│  │      "DMA" ↔ "axi_dma_0"               │                │
│  │      "Ethernet" ↔ "axi_ethernet_0"     │                │
│  │                                         │                │
│  │ Edge üretir: IMPLEMENTS                  │                │
│  │ Confidence: HIGH (isim eşleşti)         │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  STRATEJİ 2: Semantik Eşleştirme (Embedding Benzerliği)    │
│  ┌─────────────────────────────────────────┐                │
│  │ İster metni ile entity bağlamı arasında  │                │
│  │ embedding benzerliği hesaplanır.         │                │
│  │                                         │                │
│  │ İster: "Sistem 1080p@60fps video akışını │                │
│  │        gerçek zamanlı işleyecek"         │                │
│  │                     ↓ semantik yakın     │                │
│  │ Entity: Component{name: "v_proc_ss_0",  │                │
│  │         type: IP_core,                   │                │
│  │         params: {max_width: 1920,        │                │
│  │                  max_height: 1080}}      │                │
│  │                                         │                │
│  │ Yöntem:                                 │                │
│  │   a) İster metnini embed et             │                │
│  │   b) Her entity'nin context'ini embed et │                │
│  │      (isim + parametreler + bağlı        │                │
│  │       interface'ler + yorumlar)          │                │
│  │   c) Cosine similarity > threshold       │                │
│  │      → eşleştirme öner                  │                │
│  │                                         │                │
│  │ Edge üretir: IMPLEMENTS (öneri)          │                │
│  │ Confidence: MEDIUM (doğrulama gerekebilir)│                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  STRATEJİ 3: Yapısal Çıkarım (Hiyerarşi Takibi)           │
│  ┌─────────────────────────────────────────┐                │
│  │ Eşleşen bir entity'nin bağımlılıklarını │                │
│  │ takip ederek dolaylı eşleşmeler bul.    │                │
│  │                                         │                │
│  │ İster: "HDMI girişten video al"          │                │
│  │   → eşleşir: Component{dvi2rgb_0}       │                │
│  │     → DEPENDS_ON: Component{clk_wiz_0}  │                │
│  │       → "clk_wiz_0 da bu isterin        │                │
│  │          dolaylı implementasyonu"        │                │
│  │                                         │                │
│  │ Yöntem:                                 │                │
│  │   a) Strateji 1 veya 2 ile anchor bul   │                │
│  │   b) Anchor'dan DEPENDS_ON edge'lerini   │                │
│  │      N derinliğe kadar tara              │                │
│  │   c) Bağımlı component'leri dolaylı      │                │
│  │      implementor olarak işaretle        │                │
│  │                                         │                │
│  │ Edge üretir: IMPLEMENTS (indirect)       │                │
│  │ Confidence: MEDIUM                       │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  STRATEJİ 4: Kanıt Eşleştirme (Evidence Binding)           │
│  ┌─────────────────────────────────────────┐                │
│  │ İsterdeki kabul kriterlerini evidence    │                │
│  │ node'larıyla eşleştir.                  │                │
│  │                                         │                │
│  │ İster acceptance_criteria:               │                │
│  │   "WNS ≥ 0 ns tüm clock domain'lerde"   │                │
│  │                     ↓ eşleşir           │                │
│  │ Evidence: {type: timing_report,          │                │
│  │           metrics: {WNS: 0.234}}         │                │
│  │                                         │                │
│  │ Yöntem:                                 │                │
│  │   a) Kabul kriterinden metrik türü çıkar │                │
│  │      (WNS, kaynak %, PSNR, baud rate...) │                │
│  │   b) Evidence node'larında aynı metrik   │                │
│  │      türünü ara                          │                │
│  │   c) Değeri karşılaştır → pass/fail      │                │
│  │                                         │                │
│  │ Edge üretir: VERIFIED_BY                 │                │
│  │ Confidence: HIGH (metrik somut)          │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  STRATEJİ 5: Kısıt Eşleştirme (Constraint Binding)         │
│  ┌─────────────────────────────────────────┐                │
│  │ İsterdeki kısıtları proje constraint    │                │
│  │ node'larıyla eşleştir.                  │                │
│  │                                         │                │
│  │ İster constraint:                        │                │
│  │   "Sistem clock 200 MHz"                 │                │
│  │                     ↓ eşleşir           │                │
│  │ Constraint: {type: timing,               │                │
│  │             spec: "create_clock -period   │                │
│  │             5.0 [get_ports sys_clk]"}     │                │
│  │                                         │                │
│  │ Yöntem:                                 │                │
│  │   a) İster kısıtlarından teknik          │                │
│  │      parametre çıkar (frekans, voltaj,   │                │
│  │      gecikme, bant genişliği)            │                │
│  │   b) Constraint node'larıyla eşleştir    │                │
│  │   c) Tutarsızlık varsa → uyarı          │                │
│  │                                         │                │
│  │ Edge üretir: CONSTRAINED_BY              │                │
│  │ Confidence: HIGH                         │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  ────────────────────────────────────────────                │
│                                                             │
│  STRATEJİ ÖNCELİK SIRASI:                                  │
│    1 (exact match) → 5 (constraint) → 4 (evidence)          │
│    → 2 (semantic) → 3 (structural)                          │
│                                                             │
│  ÇAKIŞMA ÇÖZÜMÜ:                                            │
│    Birden fazla strateji aynı eşleşmeyi bulursa             │
│    → confidence en yüksek olan kazanır                       │
│    Farklı eşleşmeleri bulursa                               │
│    → hepsi kaydedilir, en yüksek confidence birincil        │
│                                                             │
│  EŞLEŞMEYEN İSTERLER:                                       │
│    Hiçbir entity ile eşleşmeyen ister →                     │
│    "Coverage Gap" uyarısı:                                   │
│    "REQ-017: Bu gereksinimin projede karşılığı bulunamadı.  │
│     Eksik implementasyon veya eksik entity extraction        │
│     olabilir."                                              │
│                                                             │
│  EŞLEŞMEYEN ENTITY'LER:                                    │
│    Hiçbir isterle eşleşmeyen component →                    │
│    "Orphan Component" uyarısı:                              │
│    "axi_gpio_2: Bu bileşenin karşıladığı bir gereksinim    │
│     bulunamadı. Gereksiz bileşen veya eksik ister           │
│     olabilir."                                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Eşleştirme Çıktı Formatı

Her eşleştirme şu yapıda kaydedilir:

```
{
  "match_id": "M-0042",
  "source": {
    "type": "REQUIREMENT",
    "id": "REQ-L2-005",
    "text": "Kenar tespiti 3x3 Sobel filtresi ile yapılacak"
  },
  "target": {
    "type": "COMPONENT",
    "id": "sobel_filter_v1",
    "source_file": "src/image/sobel_3x3.v"
  },
  "edge_type": "IMPLEMENTS",
  "match_strategy": "exact_name + semantic",
  "confidence": "HIGH",
  "match_evidence": [
    "Modül adında 'sobel' geçiyor (exact)",
    "Parametrede kernel_size=3 var (semantic)"
  ],
  "unmatched_aspects": [
    "İsterdeki '8-bit grayscale' kısıtı modül port
     genişliğiyle doğrulanmalı"
  ]
}
```

---

## 3. Karma Format İster Yükleme Sistemi (Aşama 3 — Detay)

### 3.1 Desteklenen Format Tipleri

```
┌─────────────────────────────────────────────────────────────┐
│             İSTER YÜKLEME FORMAT DESTEĞİ                    │
│                                                             │
│  TİP A — Yapılandırılmış (Structured)                       │
│  ┌─────────────────────────────────────────┐                │
│  │ Format: YAML veya JSON                   │                │
│  │ Avantaj: Doğrudan parse, sıfır belirsizlik│               │
│  │ Dezavantaj: Yazması daha zahmetli        │                │
│  │                                         │                │
│  │ Kullanım: Gereksinim ağacı, parametre    │                │
│  │ listeleri, kabul kriterleri, karar        │                │
│  │ kayıtları                                │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  TİP B — Serbest Metin (Free Text)                          │
│  ┌─────────────────────────────────────────┐                │
│  │ Format: Markdown, PDF, Word              │                │
│  │ Avantaj: Doğal yazım, bağlam zengin     │                │
│  │ Dezavantaj: Parse gerekiyor (LLM ile)    │                │
│  │                                         │                │
│  │ Kullanım: Tasarım gerekçeleri, mimari    │                │
│  │ açıklamalar, trade-off analizleri,       │                │
│  │ toplantı notları                         │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  TİP C — Karma (Hybrid)                                     │
│  ┌─────────────────────────────────────────┐                │
│  │ Format: Markdown içinde YAML/JSON blokları│               │
│  │ Avantaj: En esnek, hem okunabilir hem     │                │
│  │          parse edilebilir                 │                │
│  │                                         │                │
│  │ Kullanım: Her şey — önerilen birincil     │                │
│  │ format                                   │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Karma Format — Önerilen Yapı

Markdown içinde YAML front-matter + serbest metin gövde:

```markdown
# ---- Gereksinim Örneği (Karma Format) ----

---                                        ← YAML bloğu başlangıcı
req_id: REQ-L1-003
level: L1
type: functional
priority: must
parent: REQ-L0-001
status: active

acceptance_criteria:
  - "HDMI girişten 1080p@60fps video alınabilir"
  - "Piksel verisi RGB888 formatında AXI4-Stream'e aktarılır"
  - "Video sync sinyalleri (hsync, vsync) doğru zamanlama ile üretilir"

constraints:
  - type: interface
    spec: "HDMI 1.4b uyumlu"
  - type: timing
    spec: "148.5 MHz pixel clock"
  - type: board
    spec: "Nexys Video HDMI IN (J4 connector)"
---                                        ← YAML bloğu sonu

## Gereksinim

Sistem, HDMI girişinden 1080p çözünürlükte 60fps video akışını
alabilecek.

## Neden Bu Gereksinim Var

Projenin temel amacı gerçek zamanlı görüntü işleme. 1080p@60fps,
hedef uygulama için minimum kabul edilebilir çözünürlük ve kare
hızı. Müşteri spec'inde "full HD real-time" ifadesi yer alıyor
(bkz. customer_spec_v3.pdf, Bölüm 4.2).

Daha düşük çözünürlük (720p) düşünüldü ancak müşteri tarafından
reddedildi. 4K düşünülmedi çünkü hedef FPGA'nın (Artix-7)
bant genişliği ve kaynak limitleri yetmez.

## Alt Gereksinimlere Kırınım Gerekçesi

Bu gereksinim üç alt gereksinime kırılıyor:
- REQ-L2-007: HDMI fiziksel arayüz (DVI2RGB IP)
  → Neden: HDMI sinyalini decode etmek ayrı bir sorumluluk
- REQ-L2-008: Pixel clock domain yönetimi
  → Neden: HDMI source kendi clock'unu gönderiyor, tasarımın
    geri kalanıyla senkronizasyon gerekiyor
- REQ-L2-009: Video timing generator / detector
  → Neden: Downstream pipeline'ın frame boundary'leri bilmesi lazım
```

```markdown
# ---- Karar Örneği (Karma Format) ----

---
decision_id: DEC-012
title: "HDMI alıcı olarak DVI2RGB IP seçimi"
related_requirements:
  - REQ-L2-007
  - REQ-L1-003

chosen_option: "Digilent DVI2RGB IP v2.0"

alternatives:
  - option: "Xilinx HDMI RX Subsystem"
    rejected_because: "Lisans gerektirir, Artix-7'de bazı
                       özellikleri desteklenmiyor"
  - option: "Custom HDMI deserializer (RTL)"
    rejected_because: "Geliştirme süresi çok yüksek, TMDS
                       decode karmaşık, test edilmemiş olur"
  - option: "ADV7611 harici HDMI receiver chip"
    rejected_because: "Board'da bu chip yok, ek donanım gerektirir"

consequences:
  - "pixel_clk IP tarafından recover ediliyor, async domain"
  - "IP sadece DVI destekliyor, HDMI audio yok"
  - "IP'nin bilinen timing sorunu: pixel_clk jitter yüksek
     olabilir, downstream'de BUFG + MMCM gerekebilir"
---

## Karar Bağlamı

Nexys Video board üzerinde HDMI girişten video almamız gerekiyor.
Board'un HDMI IN portu doğrudan FPGA bankına bağlı (harici
receiver chip yok), bu yüzden TMDS sinyallerini FPGA içinde
deserialize etmemiz gerekiyor.

## Gerekçe (Why)

Digilent DVI2RGB IP seçildi çünkü:
1. Nexys Video board'un kendi referans tasarımında bu IP kullanılıyor
   → board ile uyumluluk test edilmiş
2. Ücretsiz ve açık kaynak (Digilent GitHub)
3. Artix-7 ISERDESE2 primitive'leri ile çalışıyor
4. Topluluk desteği ve bilinen workaround'lar mevcut

Xilinx'in kendi HDMI RX IP'si daha kapsamlı ama bu projede
HDMI audio gerekmediği ve lisans maliyeti olduğu için elendi.

## Bilinen Riskler

- pixel_clk recovery kalitesi source'a bağımlı
- IP'nin bazı versiyonlarında known issue: hot-plug sonrası
  re-lock sorunu (bkz. Digilent forum #4521)
```

### 3.3 Format Parse Pipeline'ı

```
┌─────────────────────────────────────────────────────────────┐
│              İSTER PARSE PİPELINE'I                          │
│                                                             │
│  Girdi: Kullanıcının yüklediği dosya                       │
│                                                             │
│  ADIM 1: Format Algılama                                    │
│  ┌─────────────────────────────────────────┐                │
│  │ Dosya uzantısı + içerik analizi:        │                │
│  │   .yaml/.json → Tip A (yapılandırılmış)  │                │
│  │   .md + YAML front-matter → Tip C (karma)│                │
│  │   .md (sade) → Tip B (serbest metin)     │                │
│  │   .pdf/.docx → Tip B (serbest metin)     │                │
│  └────────────────────┬────────────────────┘                │
│                       │                                     │
│         ┌─────────────┼─────────────┐                       │
│         ▼             ▼             ▼                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │  TİP A   │  │  TİP B   │  │  TİP C   │                  │
│  │ Doğrudan │  │ LLM ile  │  │ YAML:    │                  │
│  │ YAML/JSON│  │ yapısal  │  │  doğrudan │                  │
│  │ parse    │  │ bilgi    │  │ Metin:   │                  │
│  │          │  │ çıkarımı │  │  LLM ile  │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │             │             │                          │
│       └─────────────┼─────────────┘                          │
│                     ▼                                       │
│  ADIM 2: Node Üretimi                                       │
│  ┌─────────────────────────────────────────┐                │
│  │ Parse sonucundan node'lar üretilir:     │                │
│  │                                         │                │
│  │ req_id var → REQUIREMENT node           │                │
│  │ decision_id var → DECISION node         │                │
│  │ constraint bilgisi var → CONSTRAINT node│                │
│  │ acceptance_criteria var → kabul kriteri  │                │
│  │   olarak REQUIREMENT'a eklenir          │                │
│  └────────────────────┬────────────────────┘                │
│                       │                                     │
│                       ▼                                     │
│  ADIM 3: Edge Üretimi                                       │
│  ┌─────────────────────────────────────────┐                │
│  │ İlişkiler çıkarılır:                    │                │
│  │                                         │                │
│  │ parent alanı → DECOMPOSES_TO edge       │                │
│  │   + serbest metindeki "neden kırıldı"   │                │
│  │     açıklaması → decomposition_rationale│                │
│  │                                         │                │
│  │ related_requirements → MOTIVATED_BY edge│                │
│  │                                         │                │
│  │ alternatives → ALTERNATIVE_TO edge'leri │                │
│  │   + rejection_reason metadata           │                │
│  │                                         │                │
│  │ consequences → risk alanına kaydet      │                │
│  └────────────────────┬────────────────────┘                │
│                       │                                     │
│                       ▼                                     │
│  ADIM 4: Serbest Metin Zenginleştirme                      │
│  ┌─────────────────────────────────────────┐                │
│  │ Serbest metin kısımları (Neden, Bağlam,  │                │
│  │ Gerekçe bölümleri):                     │                │
│  │                                         │                │
│  │ a) Yapılandırılmış alanlara ek bağlam   │                │
│  │    olarak node'a eklenir (rationale_text)│                │
│  │                                         │                │
│  │ b) Vector DB'ye ayrıca embed edilir      │                │
│  │    (semantik arama için)                │                │
│  │                                         │                │
│  │ c) İçindeki referanslar (dosya adı,      │                │
│  │    spec numarası, bölüm referansı)       │                │
│  │    tespit edilip INFORMED_BY edge'i       │                │
│  │    olarak kaydedilir                     │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  TÜM ÇIKTILAR: confidence = HIGH                            │
│  (Kaynak: mühendis. LLM sadece parse etti, üretmedi.)      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Serbest Metin Parse İçin LLM Prompt Stratejisi

Tip B ve Tip C'deki serbest metin bölümlerini parse etmek için:

```
SİSTEM PROMPTu:
  "Sen bir gereksinim mühendisi parse aracısın.
   Sana bir mühendislik dokümanı verilecek.
   Senin görevin:

   1) Metindeki gereksinimleri, kararları ve kısıtları
      AYNEN ÇIKARmak — yeniden yazmak veya yorumlamak DEĞİL
   2) Her çıkarıma kaynak satır numarası eklemek
   3) Metin ile yapılandırılmış veri arasındaki
      tutarlılığı kontrol etmek
   4) Eksik alan varsa bildirmek (parse edilemedi, not: yok)

   KURALLAR:
   - ASLA mühendis yazmadığı bir gerekçe ÜRETME
   - Metnin söylemediği bir şeyi çıkarma
   - 'Muhtemelen', 'büyük olasılıkla' gibi ifadeler KULLANMA
   - Emin olmadığın çıkarımları 'PARSE_UNCERTAIN' olarak etiketle"

ÇIKTI FORMATI:
  {
    "requirements": [...],
    "decisions": [...],
    "constraints": [...],
    "cross_references": [...],     // metinde geçen referanslar
    "parse_warnings": [...]        // belirsiz veya eksik yerler
  }
```

**Kritik fark:** v1'de LLM "neden olabilir?" diye tahmin ediyordu. v2'de LLM sadece "mühendis ne yazmış?" diye parse ediyor. Üretim yok, sadece çıkarım.

---

## 4. Confidence Modeli — Güncelleme

v1'de confidence LLM çıkarımının belirsizliğini ölçüyordu. v2'de confidence artık farklı anlama geliyor:

```
┌─────────────────────────────────────────────────────────────┐
│           GÜNCELLENMİŞ CONFIDENCE MODELİ                    │
│                                                             │
│  ── İSTER NODE'LARI (Aşama 3) ──                            │
│                                                             │
│  Tümü HIGH başlar.                                          │
│  Kaynak mühendis, LLM sadece parse etti.                    │
│                                                             │
│  İstisna:                                                   │
│    PARSE_UNCERTAIN etiketi → MEDIUM                         │
│    "LLM parse sırasında bu kısmı tam                       │
│     çıkaramadı, orijinal metni kontrol et"                  │
│                                                             │
│  ── EŞLEŞTİRME EDGE'LERİ (Aşama 4) ──                     │
│                                                             │
│  Strateji 1 (exact match):     HIGH                         │
│  Strateji 4 (evidence match):  HIGH                         │
│  Strateji 5 (constraint match):HIGH                         │
│  Strateji 2 (semantic match):  MEDIUM                       │
│  Strateji 3 (structural):     MEDIUM                        │
│                                                             │
│  ── ÇAPRAZ REFERANS EDGE'LERİ (Aşama 5) ──                 │
│                                                             │
│  Aynı IP + aynı config:      HIGH                          │
│  Aynı IP + farklı config:    MEDIUM                        │
│  Semantik benzerlik:          MEDIUM                        │
│  Pattern tekrarı:             MEDIUM                        │
│                                                             │
│  ── ENTITY NODE'LARI (Aşama 2) ──                           │
│                                                             │
│  Doğrudan dosyadan çıkan:    HIGH                          │
│  (modül adı, IP config, constraint)                         │
│  Yorumdan çıkarılan:         MEDIUM                        │
│  (TODO/FIXME içeriği)                                       │
│                                                             │
│  ── ZİNCİR CONFIDENCE (Sorgu Zamanı) ──                     │
│                                                             │
│  Bir traversal path'indeki en düşük confidence              │
│  zincirin toplam confidence'ını belirler.                   │
│                                                             │
│  Requirement(HIGH) → IMPLEMENTS(MEDIUM) →                   │
│  Component(HIGH) → VERIFIED_BY(HIGH) → Evidence(HIGH)       │
│  → Zincir = MEDIUM                                          │
│  → "Eşleştirme semantik, doğrulaman gerekebilir"           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Güncellenmiş Halüsinasyon Önleme

```
┌─────────────────────────────────────────────────────────────┐
│      v2 — HALÜSİNASYON ÖNLEME (güncelleme)                 │
│                                                             │
│  EN BÜYÜK DEĞİŞİKLİK:                                      │
│  "Why" bilgisinin kaynağı artık LLM değil.                 │
│  Bu, halüsinasyonun en büyük kaynağını ortadan kaldırır.   │
│                                                             │
│  Kalan halüsinasyon riskleri ve önlemleri:                  │
│                                                             │
│  RİSK 1: Parse Hatası                                       │
│  ┌─────────────────────────────────────────┐                │
│  │ LLM, serbest metni yanlış parse edebilir│                │
│  │ → Gerekçeyi çarpıtabilir                │                │
│  │                                         │                │
│  │ Önlem:                                  │                │
│  │   • Parse çıktısında kaynak satır no     │                │
│  │   • PARSE_UNCERTAIN etiketi              │                │
│  │   • Orijinal metin her zaman erişilebilir│                │
│  │   • Yapılandırılmış kısım serbest metin  │                │
│  │     kısmını override eder (çelişki varsa) │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  RİSK 2: Yanlış Eşleştirme                                  │
│  ┌─────────────────────────────────────────┐                │
│  │ Otomatik eşleştirme yanlış ister-entity │                │
│  │ çifti üretebilir                        │                │
│  │                                         │                │
│  │ Önlem:                                  │                │
│  │   • Confidence etiketleme               │                │
│  │   • MEDIUM eşleştirmelerde uyarı         │                │
│  │   • Coverage gap / orphan component      │                │
│  │     tespiti                              │                │
│  │   • Kullanıcı doğrulama endpoint'i       │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  RİSK 3: Eski / Tutarsız İster                              │
│  ┌─────────────────────────────────────────┐                │
│  │ İster güncellenmiş ama eski versiyon     │                │
│  │ hâlâ DB'de                              │                │
│  │                                         │                │
│  │ Önlem:                                  │                │
│  │   • Versiyonlama (her ister yüklemesi    │                │
│  │     tarih damgalı)                       │                │
│  │   • SUPERSEDES edge'i (yeni → eski)      │                │
│  │   • Sorgu zamanında en güncel versiyon    │                │
│  │     tercih edilir                        │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  RİSK 4: Sorgu Zamanı Yanıt Üretimi                        │
│  ┌─────────────────────────────────────────┐                │
│  │ LLM, graph verilerini yorumlarken       │                │
│  │ ekleme/çıkarma yapabilir                │                │
│  │                                         │                │
│  │ Önlem:                                  │                │
│  │   • Zorunlu yanıt şablonu (v1 ile aynı)  │                │
│  │   • Yanıttaki her ifade bir node/edge'e   │                │
│  │     referans vermeli                      │                │
│  │   • "Kanıtsız ifade" kontrolü             │                │
│  │   • Graph'ta olmayan bilgi →              │                │
│  │     "DB'de bu bilgi yok" demeli           │                │
│  └─────────────────────────────────────────┘                │
│                                                             │
│  v1'DEN KALAN KATMANLAR (hâlâ aktif):                       │
│  ✓ Evidence Gate                                            │
│  ✓ Confidence Propagation                                   │
│  ✓ Version / Context Filter                                 │
│  ✓ Tool-Verified Loop                                       │
│  ✓ Contradiction Detection                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. v1'den Değişmeyen Bölümler (Referans)

Aşağıdaki bölümler v1 dokümanıyla aynıdır:

| Bölüm | İçerik | Durum |
|---|---|---|
| Node tipleri | PROJECT, REQUIREMENT, DECISION, COMPONENT, CONSTRAINT, EVIDENCE, PATTERN, SOURCE_DOC, ISSUE | Aynı |
| Edge tipleri | Tüm hiyerarşi, nedensellik, izlenebilirlik, bağımlılık, çapraz referans edge'leri | Aynı |
| Gereksinim kırınım ağacı | Özyinelemeli L0→Ln, kırınım kuralları, tetikleyici tipler | Aynı |
| Çapraz referans sistemi | 4 boyutlu algılama, sorgu örnekleri | Aynı |
| Sorgu routing | What/How/Why/Trace/CrossRef sınıflandırma | Aynı |
| Yanıt şablonu | Zorunlu "Why" yanıt formatı | Aynı |

---

## 7. Güncellenmiş Sistem Etkileşim Haritası

```
                    ┌───────────────┐
                    │  KULLANICI    │
                    │  SORGUSU      │
                    └───────┬───────┘
                            │
                    ┌───────▼───────┐
                    │  QUERY        │
                    │  ROUTER       │
                    └──┬────┬───┬──┘
                       │    │   │
           ┌───────────┘    │   └───────────┐
           ▼                ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ VECTOR   │    │ GRAPH    │    │ REQ      │
    │ STORE    │◄──►│ STORE    │◄──►│ TREE     │
    └──────────┘    └──────────┘    └──────────┘
           │                │               │
           └───────────┬────┘───────────────┘
                       │
               ┌───────▼───────┐
               │ ANTI-         │
               │ HALLUCINATION │
               │ GATES         │
               └───────┬───────┘
                       │
               ┌───────▼───────┐
               │ STRUCTURED    │
               │ RESPONSE      │
               └───────┬───────┘
                       │
               ┌───────▼───────┐
               │ KULLANICIYA   │
               │ YANITLA       │
               └───────────────┘



  ┌────────────────────────────────────────────────────────┐
  │                  BESLEME TARAFI (v2)                    │
  │                                                        │
  │                                                        │
  │  ┌──────────────┐    ┌──────────────────┐              │
  │  │ PROJE        │    │ İSTERLER         │              │
  │  │ DOSYALARI    │    │ (SEN yüklüyorsun)│              │
  │  │ (otomatik)   │    │                  │              │
  │  └──────┬───────┘    └────────┬─────────┘              │
  │         │                     │                        │
  │         ▼                     ▼                        │
  │  ┌──────────────┐    ┌──────────────────┐              │
  │  │ AŞAMA 1+2    │    │ AŞAMA 3          │              │
  │  │ Proje Tarama │    │ İster Parse      │              │
  │  │ + Entity     │    │ (YAML parse +    │              │
  │  │ Extraction   │    │  LLM text parse) │              │
  │  │              │    │                  │              │
  │  │ Çıktı:       │    │ Çıktı:           │              │
  │  │ Component,   │    │ Requirement,     │              │
  │  │ Constraint,  │    │ Decision,        │              │
  │  │ Evidence,    │    │ Constraint       │              │
  │  │ Issue        │    │ node'ları        │              │
  │  │ node'ları    │    │ (confidence=HIGH)│              │
  │  └──────┬───────┘    └────────┬─────────┘              │
  │         │                     │                        │
  │         └──────────┬──────────┘                        │
  │                    │                                   │
  │                    ▼                                   │
  │         ┌──────────────────┐                           │
  │         │ AŞAMA 4          │                           │
  │         │ OTOMATİK         │                           │
  │         │ EŞLEŞTİRME      │                           │
  │         │                  │                           │
  │         │ 5 strateji:      │                           │
  │         │ exact → constraint│                          │
  │         │ → evidence →     │                           │
  │         │ semantic →       │                           │
  │         │ structural       │                           │
  │         │                  │                           │
  │         │ Çıktı:           │                           │
  │         │ IMPLEMENTS,      │                           │
  │         │ VERIFIED_BY,     │                           │
  │         │ CONSTRAINED_BY   │                           │
  │         │ edge'leri        │                           │
  │         │                  │                           │
  │         │ + Coverage Gap   │                           │
  │         │ + Orphan uyarıları│                          │
  │         └────────┬─────────┘                           │
  │                  │                                     │
  │                  ▼                                     │
  │         ┌──────────────────┐                           │
  │         │ AŞAMA 5          │                           │
  │         │ ÇAPRAZ REFERANS  │                           │
  │         │ TESPİTİ          │                           │
  │         └────────┬─────────┘                           │
  │                  │                                     │
  │                  ▼                                     │
  │         ┌──────────────────┐                           │
  │         │ AŞAMA 6          │                           │
  │         │ GRAPH + VECTOR   │                           │
  │         │ COMMIT           │                           │
  │         └──────────────────┘                           │
  │                                                        │
  └────────────────────────────────────────────────────────┘
```

---

*v2: "Why" bilgisinin kaynağı LLM çıkarımı değil, mühendis dokümanıdır.
LLM'in rolü: parse, eşleştir, sun — üretme.*
