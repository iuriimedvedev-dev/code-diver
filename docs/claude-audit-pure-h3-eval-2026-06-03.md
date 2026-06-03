# Claude Audit Status - 2026-06-03

Claude Code audit was requested for the final Pure H3 setup and evaluation validity.

## Attempted Command

```bash
cat <<'PROMPT' | claude -p --model claude-opus-4-8 --effort xhigh --max-budget-usd 25 --permission-mode bypassPermissions --allowedTools "Read,Grep,Glob,Bash" > docs/claude-audit-pure-h3-eval-2026-06-03.md
Audit this repository's final code-search setup. Focus on: Pure H3 default profile, MTEB CodeSearchNet benchmark integration, evaluate command reproducibility, metric validity, risks that make our eval numbers untrustworthy, and concrete fixes. Do not edit files. Write a concise but detailed audit with ranked findings, evidence paths, and recommendations.
PROMPT
```

## Result

The audit did not run because Claude Code is not authenticated in this shell:

```text
Not logged in · Please run /login
```

No Claude findings were produced. This file is a status record, not an audit result.

## Follow-Up

Run `/login` in Claude Code, then rerun the command above. Until that succeeds, rely on the local eval-validity notes and the CodeSearchNet market comparison report.
