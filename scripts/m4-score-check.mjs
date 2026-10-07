import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const report = JSON.parse(readFileSync('.tmp/m4-qa/pier.json', 'utf8'));
const response = report.responses.find(call => call.name === '10000-char-search');
const results = JSON.parse(response.response.result.content[0].text);
console.log('long-query scores:', results.map(result => result.score));
assert.ok(results.every((result, index) => index === 0 || results[index - 1].score >= result.score),
  'M4 returned results are not descending by exposed score');