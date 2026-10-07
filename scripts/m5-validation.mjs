import { spawn } from 'node:child_process';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve, relative, isAbsolute } from 'node:path';
import { performance } from 'node:perf_hooks';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const PREFIX = 'Represent this code search query for retrieving relevant files: ';
const PIER = '/Users/iurii.medvedev/Work/sre-support-pier/tmp/rust-pier';
const LIMIT = 34;

function normalize(path) {
  return path.replaceAll('\\', '/').replace(/^\.\//, '');
}

export function expectedPaths(query) {
  const files = query.expected_files ?? query.expected;
  assert.ok(Array.isArray(files) && files.length && files.every(p => typeof p === 'string' && p.length), 'expected files required');
  return files.map(file => {
    const path = normalize(file), repo = normalize(query.repo ?? '');
    return repo && !path.startsWith(`${repo}/`) ? `${repo}/${path}` : path;
  });
}

export function decode(response, stderrFailed = false) {
  if (response.error || response.result?.isError) {
    const rerank = /rerank|cross.encoder/i.test(JSON.stringify(response));
    return { ok: false, failure: rerank ? 'rerank_failure' : 'rpc_or_tool_error' };
  }
  const content = response.result?.content;
  if (!Array.isArray(content)) return { ok: false, failure: 'invalid_response' };
  let results, metadata = [], warning = false;
  const structured = response.result?.structuredContent;
  if (structured && typeof structured === 'object') {
    metadata.push(structured);
    if (structured.state && typeof structured.state === 'object') metadata.push(structured.state);
    if (Array.isArray(structured.results)) results = structured.results;
  }
  for (const block of content) {
    if (block.type !== 'text') continue;
    try {
      const value = JSON.parse(block.text);
      if (Array.isArray(value)) { results = value; metadata.push(...value); }
      else if (value && typeof value === 'object') {
        metadata.push(value);
        if (Array.isArray(value.results)) { results = value.results; metadata.push(...results); }
      }
    } catch {
      if (/rerank|degrad|cross.encoder/i.test(block.text)) warning = true;
    }
  }
  metadata = metadata.filter(v => v && typeof v === 'object');
  if (stderrFailed || warning || metadata.some(v => v.rerank_applied === false || v.rerank_second_pass_failed === true || v.rerank_error)) {
    return { ok: false, failure: 'rerank_failure' };
  }
  if (!results || results.some(v => !v || typeof v.path !== 'string')) return { ok: false, failure: 'invalid_results' };
  if (!metadata.some(v => v.rerank_applied === true)) return { ok: false, failure: 'rerank_unconfirmed' };
  return { ok: true, paths: results.map(v => normalize(v.path)), rerankMetadataPresent: metadata.some(v => 'rerank_applied' in v) };
}

function latency(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const percentile = p => sorted.length ? sorted[Math.ceil(p * sorted.length) - 1] : null;
  return { count: values.length, meanMs: values.length ? values.reduce((a, b) => a + b, 0) / values.length : null,
    p50Ms: percentile(0.5), p95Ms: percentile(0.95) };
}

export function summarize(pairs) {
  const included = pairs.filter(p => p.off.ok && p.on.ok);
  const sides = {};
  for (const side of ['off', 'on']) {
    const failures = {};
    for (const pair of pairs) if (!pair[side].ok) {
      const reason = pair[side].failure;
      failures[reason] = (failures[reason] ?? 0) + 1;
    }
    sides[side] = { failures, failureCount: pairs.filter(p => !p[side].ok).length,
      hits: Object.fromEntries([1, 5, 10].map(k => {
        const count = included.filter(p => p[side].paths.slice(0, k).some(path => p.expected.includes(path))).length;
        return [`hit@${k}`, { count, denominator: included.length, percent: included.length ? 100 * count / included.length : null }];
      })), pairedLatency: latency(included.map(p => p[side].ms)), allAttemptLatency: latency(pairs.map(p => p[side].ms)) };
  }
  return { attemptedPairs: pairs.length, includedPairs: included.length, excludedPairs: pairs.length - included.length, sides };
}

function client(executable, args, timeoutMs) {
  const child = spawn(executable, args, { stdio: ['pipe', 'pipe', 'pipe'] });
  const pending = new Map();
  let seq = 0, buffer = '', dead = false, stderrTail = '', rerankFailure = false;
  const closed = new Promise(resolveClose => child.once('close', resolveClose));
  function fail() {
    dead = true;
    for (const p of pending.values()) { clearTimeout(p.timer); p.reject(new Error('process_failure')); }
    pending.clear();
  }
  child.on('error', fail);
  child.on('exit', fail);
  child.stdin.on('error', fail);
  child.stderr.on('data', data => {
    stderrTail = (stderrTail + data.toString()).slice(-4096);
    if (/(rerank|cross.encoder)[^\n]*(fail|error|degrad)|(?:fail|error|degrad)[^\n]*rerank/i.test(stderrTail)) rerankFailure = true;
  });
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', data => {
    buffer += data;
    while (buffer.includes('\n')) {
      const index = buffer.indexOf('\n'), line = buffer.slice(0, index);
      buffer = buffer.slice(index + 1);
      if (!line.trim()) continue;
      let response;
      try { response = JSON.parse(line); } catch { fail(); child.kill(); return; }
      const p = pending.get(response.id);
      if (!p) continue;
      pending.delete(response.id); clearTimeout(p.timer); p.resolve(response);
    }
  });
  function rpc(method, params = {}) {
    if (dead) return Promise.reject(new Error('process_failure'));
    const id = ++seq;
    return new Promise((resolveRpc, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id); reject(new Error('timeout')); fail(); child.kill();
      }, timeoutMs);
      pending.set(id, { resolve: resolveRpc, reject, timer });
      child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  }
  return {
    async initialize() {
      const response = await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'm5-validation', version: '1' } });
      assert.ok(response.result?.serverInfo && !response.error, 'initialize failed');
      child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
      const tools = await rpc('tools/list');
      assert.ok(tools.result?.tools.some(t => t.name === 'code_diver_search'), 'search tool missing');
      return response.result.serverInfo;
    },
    async search(query) {
      rerankFailure = false; stderrTail = '';
      const start = performance.now();
      try {
        const response = await rpc('tools/call', { name: 'code_diver_search', arguments: { query, limit: LIMIT, preview_chars: 0 } });
        return { ...decode(response, rerankFailure), ms: performance.now() - start };
      } catch (error) {
        return { ok: false, failure: error.message === 'timeout' ? 'timeout' : 'process_failure', ms: performance.now() - start };
      }
    },
    async close() {
      child.stdin.end();
      const timer = setTimeout(() => child.kill('SIGKILL'), 2000);
      await closed; clearTimeout(timer);
    },
  };
}

