# Инкрементальное обновление индекса — 2026-09-21

## Мотивация

`code-diver index --update-index` — misleading: запись всегда full
(scan all → embed ~136k → staging + alias swap). Настоящего diff/upsert не было.
Новый `scripts/update_index_incremental.py` закрывает дыру.

## Как работает

1. Scroll коллекции: item.id → (point id, embedded content).
2. Scan репозитория (без эмбеддингов).
3. Diff: deleted → delete points; added/changed → embed **только их** + upsert;
   unchanged → skip (экономия против полного ребилда).
4. Upsert идет через `QdrantVectorStore.append` — ids (uuid5 от item.id) и payload
   байт-идентичны по конструкции полному пути. Dry-run по умолчанию.

## Доказательство (живая коллекция intellij, синтетические пробы)

| Шаг | Результат |
|---|---|
| +probe .md | added 2, upserted, векторный поиск находит пробу топ-1/2/3 |
| ~probe (v1→v2) | **changed 1**, upserted 1 (manifest unchanged → skip) |
| −probe | deleted 2, коллекция ровно 136152 |
| Аудит до/после | drift 0.0000 |

Сканирование ~85-110с (полный скан без эмбеддингов — неснижаемая цена);
эмбеддинг только dirty items (2 шт ≈ секунды).

## Замечание по схеме

Upserted points схема-идентичны старым: top-level
{item, root, provider, model, dimensions}, item.{id, path, title, content, ...}.
Читатели (`payload["item"]["path"]`) ничего не заметят.

## Ограничения

- Graph-артефакт (`.code-diver/intellij-h37-jvm-graph.json`) не трогается —
  при реальных изменениях исходников нужен и его ребилд (отдельная задача).
- Dimensions сверяются с коллекцией (`append` падает при mismatch) — смена
  эмбеддинг-модели требует полного ребилда, это нормально.
