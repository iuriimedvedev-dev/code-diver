import { spawn } from "node:child_process";
import { appendFile, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Box, Text } from "@earendil-works/pi-tui";

type ToolContext = {
  cwd: string;
};

type CommandResult = {
  stdout: string;
  stderr: string;
};

const MAX_TOOL_OUTPUT = 40_000;

type SearchProbe = {
  query: string;
  limit?: number;
};

type TextProbe = {
  pattern: string;
  path?: string;
  limit?: number;
};

type TreeProbe = {
  path?: string;
  depth?: number;
  limit?: number;
};

type ReadProbe = {
  file: string;
  startLine?: number;
  lines?: number;
};

type SymbolsProbe = {
  path?: string;
  limit?: number;
};

type SelectedIndexItem = {
  path: string;
  startLine?: number;
  endLine?: number;
  title?: string;
  reason?: string;
  kind?: string;
};

type FailureFeedback = {
  query: string;
  correction: string;
  actual?: string;
  expected?: string;
  files?: string[];
  notes?: string;
};

type SuccessFeedback = {
  query: string;
  answer: string;
  files?: string[];
  symbols?: string[];
  notes?: string;
};

export default function (pi: ExtensionAPI) {
  registerCodeDiverWelcome(pi);

  pi.registerTool({
    name: "code_diver_index",
    label: "Code Diver Index",
    description: "Build or refresh the Code Diver retrieval artifact for this repository.",
    parameters: Type.Object({}),
    ...compactToolUi("index"),
    execute: async (_toolCallId, _params, signal, _onUpdate, ctx: ToolContext) => {
      const result = await runCodeDiver(ctx.cwd, ["index"], signal);
      return textResult(result.stdout || result.stderr || "Index completed.");
    },
  });

  pi.registerTool({
    name: "code_diver_index_selected",
    label: "Code Diver Index Selected",
    description:
      "Persist AI-selected repository file ranges into the configured local vector store. Accepts paths and line ranges only; the CLI reads files itself.",
    ...compactToolUi("index selected"),
    parameters: Type.Object({
      items: Type.Array(
        Type.Object({
          path: Type.String({ description: "Relative file path inside the repository." }),
          startLine: Type.Optional(Type.Integer({ minimum: 1, description: "First line to index." })),
          endLine: Type.Optional(Type.Integer({ minimum: 1, description: "Last line to index." })),
          title: Type.Optional(Type.String({ description: "Short stable title for this code item." })),
          reason: Type.Optional(Type.String({ description: "Why this range is useful for retrieval." })),
          kind: Type.Optional(Type.String({ description: "Optional kind such as entrypoint, api, config, model, test." })),
        }),
        { minItems: 1, maxItems: 200 },
      ),
    }),
    execute: async (_toolCallId, params: { items: SelectedIndexItem[] }, signal, _onUpdate, ctx: ToolContext) => {
      const result = await runCodeDiver(ctx.cwd, ["index-selected", "--json"], signal, JSON.stringify(params));
      return textResult(result.stdout || result.stderr || "Selected index completed.");
    },
  });

  pi.registerTool({
    name: "code_diver_search",
    label: "Code Diver Search",
    description: "Search the Code Diver retrieval index for repository context relevant to a query.",
    ...compactToolUi("search"),
    parameters: Type.Object({
      query: Type.String({ description: "Natural language search query." }),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 25, description: "Maximum number of results." })),
    }),
    execute: async (_toolCallId, params: { query: string; limit?: number }, signal, _onUpdate, ctx: ToolContext) => {
      const args = ["search", params.query, "--json"];
      if (params.limit) {
        args.push("--limit", String(params.limit));
      }
      const result = await runCodeDiver(ctx.cwd, args, signal);
      return textResult(result.stdout);
    },
  });

  pi.registerTool({
    name: "code_diver_inspect",
    label: "Code Diver Inspect",
    description:
      "Run multiple independent read-only repository probes concurrently: vector searches, regex searches, literal greps, and tree reads.",
    ...compactToolUi("inspect"),
    parameters: Type.Object({
      searches: Type.Optional(
        Type.Array(
          Type.Object({
            query: Type.String({ description: "Natural language search query." }),
            limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 25, description: "Maximum number of results." })),
          }),
          { maxItems: 8 },
        ),
      ),
      regexes: Type.Optional(
        Type.Array(
          Type.Object({
            pattern: Type.String({ description: "Regex pattern to search for." }),
            path: Type.Optional(Type.String({ description: "Relative path inside the repository." })),
            limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, description: "Maximum number of matches." })),
          }),
          { maxItems: 8 },
        ),
      ),
      literals: Type.Optional(
        Type.Array(
          Type.Object({
            pattern: Type.String({ description: "Literal text to search for." }),
            path: Type.Optional(Type.String({ description: "Relative path inside the repository." })),
            limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, description: "Maximum number of matches." })),
          }),
          { maxItems: 8 },
        ),
      ),
      trees: Type.Optional(
        Type.Array(
          Type.Object({
            path: Type.Optional(Type.String({ description: "Relative path inside the repository." })),
            depth: Type.Optional(Type.Integer({ minimum: 1, maximum: 10, description: "Maximum tree depth." })),
            limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, description: "Maximum number of entries." })),
          }),
          { maxItems: 8 },
        ),
      ),
      reads: Type.Optional(
        Type.Array(
          Type.Object({
            file: Type.String({ description: "Relative file path inside the repository." }),
            startLine: Type.Optional(Type.Integer({ minimum: 1, description: "First line to read." })),
            lines: Type.Optional(Type.Integer({ minimum: 1, maximum: 400, description: "Number of lines to read." })),
          }),
          { maxItems: 8 },
        ),
      ),
      symbols: Type.Optional(
        Type.Array(
          Type.Object({
            path: Type.Optional(Type.String({ description: "Relative path inside the repository." })),
            limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, description: "Maximum number of symbols." })),
          }),
          { maxItems: 8 },
        ),
      ),
    }),
    execute: async (
      _toolCallId,
      params: {
        searches?: SearchProbe[];
        regexes?: TextProbe[];
        literals?: TextProbe[];
        trees?: TreeProbe[];
        reads?: ReadProbe[];
        symbols?: SymbolsProbe[];
      },
      signal,
      _onUpdate,
      ctx: ToolContext,
    ) => {
      const tasks: Array<Promise<string>> = [];
      for (const search of params.searches ?? []) {
        const args = ["search", search.query, "--json"];
        if (search.limit) {
          args.push("--limit", String(search.limit));
        }
        tasks.push(labelResult(`search: ${search.query}`, runCodeDiver(ctx.cwd, args, signal)));
      }
      for (const regex of params.regexes ?? []) {
        const args = ["rg", regex.pattern];
        appendPathAndLimit(args, regex.path, regex.limit);
        tasks.push(labelResult(`rg: ${regex.pattern}`, runCodeDiver(ctx.cwd, args, signal)));
      }
      for (const literal of params.literals ?? []) {
        const args = ["grep", literal.pattern];
        appendPathAndLimit(args, literal.path, literal.limit);
        tasks.push(labelResult(`grep: ${literal.pattern}`, runCodeDiver(ctx.cwd, args, signal)));
      }
      for (const tree of params.trees ?? []) {
        const args = ["tree"];
        if (tree.path) {
          args.push("--path", tree.path);
        }
        if (tree.depth) {
          args.push("--depth", String(tree.depth));
        }
        if (tree.limit) {
          args.push("--limit", String(tree.limit));
        }
        tasks.push(labelResult(`tree: ${tree.path ?? "."}`, runCodeDiver(ctx.cwd, args, signal)));
      }
      for (const read of params.reads ?? []) {
        const args = ["read", read.file];
        if (read.startLine) {
          args.push("--start-line", String(read.startLine));
        }
        if (read.lines) {
          args.push("--lines", String(read.lines));
        }
        tasks.push(labelResult(`read: ${read.file}`, runCodeDiver(ctx.cwd, args, signal)));
      }
      for (const symbol of params.symbols ?? []) {
        const args = ["symbols"];
        appendPathAndLimit(args, symbol.path, symbol.limit);
        tasks.push(labelResult(`symbols: ${symbol.path ?? "."}`, runCodeDiver(ctx.cwd, args, signal)));
      }
      if (!tasks.length) {
        return textResult("No probes requested.");
      }
      return textResult((await Promise.all(tasks)).join("\n\n"));
    },
  });

  pi.registerTool({
    name: "code_diver_open",
    label: "Code Diver Open",
    description: "Open the best Code Diver search result in the configured editor.",
    ...compactToolUi("open"),
    parameters: Type.Object({
      query: Type.String({ description: "Natural language search query." }),
      rank: Type.Optional(Type.Integer({ minimum: 1, maximum: 25, description: "Search result rank to open." })),
    }),
    execute: async (_toolCallId, params: { query: string; rank?: number }, signal, _onUpdate, ctx: ToolContext) => {
      const args = ["open", params.query];
      if (params.rank) {
        args.push("--rank", String(params.rank));
      }
      const result = await runCodeDiver(ctx.cwd, args, signal);
      return textResult(result.stdout || result.stderr);
    },
  });

  pi.registerTool({
    name: "code_diver_evaluate",
    label: "Code Diver Evaluate",
    description: "Run the configured retrieval evaluation dataset and report metrics.",
    ...compactToolUi("evaluate"),
    parameters: Type.Object({
      details: Type.Optional(Type.Boolean({ description: "Include per-case retrieval details." })),
      reindex: Type.Optional(Type.Boolean({ description: "Rebuild the index before evaluation." })),
    }),
    execute: async (_toolCallId, params: { details?: boolean; reindex?: boolean }, signal, _onUpdate, ctx: ToolContext) => {
      const args = ["evaluate"];
      if (params.details) {
        args.push("--details");
      }
      if (params.reindex) {
        args.push("--reindex");
      }
      const result = await runCodeDiver(ctx.cwd, args, signal);
      return textResult(result.stdout || result.stderr);
    },
  });

  pi.registerTool({
    name: "code_diver_experiment",
    label: "Code Diver Experiment",
    description: "Run configured retrieval hypotheses and record metrics when metrics storage is enabled.",
    ...compactToolUi("experiment"),
    parameters: Type.Object({
      reindex: Type.Optional(Type.Boolean({ description: "Rebuild the index before running hypotheses." })),
    }),
    execute: async (_toolCallId, params: { reindex?: boolean }, signal, _onUpdate, ctx: ToolContext) => {
      const args = ["experiment"];
      if (params.reindex) {
        args.push("--reindex");
      }
      const result = await runCodeDiver(ctx.cwd, args, signal);
      return textResult(result.stdout || result.stderr);
    },
  });

  pi.registerTool({
    name: "code_diver_tree",
    label: "Code Diver Tree",
    description: "Read-only, gitignore-aware repository tree. Does not edit files.",
    ...compactToolUi("tree"),
    parameters: Type.Object({
      path: Type.Optional(Type.String({ description: "Relative path inside the repository." })),
      depth: Type.Optional(Type.Integer({ minimum: 1, maximum: 10, description: "Maximum tree depth." })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, description: "Maximum number of entries." })),
    }),
    execute: async (_toolCallId, params: { path?: string; depth?: number; limit?: number }, signal, _onUpdate, ctx: ToolContext) => {
      const args = ["tree"];
      if (params.path) {
        args.push("--path", params.path);
      }
      if (params.depth) {
        args.push("--depth", String(params.depth));
      }
      if (params.limit) {
        args.push("--limit", String(params.limit));
      }
      const result = await runCodeDiver(ctx.cwd, args, signal);
      return textResult(result.stdout || result.stderr);
    },
  });

  pi.registerTool({
    name: "code_diver_grep",
    label: "Code Diver Grep",
    description: "Read-only, gitignore-aware literal text search. Does not edit files.",
    ...compactToolUi("grep"),
    parameters: Type.Object({
      pattern: Type.String({ description: "Literal text to search for." }),
      path: Type.Optional(Type.String({ description: "Relative path inside the repository." })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, description: "Maximum number of matches." })),
    }),
    execute: async (_toolCallId, params: { pattern: string; path?: string; limit?: number }, signal, _onUpdate, ctx: ToolContext) => {
      const args = ["grep", params.pattern];
      if (params.path) {
        args.push("--path", params.path);
      }
      if (params.limit) {
        args.push("--limit", String(params.limit));
      }
      const result = await runCodeDiver(ctx.cwd, args, signal);
      return textResult(result.stdout || result.stderr);
    },
  });

  pi.registerTool({
    name: "code_diver_rg",
    label: "Code Diver Rg",
    description: "Read-only, gitignore-aware regex text search using ripgrep when available. Does not edit files.",
    ...compactToolUi("rg"),
    parameters: Type.Object({
      pattern: Type.String({ description: "Regex pattern to search for." }),
      path: Type.Optional(Type.String({ description: "Relative path inside the repository." })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, description: "Maximum number of matches." })),
    }),
    execute: async (_toolCallId, params: { pattern: string; path?: string; limit?: number }, signal, _onUpdate, ctx: ToolContext) => {
      const args = ["rg", params.pattern];
      if (params.path) {
        args.push("--path", params.path);
      }
      if (params.limit) {
        args.push("--limit", String(params.limit));
      }
      const result = await runCodeDiver(ctx.cwd, args, signal);
      return textResult(result.stdout || result.stderr);
    },
  });

  pi.registerTool({
    name: "code_diver_read",
    label: "Code Diver Read",
    description: "Read-only bounded source excerpt with line numbers. Does not edit files.",
    ...compactToolUi("read"),
    parameters: Type.Object({
      file: Type.String({ description: "Relative file path inside the repository." }),
      startLine: Type.Optional(Type.Integer({ minimum: 1, description: "First line to read." })),
      lines: Type.Optional(Type.Integer({ minimum: 1, maximum: 400, description: "Number of lines to read." })),
    }),
    execute: async (_toolCallId, params: { file: string; startLine?: number; lines?: number }, signal, _onUpdate, ctx: ToolContext) => {
      const args = ["read", params.file];
      if (params.startLine) {
        args.push("--start-line", String(params.startLine));
      }
      if (params.lines) {
        args.push("--lines", String(params.lines));
      }
      const result = await runCodeDiver(ctx.cwd, args, signal);
      return textResult(result.stdout || result.stderr);
    },
  });

  pi.registerTool({
    name: "code_diver_symbols",
    label: "Code Diver Symbols",
    description: "Read-only symbol listing for source files. Useful before precise grep/read probes.",
    ...compactToolUi("symbols"),
    parameters: Type.Object({
      path: Type.Optional(Type.String({ description: "Relative path inside the repository." })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, description: "Maximum number of symbols." })),
    }),
    execute: async (_toolCallId, params: { path?: string; limit?: number }, signal, _onUpdate, ctx: ToolContext) => {
      const args = ["symbols"];
      appendPathAndLimit(args, params.path, params.limit);
      const result = await runCodeDiver(ctx.cwd, args, signal);
      return textResult(result.stdout || result.stderr);
    },
  });

  pi.registerTool({
    name: "code_diver_record_failure",
    label: "Code Diver Record Failure",
    description:
      "Record a retrieval failure case when the user explicitly says the answer/search result was wrong, missing, or not what they meant. Writes only Code Diver feedback artifacts.",
    ...compactToolUi("record failure"),
    parameters: Type.Object({
      query: Type.String({ description: "The user's original or current repository question." }),
      correction: Type.String({ description: "What the user said was wrong, missing, or should be found instead." }),
      actual: Type.Optional(Type.String({ description: "Short summary of the wrong result or answer." })),
      expected: Type.Optional(Type.String({ description: "Expected file, symbol, behavior, or intent if known." })),
      files: Type.Optional(
        Type.Array(Type.String({ description: "Relevant file paths mentioned by user or discovered later." }), {
          maxItems: 20,
        }),
      ),
      notes: Type.Optional(Type.String({ description: "Extra concise debugging notes." })),
    }),
    execute: async (_toolCallId, params: FailureFeedback, _signal, _onUpdate, ctx: ToolContext) => {
      const path = await recordFailure(ctx.cwd, params);
      return textResult(`Recorded failure feedback: ${path}`);
    },
  });

  pi.registerTool({
    name: "code_diver_record_success",
    label: "Code Diver Record Success",
    description:
      "Record a confirmed successful code search/explanation when the user explicitly says the answer or found location is correct. Writes only Code Diver feedback artifacts.",
    ...compactToolUi("record success"),
    parameters: Type.Object({
      query: Type.String({ description: "The user's repository question that was answered correctly." }),
      answer: Type.String({ description: "Short summary of the correct answer or found location." }),
      files: Type.Optional(
        Type.Array(Type.String({ description: "Confirmed relevant file paths." }), {
          maxItems: 20,
        }),
      ),
      symbols: Type.Optional(
        Type.Array(Type.String({ description: "Confirmed relevant classes, functions, methods, or symbols." }), {
          maxItems: 20,
        }),
      ),
      notes: Type.Optional(Type.String({ description: "Extra concise notes about why this was successful." })),
    }),
    execute: async (_toolCallId, params: SuccessFeedback, _signal, _onUpdate, ctx: ToolContext) => {
      const path = await recordSuccess(ctx.cwd, params);
      return textResult(`Recorded success feedback: ${path}`);
    },
  });
}