function options(argv) {
  const split = argv.indexOf('--');
  const own = split < 0 ? argv : argv.slice(0, split), common = split < 0 ? [] : argv.slice(split + 1);
  const opts = { queries: `${PIER}/queries80.json`, output: '.tmp/m5-prefix/results.json', prefixFlag: '--embedding-query-prefix', timeoutMs: 180000, warmup: 1 };
  for (let i = 0; i < own.length; i += 2) {
    const key = { '--executable': 'executable', '--queries': 'queries', '--output': 'output', '--prefix-flag': 'prefixFlag', '--timeout-ms': 'timeoutMs', '--warmup': 'warmup' }[own[i]];
    assert.ok(key && own[i + 1] !== undefined, 'unknown option or missing value');
    opts[key] = ['timeoutMs', 'warmup'].includes(key) ? Number(own[i + 1]) : own[i + 1];
  }
  assert.ok(opts.executable, '--executable required');
  assert.ok(Number.isInteger(opts.timeoutMs) && opts.timeoutMs > 0 && Number.isInteger(opts.warmup) && opts.warmup >= 0, 'invalid numeric option');
  assert.ok(/^--[a-z-]+$/.test(opts.prefixFlag), 'invalid prefix flag');
  assert.ok(!common.some(v => v === opts.prefixFlag || v.startsWith(`${opts.prefixFlag}=`)), 'prefix is controlled by harness');
  assert.ok(!common.some(v => /(?:api-key|bearer|token|password|secret)/i.test(v)), 'pass credentials via environment, not command flags');
  const output = relative(resolve('.tmp'), resolve(opts.output));
  assert.ok(output && !output.startsWith('..') && !isAbsolute(output), 'output must be under .tmp/');
  return { ...opts, common };
}

