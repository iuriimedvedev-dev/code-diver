import json
import sys

dataset_path = 'datasets/intellij_eval_1000.answer_sets.jsonl'
output_path = 'datasets/intellij_eval_mech150.jsonl'

buckets = {
    'config': [],
    'path': [],
    'symbol': [],
    'where': []
}

with open(dataset_path, 'r') as f:
    for line in f:
        case = json.loads(line)
        case_id = case.get('id', '')
        for bucket_name in buckets.keys():
            if case_id.startswith(f"{bucket_name}-"):
                buckets[bucket_name].append(case)
                break

# Sample 50 from each (or all if less than 50)
selected = []
for name, cases in buckets.items():
    limit = 50
    # The session note mentions "79" for where, let's keep it consistent with the note if possible
    # but the rule says 50/50/50. Actually the note says "150 cases, 50 config / 50 path / 50 symbol"
    # It doesn't mention 'where' in the 150 slice, but 'where' is critical for promotion.
    # Wait, the issue says: "overall + per-bucket (config/path/symbol/where) recall@10"
    # and "where-bucket improves".
    # I will take 50 config, 50 path, 50 symbol, and ALL where cases (78).
    
    if name == 'where':
        selected.extend(cases)
    else:
        selected.extend(cases[:50])

print(f"Selected {len(selected)} cases total.")
for name, cases in buckets.items():
    print(f"Bucket {name}: {len(cases)} total, selected {min(len(cases), 50 if name != 'where' else len(cases))}")

with open(output_path, 'w') as f:
    for case in selected:
        f.write(json.dumps(case) + '\n')
