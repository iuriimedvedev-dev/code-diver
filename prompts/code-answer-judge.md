# Code Answer Judge

You are evaluating an answer to a repository-level code question.

Use the reference answer as ground truth. Use the retrieved context to check
whether the candidate answer is grounded. Do not reward plausible claims that
are absent from both the reference and context.

Score each criterion from 0 to 4:

- 4: excellent; materially correct and useful.
- 3: mostly correct; minor omissions or imprecision.
- 2: partially correct; important omissions or some unsupported claims.
- 1: mostly wrong; one useful fragment, but major misunderstanding.
- 0: wrong, empty, unsafe, or hallucinated.

Classify the candidate answer's `answer_type`:

- `substantive`: the answer asserts something about the codebase.
- `abstention`: the answer explicitly declines (says it cannot determine the
  answer, lacks sufficient context, or could not find the relevant code) and
  makes no substantive claim about the codebase.
- `empty`: the answer is blank, whitespace, or contains no assertion at all.

An abstention is NOT a good answer when the reference contains a real answer.
Score answer_correctness, evidence_grounding, coverage, citation_quality and
specificity all 0 for an abstention. hallucination_control may remain high
because nothing was fabricated.

Return JSON only. Do not include markdown.

Required JSON shape:

{
  "answer_type": "substantive | abstention | empty",
  "criteria": {
    "answer_correctness": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason"
    },
    "evidence_grounding": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason"
    },
    "coverage": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason"
    },
    "citation_quality": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason"
    },
    "specificity": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason"
    },
    "hallucination_control": {
      "score": 0,
      "answer": "yes | mostly | partially | no",
      "evidence": "brief reason"
    }
  },
  "critical_issues": ["short issue, or empty list"],
  "rationale": "short final explanation of the judgment"
}

Criteria:

1. `answer_correctness`: Does the answer directly and correctly answer the
   user question?
2. `evidence_grounding`: Are the important claims supported by retrieved code
   context or the reference answer?
3. `coverage`: Does it cover the important files, classes, methods, behaviors,
   and relationships required by the reference?
4. `citation_quality`: Are cited files and line ranges useful and consistent
   with the evidence?
5. `specificity`: Does it use concrete code names and responsibilities rather
   than generic filler?
6. `hallucination_control`: Does it avoid invented APIs, files, line numbers,
   side effects, or architecture?

Question:
{{question}}

Case metadata:
{{metadata_json}}

Retrieved context:
{{context}}

Reference answer:
{{reference}}

Candidate answer:
{{prediction}}
