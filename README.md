# Why Aware RAG Design

FPGA RAG v2 mimarisine göre hazırlanmış sorgu, loader ve normalize SQLite şema paketi.

## İçerik

- `fpga_rag_query_v4.py`: JSON/SQLite dual-backend sorgu arayüzü
- `fpga_rag_query_v3.py`: JSON backend query engine (v4 içinde import edilir)
- `fpga_rag_sqlite_loader_v2.py`: stage çıktılarından normalize SQLite üretir
- `fpga_rag_schema_arch_v2.sql`: mimari-v2 uyumlu DB şeması
- `fpga_rag_backend_benchmark_v1.py`: JSON vs SQLite performans benchmark
- `fpga_rag_db_mapping_arch_v2.md`: aşama-tablo eşleme notu
- `fpga_rag_v2_outputs/`: stage çıktıları + `fpga_rag_arch_v2.sqlite`

## Kurulum

```bash
python3 -m pip install numpy scikit-learn
```

## Kullanım

DB üret:

```bash
python3 fpga_rag_sqlite_loader_v2.py
```

Sorgu:

```bash
python3 fpga_rag_query_v4.py --backend sqlite --query "Neden DMA seçildi, alternatifler neydi?"
python3 fpga_rag_query_v4.py --backend sqlite --interactive
```

Benchmark:

```bash
python3 fpga_rag_backend_benchmark_v1.py --iterations 20
```

Web arayüz (RAG + ChatGPT):

```bash
OPENAI_API_KEY=your_key_here python3 fpga_rag_chatgpt_ui_v1.py --port 8787
```

Tarayıcı:

```text
http://127.0.0.1:8787
```
