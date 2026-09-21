# Индекс intellij: вместо ребилда — хирургический prune — 2026-09-21

## Почему не полный ребилд

- Чекут заморожен с 24.08: `693e76f0..HEAD` = 1 ninja-коммит, только `.code-diver/`-метаданные.
  Исходниковый корпус байт-идентичен.
- Инкрементального апдейта в code-diver **нет**: `index --update-index` лишь меняет
  обработку существующей коллекции, сама запись всегда full (scan all → embed ~136k
  → staging + alias swap, `src/code_diver/store/qdrant_vector_store.py`). Ребилд ради
  нулевого дрейфа контента — часы эмбеддинга впустую.

## Что было не так

Аудит (`scripts/audit_index_staleness.py`, полное сравнение, не сэмпл):
индексировано 136578, сканер дает 136152. **426 stale (0.3%)**, content-diff 0.
Все 426 — dot-paths/метаданные, ноль исходников:

| Группа | Штук |
|---|---|
| `.agents/skills/**` (доки скиллов) | 114 |
| `.claude/**` | 112 |
| `.idea.bazel/**` | 80 |
| `python/**/test-data, .vscode, .settings, .state.json` и т.п. | 50 |
| `plugins/**/.vscode, .ai` | 20 |
| `.github, .ai, .ownership` | 44 |
| `.buildifier.json, native, platform` (dot-файлы) | 6 |

Старый сканер индексировал dot-файлы, текущий скипает. Мусор был retrievable
(мог всплывать в выдаче).

## Что сделано

- `scripts/prune_stale_index_points.py` (новый, dry-run по умолчанию): маппит
  item.id → point UUID полным скроллом, требует 100% match, удаляет по IDs.
- Удалено 426/426, missing 0. Коллекция
  `intellij_h66b_budget_qwen__staging_4fa4c6c030d2440daeeefc996ded6473`:
  136578 → **136152**. Алиас/шейма не тронуты.
- Контрольный аудит после: indexed 136152 = scanner 136152, only_in 0,
  only_in_scan 0, content differs 0 → **drift 0.0000**.
- Список удаленного: `docs/research/2026-09-21_index-prune-stale-ids.txt`.

## Влияние на замеры

Нулевое ожидаемое: eval-expected — продуктовые исходники, удален только мусор.
Прогоны run21/ab21b валидны (мусор в top-10 кодовых запросов практически не всплывает).
