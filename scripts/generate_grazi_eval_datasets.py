"""Convert Grazie question datasets to evaluation JSONL files."""

import json
from pathlib import Path


def convert_dataset(input_path: str, output_path: str, id_prefix: str) -> int:
    """Convert a question dataset to JSONL and return the number of examples."""
    dataset = json.loads(Path(input_path).read_text())
    questions = dataset["questions"]
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open("w") as file:
        for index, question in enumerate(questions):
            json.dump(
                {
                    "id": f"{id_prefix}-{index}",
                    "query": question["question"],
                    "expected": question["files"],
                },
                file,
            )
            file.write("\n")

    return len(questions)


if __name__ == "__main__":
    conversions = (
        (
            "/tmp/jbcontext_datasets/datasets/grazie-platform-commits-validated.json",
            "/tmp/grazie_platform_eval.jsonl",
            "grazie-commits",
        ),
        (
            "/tmp/jbcontext_datasets/datasets/grazie_platform_functions_small.json",
            "/tmp/grazie_platform_functions_small_eval.jsonl",
            "grazie-functions-small",
        ),
        (
            "/tmp/jbcontext_datasets/datasets/grazie-search-bench-modified.json",
            "/tmp/grazie_search_bench_modified_eval.jsonl",
            "grazie-search-bench",
        ),
    )

    for input_path, output_path, id_prefix in conversions:
        try:
            count = convert_dataset(input_path, output_path, id_prefix)
            print(f"Wrote {count} examples to {output_path}")
        except (OSError, KeyError, TypeError, ValueError) as error:
            print(f"Error converting {input_path}: {error}")
