import json

def analyze_report(path):
    with open(path, 'r') as f:
        data = json.load(f)
    
    results = data['results']
    buckets = {}
    
    for res in results:
        case_id = res['case_id']
        bucket = 'unknown'
        if case_id.startswith('config-'): bucket = 'config'
        elif case_id.startswith('path-'): bucket = 'path'
        elif case_id.startswith('symbol-'): bucket = 'symbol'
        elif case_id.startswith('where-'): bucket = 'where'
        
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append(res)
    
    overall_recall = sum(r['file_recall'] for r in results) / len(results)
    overall_mrr = sum(r['file_reciprocal_rank'] for r in results) / len(results)
    
    bucket_metrics = {}
    for name, res_list in buckets.items():
        recall = sum(r['file_recall'] for r in res_list) / len(res_list)
        mrr = sum(r['file_reciprocal_rank'] for r in res_list) / len(res_list)
        bucket_metrics[name] = {'recall': recall, 'mrr': mrr, 'n': len(res_list)}
        
    return {
        'overall': {'recall': overall_recall, 'mrr': overall_mrr, 'n': len(results)},
        'buckets': bucket_metrics
    }

h83 = analyze_report('h83_results.json')
champion = analyze_report('champion_results.json')

print("Gate Results Table (Recall@10)")
print(f"{'bucket':<10} | {'champion':<10} | {'H-83':<10} | {'delta':<10}")
print("-" * 50)

def print_row(name, champ_val, h83_val):
    delta = h83_val - champ_val
    print(f"{name:<10} | {champ_val:.4f}     | {h83_val:.4f}     | {delta:+.4f}")

print_row('overall', champion['overall']['recall'], h83['overall']['recall'])
for b in ['config', 'path', 'symbol', 'where']:
    print_row(b, champion['buckets'][b]['recall'], h83['buckets'][b]['recall'])

print("\nGate Results Table (MRR)")
print(f"{'bucket':<10} | {'champion':<10} | {'H-83':<10} | {'delta':<10}")
print("-" * 50)
print_row('overall', champion['overall']['mrr'], h83['overall']['mrr'])
for b in ['config', 'path', 'symbol', 'where']:
    print_row(b, champion['buckets'][b]['mrr'], h83['buckets'][b]['mrr'])

# Check criteria
print("\nPromotion Criteria Check:")
regressed_buckets = []
for b in ['config', 'path', 'symbol']:
    if h83['buckets'][b]['recall'] < champion['buckets'][b]['recall'] - 0.01:
        regressed_buckets.append(b)

overall_drop = champion['overall']['recall'] - h83['overall']['recall']
where_improved = h83['buckets']['where']['recall'] > champion['buckets']['where']['recall']

print(f"(a) Overall recall@10 drop <= 0.005: {'PASS' if overall_drop <= 0.005 else 'FAIL'} ({overall_drop:+.4f})")
print(f"(b) No individual bucket regresses > 0.01: {'PASS' if not regressed_buckets else 'FAIL'} ({', '.join(regressed_buckets) if regressed_buckets else 'none'})")
print(f"(c) where-bucket improves: {'PASS' if where_improved else 'FAIL'} (champ: {champion['buckets']['where']['recall']:.4f}, h83: {h83['buckets']['where']['recall']:.4f})")

if overall_drop <= 0.005 and not regressed_buckets and where_improved:
    print("\nVERDICT: PROMOTED")
else:
    print("\nVERDICT: REJECTED")
