# Code Explanation Judge

You are evaluating a developer-facing code explanation. Judge only the candidate
answer below. Use the source code as the primary truth. Use the reference
docstring as supporting truth, but do not require identical wording.

Score each criterion from 0 to 4:

- 4: excellent; materially correct and useful.
- 3: mostly correct; minor omissions or imprecision.
- 2: partially correct; important omissions or some vague/unsupported claims.
- 1: mostly wrong; small useful fragment, but major misunderstanding.
- 0: wrong, empty, unsafe, or hallucinated.

Return JSON only. Do not include markdown.

Required JSON shape:

{
  "criteria": {
    "purpose_accuracy": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason tied to code/reference"
    },
    "behavior_accuracy": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason tied to code/reference"
    },
    "api_contract": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason tied to code/reference"
    },
    "groundedness": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason tied to code/reference"
    },
    "specificity": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason tied to code/reference"
    },
    "completeness": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason tied to code/reference"
    },
    "clarity": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason tied to code/reference"
    }
  },
  "critical_issues": ["short issue, or empty list"],
  "rationale": "short final explanation of the judgment"
}

Criteria:

1. `purpose_accuracy`: Does the explanation correctly identify what the code is
   for?
2. `behavior_accuracy`: Does it accurately describe important control flow,
   transformations, branches, loops, calls, and returned behavior visible in the
   code?
3. `api_contract`: Does it correctly describe inputs, outputs, side effects,
   exceptions/errors, and externally visible contract when visible?
4. `groundedness`: Are all important claims supported by the code or reference?
   Penalize invented dependencies, hidden behavior, or unsupported intent.
5. `specificity`: Does it mention concrete names and concepts from this code
   rather than generic filler?
6. `completeness`: Does it cover the important behavior a developer would need
   to understand or modify the code?
7. `clarity`: Is it concise, readable, and organized for a developer?

User prompt:
{{user_prompt}}

Function metadata:
{{metadata_json}}

Code:
```python
{{code}}
```

Reference docstring:
{{reference}}

Candidate explanation:
{{prediction}}
