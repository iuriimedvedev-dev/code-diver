# Latency A/B: все три рычага разом — 2026-09-21

## Дизайн

Rust-рука, `2026-09-21_latency-ab21b` (n=21, те же кейсы что `h91afix-run21`, seed 42):
 Cand-20 (`--rust-candidate-limit 20`) + strict second pass (cap 8, floor 0.15)
 + mixed CE (first pass llama `:18081`, second pass MLX `:18083` через новый
 `--second-ce-url`). Python-контроль H91a без изменений. 0 failures.

## Качество: все три рычага бесплатны

| full1065 (n=21) | Python | Rust | Δ |
|---|---|---|---|
| Бейзлайн run21 | 0.952 / 0.952 | 0.905 / 0.825 | −0.048 / −0.127 |
| **A/B ab21b** | 0.952 / 0.952 | **0.905 / 0.825** | −0.048 / −0.127 |

**42/42 arm-результатов попарно идентичны** (hit, rr) между run21 и ab21b —
включая Python-руку (подтверждает те же кейсы). Cand-20, strict second pass
и смена second-pass CE на MLX не изменили ни одного ранга на этих 21 кейсах.

## Latency: замер сконфаунден, выводов нет

| p50 / p95 | Python | Rust |
|---|---|---|
| run21 (утро) | 5130 / 7394ms | 3871 / 5442ms |
| **ab21b (вечер)** | 7207 / 15565ms | 5351 / 8507ms (+38%!) |

Обе руки замедлились одинаково (~+40%), включая нетронутый Python —
дело не в рычагах, а в машине: load average **47** после рестарта
(Spotlight-реиндекс + 3 сервера + eval). Прямая проверка: llama CE на
фиксированном 34-док батче дает 2234ms — как утром (2.25s), CE здоров.
Latency-эффект рычагов нужно перемерить на спокойной машине.

## Инфраструктура заодно

- `--second-ce-url` в бинаре (пусто = как раньше): types/main/pipeline.
- Харнес: `--rust-candidate-limit/--rust-second-pass-cap/--rust-second-pass-floor/--rust-second-ce-url`
  (дефолты = старый COMMAND, тест равенства цел). Пин → `569ebffd`, мок теста обновлен.
- Рестарт потер `/tmp/rust_catalog.jsonl` — перегенерил (`rust_bench_prepare.py`).
  Вывод: надо бы держать каталог/граф вне /tmp (follow-up).
- MLX CE на момент записи ОСТАНОВЛЕ (убита для проверки contention),
  embedder `:8001` + llama `:18081` + Qdrant живые.

## Эвиденсы

`artifacts/research/2026-09-07_rust-full-eval/2026-09-21_latency-ab21b/`
(сырые, gitignored). Следующий шаг: перезапустить ab21b при load < 10.