function registerCodeDiverWelcome(pi: ExtensionAPI) {
  pi.registerMessageRenderer("code-diver-welcome", (message, _options, theme) => {
    const text = new Text(typeof message.content === "string" ? message.content : codeDiverWelcomeText(""), 0, 0);
    const box = new Box(1, 1, (token) => theme.bg("customMessageBg", token));
    box.addChild(text);
    return box;
  });

  pi.on("session_start", async (event, ctx) => {
    if (event.reason !== "startup") {
      return;
    }
    if ("hasUI" in ctx && !ctx.hasUI) {
      return;
    }
    pi.sendMessage({
      customType: "code-diver-welcome",
      content: codeDiverWelcomeText(ctx.cwd),
      display: true,
    });
  });
}

function codeDiverWelcomeText(cwd: string): string {
  const repository = cwd ? `Repository: ${cwd}` : "Repository: current workspace";
  return [
    "Code Diver Search agent",
    "",
    repository,
    "",
    "I can search the local Code Diver index, inspect symbols, run grep/rg, read bounded excerpts, open code locations, explain code flows with file/line evidence, refresh indexes, and run retrieval evaluations.",
    "",
    "This session is read-only for source code. Ask a code question to start.",
  ].join("\n");
}

function compactToolUi(label: string) {
  return {
    renderCall(args: unknown, theme: any, context: any) {
      const text = (context.lastComponent as Text | undefined) ?? new Text("", 0, 0);
      const suffix = summarizeArgs(args);
      text.setText(theme.fg("toolTitle", `code_diver_${label.replaceAll(" ", "_")}`) + (suffix ? theme.fg("muted", ` ${suffix}`) : ""));
      return text;
    },
    renderResult(result: any, options: any, theme: any) {
      if (options?.isPartial) {
        return new Text(theme.fg("warning", "running..."), 0, 0);
      }
      if (result?.isError) {
        return new Text(theme.fg("error", compactResultText(result) || "failed"), 0, 0);
      }
      return new Text(theme.fg("success", summarizeResult(compactResultText(result))), 0, 0);
    },
  };
}

