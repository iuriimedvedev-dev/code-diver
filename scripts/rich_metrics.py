from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

import requests


EMBEDDING_URL = "http://127.0.0.1:8001/v1/embeddings"
EMBEDDING_MODEL = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall", "it",
    "its", "this", "that", "these", "those", "i", "you", "he", "she",
    "we", "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "its", "our", "their", "not", "no", "nor", "so", "if", "then", "than",
    "also", "just", "very", "too", "much", "more", "most", "some", "any",
    "each", "every", "all", "both", "few", "many", "several", "about",
    "into", "over", "after", "before", "between", "under", "above",
    "below", "up", "down", "out", "off", "over", "such", "only",
    "own", "same", "other", "another", "well", "back", "still", "even",
    "because", "while", "since", "until", "although", "though", "once",
    "here", "there", "where", "when", "why", "how", "which", "who",
    "whom", "what", "whether", "if", "then", "else", "than",
}

PYTHON_KEYWORDS = {
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield",
}


def embed(text: str) -> list[float] | None:
    try:
        resp = requests.post(
            EMBEDDING_URL,
            json={"model": EMBEDDING_MODEL, "input": text},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
        return data["data"][0]["embedding"]
    except Exception:
        return None


def cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def word_tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Zа-яА-Я0-9]+(?:[-'][a-zA-Zа-яА-Я0-9]+)*", text.lower())


def sent_tokenize(text: str) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s for s in sents if len(s.strip()) > 2]


def extract_ngrams(words: list[str], n: int = 2) -> list[str]:
    return [" ".join(words[i:i+n]) for i in range(len(words)-n+1)]


def compute_corpus_keywords(
    reference_texts: list[str],
    candidate_preds: dict[str, list[str]],
    top_n: int = 30,
) -> dict[str, list[str]]:
    corpus: dict[str, str] = {"__reference__": " ".join(reference_texts)}
    for label, preds in candidate_preds.items():
        corpus[label] = " ".join(preds)

    doc_words = {}
    doc_terms = {}
    for doc_id, text in corpus.items():
        words = word_tokenize(text)
        terms = [w for w in words if w not in STOPWORDS and w not in PYTHON_KEYWORDS and len(w) > 2]
        doc_words[doc_id] = words
        doc_terms[doc_id] = terms

    ndocs = len(corpus)
    doc_freq: Counter[str] = Counter()
    for terms in doc_terms.values():
        doc_freq.update(set(terms))

    result = {}
    for doc_id, terms in doc_terms.items():
        term_counts = Counter(terms)
        tfidf: dict[str, float] = {}
        for term, count in term_counts.items():
            tf = math.log(1 + count / len(terms)) if terms else 0
            idf = math.log((ndocs + 1) / (doc_freq.get(term, 0) + 1)) + 1
            tfidf[term] = tf * idf
        top = sorted(tfidf.items(), key=lambda x: -x[1])[:top_n]
        result[doc_id] = [t for t, _ in top]

    return result


def compute_keyword_overlap(candidate_datas: list[dict]) -> dict[str, dict]:
    labels = [cd["label"] for cd in candidate_datas]
    all_refs = []
    candidate_preds: dict[str, list[str]] = {}
    for cd in candidate_datas:
        all_refs.extend(cd["refs"])
        candidate_preds[cd["label"]] = cd["preds"]

    corpus_kw = compute_corpus_keywords(all_refs, candidate_preds, top_n=30)
    ref_set = set(corpus_kw.get("__reference__", []))

    result = {}
    for label in labels:
        pred_set = set(corpus_kw.get(label, []))
        overlap = pred_set & ref_set
        precision = len(overlap) / len(pred_set) if pred_set else 0.0
        recall = len(overlap) / len(ref_set) if ref_set else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        result[label] = {
            "kw_precision": round(precision, 4),
            "kw_recall": round(recall, 4),
            "kw_f1": round(f1, 4),
            "kw_pred_top": ", ".join(pred_set - ref_set)[:100],
            "kw_shared": ", ".join(overlap)[:100],
        }
    return result


def compute_prediction_metrics(prediction: str) -> dict[str, float]:
    pred = str(prediction or "").strip()
    words = word_tokenize(pred)
    chars = len(pred)
    word_count = len(words)
    sentences = sent_tokenize(pred)
    sent_count = len(sentences)
    unique = len(set(words))
    ttr = unique / word_count if word_count else 0.0

    content_words = [w for w in words if w not in STOPWORDS]
    content_ttr = len(set(content_words)) / len(content_words) if content_words else 0.0

    avg_wl = mean(len(w) for w in words) if words else 0.0
    long_words = sum(1 for w in words if len(w) > 6)
    long_word_ratio = long_words / word_count if word_count else 0.0

    avg_sl = word_count / sent_count if sent_count else 0.0

    code_blocks = len(re.findall(r"```", pred)) // 2
    inline_code = len(re.findall(r"`[^`]+`", pred))

    caps_words = sum(1 for w in words if w.isupper() and len(w) > 1)
    caps_ratio = caps_words / word_count if word_count else 0.0

    punct = sum(1 for c in pred if c in ".,;:!?()-[]{}")
    punct_density = punct / chars if chars else 0.0

    stopword_count = sum(1 for w in words if w in STOPWORDS)
    stopword_ratio = stopword_count / word_count if word_count else 0.0

    return {
        "char_len": chars,
        "word_len": word_count,
        "sentence_count": sent_count,
        "type_token_ratio": round(ttr, 4),
        "content_word_ttr": round(content_ttr, 4),
        "avg_word_length": round(avg_wl, 3),
        "avg_sentence_len_words": round(avg_sl, 1),
        "long_word_ratio": round(long_word_ratio, 4),
        "code_block_count": code_blocks,
        "inline_code_count": inline_code,
        "caps_ratio": round(caps_ratio, 4),
        "punct_density": round(punct_density, 4),
        "stopword_ratio": round(stopword_ratio, 4),
    }


def process_candidate(cr: dict) -> dict:
    label = cr["label"]
    report = json.loads(Path(cr["path"]).read_text(encoding="utf-8"))
    results = report.get("results", [])
    valid = [r for r in results if r.get("prediction") and str(r["prediction"]).strip() and not r.get("error")]

    refs = [str(r.get("reference", "")) for r in valid]
    preds = [str(r.get("prediction", "")) for r in valid]

    all_metrics = [compute_prediction_metrics(p) for p in preds]
    agg = {}
    for key in all_metrics[0] if all_metrics else {}:
        vals = [m[key] for m in all_metrics]
        agg[key] = mean(vals) if vals else 0.0

    sims = compute_embedding_similarity(preds, refs) if preds else []
    emb_sim = mean(sims) if sims else 0.0

    indiv_overalls = [
        float(r.get("metrics", {}).get("judge_overall", 0) or 0)
        for r in valid
    ]
    mean_jo = mean(indiv_overalls) if indiv_overalls else 0.0
    total_jo = sum(indiv_overalls)

    # F1 metrics from individual report
    m = report.get("metrics") or {}
    token_f1 = float(m.get("token_f1", 0) or 0)
    key_token_f1 = float(m.get("key_token_f1", 0) or 0)
    bigram_f1 = float(m.get("bigram_f1", 0) or 0)

    return {
        "label": label,
        "mean_jo": mean_jo,
        "total_jo": total_jo,
        **agg,
        "embedding_cosine": round(emb_sim, 4),
        "token_f1": round(token_f1, 4),
        "key_token_f1": round(key_token_f1, 4),
        "bigram_f1": round(bigram_f1, 4),
        "valid": len(valid),
        "preds": preds,
        "refs": refs,
    }


def compute_embedding_similarity(predictions: list[str], references: list[str]) -> list[float]:
    sims = []
    for pred, ref in zip(predictions, references):
        if not pred or not ref:
            sims.append(0.0)
            continue
        e_pred = embed(str(pred))
        e_ref = embed(str(ref))
        if e_pred and e_ref:
            sims.append(cosine_sim(e_pred, e_ref))
        else:
            sims.append(0.0)
    return sims



def main() -> int:
    meta_path = Path(sys.argv[1])
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    candidates = meta.get("candidate_reports", [])

    print("=== ПОЛНАЯ ТАБЛИЦА МЕТРИК ===\n")

    print("--- Базовые метрики + F1 ---")
    candidate_datas = [process_candidate(cr) for cr in candidates]

    header = [
        "Candidate",
        "Valid", "JO µ", "JO Σ",
        "Chars", "Words", "TTR",
        "EmbSim",
        "TokF1", "KeyF1", "BiF1",
    ]
    print("| " + " | ".join(header) + " |")
    print("| " + " | ".join("---:" for _ in header) + " |")

    for cd in sorted(candidate_datas, key=lambda x: -x["mean_jo"]):
        print(
            "| "
            + " | ".join([
                cd["label"],
                str(cd["valid"]),
                f"{cd['mean_jo']:.3f}",
                f"{cd['total_jo']:.1f}",
                f"{cd['char_len']:.0f}",
                f"{cd['word_len']:.0f}",
                f"{cd['type_token_ratio']:.3f}",
                f"{cd['embedding_cosine']:.4f}",
                f"{cd['token_f1']:.4f}",
                f"{cd['key_token_f1']:.4f}",
                f"{cd['bigram_f1']:.4f}",
            ])
            + " |"
        )

    print("\n--- Keyword Overlap (TF-IDF, vs reference) ---")
    kw_data = compute_keyword_overlap(candidate_datas)

    kw_header = ["Candidate", "KW Prec", "KW Rec", "KW F1"]
    print("| " + " | ".join(kw_header) + " |")
    print("| " + " | ".join("---:" for _ in kw_header) + " |")
    for cd in sorted(candidate_datas, key=lambda x: -kw_data[x["label"]]["kw_f1"]):
        kw = kw_data[cd["label"]]
        print(
            "| "
            + " | ".join([
                cd["label"],
                f"{kw['kw_precision']:.4f}",
                f"{kw['kw_recall']:.4f}",
                f"{kw['kw_f1']:.4f}",
            ])
            + " |"
        )

    print()
    print("=== LEGEND ===")
    print("  JO µ  = Mean judge_overall (individual)")
    print("  JO Σ  = Sum of judge_overall")
    print("  TTR   = Type-Token Ratio (lexical diversity)")
    print("  EmbSim = Embedding cosine similarity (pred vs ref)")
    print("  TokF1  = Token F1 (exact token overlap)")
    print("  KeyF1  = Key Token F1 (important tokens)")
    print("  BiF1   = Bigram F1 (2-gram overlap)")
    print("  KW F1  = TF-IDF keyword overlap F1 (reference concepts covered)")
    print()
    print("  Embedding model: mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ (port 8001)")
    print("  Keyword extraction: TF-IDF on full corpus (all refs + all preds per candidate), top-30 terms per document")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