async function main() {
  const opts = options(process.argv.slice(2));
  const queries = JSON.parse(readFileSync(opts.queries, 'utf8'));
  assert.ok(Array.isArray(queries) && queries.length === 80, 'exactly 80 queries required');
  for (const q of queries) { assert.ok(typeof q.query === 'string' && q.query.trim(), 'query required'); expectedPaths(q); }
  mkdirSync(resolve(opts.output, '..'), { recursive: true });
  const clients = {}, pairs = [], warmup = {}, servers = {};
  const save = () => writeFileSync(opts.output, JSON.stringify({ prefix: PREFIX, prefixFlag: opts.prefixFlag, limit: LIMIT,
    queryCount: queries.length, protocol: 'persistent MCP, alternating off/on then on/off, require-rerank', servers, warmup,
    summary: summarize(pairs), pairs }, null, 2));
  try {
    for (const side of ['off', 'on']) {
      clients[side] = client(opts.executable, ['mcp', ...opts.common, '--require-rerank', `${opts.prefixFlag}=${side === 'on' ? PREFIX : ''}`], opts.timeoutMs);
      servers[side] = await clients[side].initialize();
      warmup[side] = [];
      for (let i = 0; i < opts.warmup; i++) warmup[side].push(await clients[side].search(queries[i % queries.length].query));
    }
    for (let i = 0; i < queries.length; i++) {
      const q = queries[i], order = i % 2 ? ['on', 'off'] : ['off', 'on'];
      const pair = { index: i, id: q.id ?? i, expected: expectedPaths(q), order };
      for (const side of order) pair[side] = await clients[side].search(q.query);
      pairs.push(pair); save();
      console.log(JSON.stringify({ completed: pairs.length, included: pair.off.ok && pair.on.ok }));
    }
    console.log(JSON.stringify(summarize(pairs), null, 2));
    if (pairs.some(p => !p.off.ok || !p.on.ok)) process.exitCode = 1;
  } finally {
    save(); await Promise.all(Object.values(clients).map(c => c.close()));
  }
}

function selfTest() {
  assert.deepEqual(expectedPaths({ expected: ['a.go'], repo: 'repos/example' }), ['repos/example/a.go']);
  assert.deepEqual(expectedPaths({ expected_files: ['repos/example/a.go'], repo: 'repos/example' }), ['repos/example/a.go']);
  const response = value => ({ result: { content: [{ type: 'text', text: JSON.stringify(value) }] } });
  assert.equal(decode(response([{ path: 'a', rerank_applied: false }])).failure, 'rerank_failure');
  assert.equal(decode(response({ results: [{ path: 'a' }], rerank_second_pass_failed: true })).ok, false);
  assert.equal(decode(response([{ path: 'a' }]), true).ok, false);
  assert.equal(decode({ result: { isError: true } }).ok, false);
  assert.equal(decode({ result: { isError: true, content: [{ type: 'text', text: 'rerank failed' }] } }).failure, 'rerank_failure');
  assert.equal(decode(response([null])).failure, 'invalid_results');
  assert.deepEqual(decode(response({ results: [{ path: 'a' }], rerank_applied: true })).paths, ['a']);
  assert.equal(decode(response([{ path: 'a' }])).failure, 'rerank_unconfirmed');
  const structured = { result: { structuredContent: { results: [{ path: 'a' }], rerank_applied: true }, content: [] } };
  assert.deepEqual(decode(structured).paths, ['a']);
  structured.result.structuredContent.rerank_error = 'failed';
  assert.equal(decode(structured).failure, 'rerank_failure');
  structured.result.structuredContent = { results: [{ path: 'a' }], state: { rerank_applied: true } };
  assert.equal(decode(structured).ok, true);
  const ok = { ok: true, paths: ['a'], ms: 10 }, bad = { ok: false, failure: 'rerank_failure', ms: 20 };
  const summary = summarize([{ expected: ['a'], off: ok, on: ok }, { expected: ['a'], off: ok, on: bad }]);
  assert.equal(summary.includedPairs, 1);
  assert.deepEqual(summary.sides.off.hits['hit@1'], { count: 1, denominator: 1, percent: 100 });
  assert.equal(summary.sides.on.failureCount, 1);
  const fifth = { ok: true, paths: ['b', 'c', 'd', 'e', 'a'], ms: 30 };
  const ranked = summarize([{ expected: ['a'], off: fifth, on: ok }]);
  assert.equal(ranked.sides.off.hits['hit@1'].count, 0);
  assert.equal(ranked.sides.off.hits['hit@5'].count, 1);
  assert.equal(ranked.sides.off.hits['hit@10'].count, 1);
  assert.equal(summarize([]).sides.off.hits['hit@10'].percent, null);
  assert.throws(() => options(['--executable', 'x', '--output', 'results.json']));
  console.log('m5-validation self-test passed');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (process.argv.includes('--self-test')) selfTest();
  else main().catch(() => { console.error('M5 harness failed; check executable, flags, inputs and service availability (details suppressed to protect credentials).'); process.exitCode = 1; });
}