function summarizeArgs(args: unknown): string {
  if (!args || typeof args !== "object") {
    return "";
  }
  const value = args as Record<string, unknown>;
  for (const key of ["query", "pattern", "file", "path", "rank"]) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return truncateLine(candidate.trim(), 80);
    }
    if (typeof candidate === "number") {
      return String(candidate);
    }
  }
  const probes = ["searches", "regexes", "literals", "trees", "reads", "symbols"]
    .map((key) => [key, Array.isArray(value[key]) ? (value[key] as unknown[]).length : 0] as const)
    .filter((entry) => entry[1] > 0);
  if (probes.length) {
    return probes.map(([key, count]) => `${key}:${count}`).join(" ");
  }
  return "";
}

function compactResultText(result: any): string {
  const content = result?.content;
  if (!Array.isArray(content)) {
    return "";
  }
  return content
    .map((part) => (typeof part?.text === "string" ? part.text : ""))
    .filter(Boolean)
    .join("\n");
}

function summarizeResult(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) {
    return "done";
  }
  const parsed = tryJson(trimmed);
  const count = resultCount(parsed);
  if (count !== null) {
    return `${count} result${count === 1 ? "" : "s"}`;
  }
  const sections = (trimmed.match(/^## /gm) ?? []).length;
  if (sections > 0) {
    return `${sections} probe${sections === 1 ? "" : "s"} completed`;
  }
  const lines = trimmed.split(/\r?\n/).filter((line) => line.trim()).length;
  if (lines > 1) {
    return `${lines} lines`;
  }
  return truncateLine(trimmed, 96);
}

function tryJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function resultCount(value: unknown): number | null {
  if (Array.isArray(value)) {
    return value.length;
  }
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  for (const key of ["results", "candidates", "items"]) {
    if (Array.isArray(record[key])) {
      return record[key].length;
    }
  }
  return null;
}

function truncateLine(text: string, limit: number): string {
  const oneLine = text.replace(/\s+/g, " ").trim();
  if (oneLine.length <= limit) {
    return oneLine;
  }
  return `${oneLine.slice(0, Math.max(limit - 1, 0))}…`;
}

async function recordFailure(cwd: string, feedback: FailureFeedback): Promise<string> {
  return appendFeedback(cwd, "fail-cases.jsonl", {
    ts: new Date().toISOString(),
    query: feedback.query,
    correction: feedback.correction,
    actual: feedback.actual ?? null,
    expected: feedback.expected ?? null,
    files: feedback.files ?? [],
    notes: feedback.notes ?? null,
  });
}

async function recordSuccess(cwd: string, feedback: SuccessFeedback): Promise<string> {
  return appendFeedback(cwd, "success-cases.jsonl", {
    ts: new Date().toISOString(),
    query: feedback.query,
    answer: feedback.answer,
    files: feedback.files ?? [],
    symbols: feedback.symbols ?? [],
    notes: feedback.notes ?? null,
  });
}

async function appendFeedback(cwd: string, filename: string, record: Record<string, unknown>): Promise<string> {
  const feedbackDir = join(cwd, ".code-diver", "feedback");
  const feedbackPath = join(feedbackDir, filename);
  await mkdir(feedbackDir, { recursive: true });
  await appendFile(feedbackPath, `${JSON.stringify(record)}\n`, "utf8");
  return `.code-diver/feedback/${filename}`;
}

function appendPathAndLimit(args: string[], path?: string, limit?: number) {
  if (path) {
    args.push("--path", path);
  }
  if (limit) {
    args.push("--limit", String(limit));
  }
}

async function labelResult(label: string, resultPromise: Promise<CommandResult>): Promise<string> {
  const result = await resultPromise;
  return `## ${label}\n${result.stdout || result.stderr}`;
}

function runCodeDiver(cwd: string, args: string[], signal?: AbortSignal, input?: string): Promise<CommandResult> {
  const config = process.env.CODE_DIVER_CONFIG || "code-diver.yml";
  const root = process.env.CODE_DIVER_ROOT;
  const packageRoot = process.env.CODE_DIVER_PACKAGE_ROOT || cwd;
  const childArgs = ["run", "code-diver", "--config", config];
  if (root) {
    childArgs.push("--root", root);
  }
  childArgs.push(...args);
  return new Promise((resolve, reject) => {
    const child = spawn("uv", childArgs, {
      cwd: packageRoot,
      env: process.env,
      stdio: ["pipe", "pipe", "pipe"],
      signal,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    if (input) {
      child.stdin.write(input);
    }
    child.stdin.end();
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve({ stdout: truncate(stdout), stderr: truncate(stderr) });
        return;
      }
      reject(new Error(truncate(stderr || stdout || `code-diver exited with status ${code}`)));
    });
  });
}

function textResult(text: string) {
  return {
    content: [{ type: "text", text: truncate(text) }],
    details: {},
  };
}

function truncate(text: string): string {
  if (text.length <= MAX_TOOL_OUTPUT) {
    return text;
  }
  return `${text.slice(0, MAX_TOOL_OUTPUT)}\n... truncated ...`;
}
