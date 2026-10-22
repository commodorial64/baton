'use strict';

const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { execFile } = require('child_process');

const data = require('./data');
const analyze = require('./analyze');
const { parseDiagnostics } = require('./diagnostics');

const LANGUAGE = 'baton';

const analysisCache = new Map();
const checkGeneration = new Map();
const typeTimers = new Map();
const compilerCache = new Map();

let diagnostics;
let output;
let missingCompilerNotified = false;

// -- analysis ------------------------------------------------------------

function getAnalysis(document) {
  const key = document.uri.toString();
  const cached = analysisCache.get(key);
  if (cached && cached.version === document.version) return cached.analysis;
  const analysis = analyze.analyzeDocument(document.getText());
  analysisCache.set(key, { version: document.version, analysis });
  return analysis;
}

function symbolKind(symbol) {
  switch (symbol.kind) {
    case 'function':
    case 'extern':
      return vscode.CompletionItemKind.Function;
    case 'struct':
      return vscode.CompletionItemKind.Struct;
    case 'namespace':
    case 'module':
      return vscode.CompletionItemKind.Module;
    case 'constant':
      return vscode.CompletionItemKind.Constant;
    case 'field':
      return vscode.CompletionItemKind.Field;
    default:
      return vscode.CompletionItemKind.Variable;
  }
}

function symbolMarkdown(symbol, fileName) {
  const markdown = new vscode.MarkdownString();
  if (symbol.signature) markdown.appendCodeblock(symbol.signature, 'baton');
  if (symbol.detail) markdown.appendMarkdown(`\n\n${symbol.detail}`);
  if (fileName) {
    markdown.appendMarkdown(`\n\nDefined at \`${path.basename(fileName)}:${symbol.line + 1}\``);
  }
  return markdown;
}

function dataMarkdown(info) {
  const markdown = new vscode.MarkdownString();
  if (info.signature) markdown.appendCodeblock(info.signature, 'baton');
  if (info.documentation) markdown.appendMarkdown(`\n\n${info.documentation}`);
  return markdown;
}

function sortTextFor(symbol) {
  switch (symbol.kind) {
    case 'parameter':
    case 'variable':
    case 'loop':
      return `0_${symbol.name}`;
    case 'global':
    case 'constant':
      return `1_${symbol.name}`;
    case 'field':
      return `1_${symbol.name}`;
    case 'function':
    case 'extern':
      return `2_${symbol.name}`;
    case 'struct':
    case 'namespace':
    case 'module':
      return `3_${symbol.name}`;
    default:
      return `4_${symbol.name}`;
  }
}

function symbolItem(symbol, fileName) {
  const item = new vscode.CompletionItem(symbol.name, symbolKind(symbol));
  item.detail = symbol.signature || symbol.type || symbol.name;
  item.documentation = symbolMarkdown(symbol, fileName);
  item.sortText = sortTextFor(symbol);
  item.insertText = symbol.name;
  return item;
}

function builtinItem(name, info) {
  const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.Function);
  item.detail = info.signature || name;
  item.documentation = dataMarkdown(info);
  item.sortText = `2_${name}`;
  return item;
}

function namespaceItem(name, info) {
  const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.Module);
  item.detail = info.detail || name;
  item.documentation = new vscode.MarkdownString(info.documentation || '');
  item.sortText = `3_${name}`;
  return item;
}

function typeItem(name, info) {
  const kind = name === 'File' || name === 'Task'
    ? vscode.CompletionItemKind.Class
    : vscode.CompletionItemKind.TypeParameter;
  const item = new vscode.CompletionItem(name, kind);
  item.detail = info.detail || name;
  item.documentation = new vscode.MarkdownString(info.documentation || '');
  item.sortText = `4_${name}`;
  return item;
}

function keywordItem(name, info) {
  const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.Keyword);
  item.detail = info.detail || 'keyword';
  item.documentation = new vscode.MarkdownString(info.documentation || '');
  item.sortText = `5_${name}`;
  return item;
}

function memberItem(name, info) {
  const constant = /const/.test(info.detail || '');
  const item = new vscode.CompletionItem(
    name,
    constant ? vscode.CompletionItemKind.Constant : vscode.CompletionItemKind.Method
  );
  item.detail = info.signature || name;
  item.documentation = dataMarkdown(info);
  item.sortText = `0_${name}`;
  return item;
}

// -- completion ----------------------------------------------------------

async function loadModule(moduleSymbol, document) {
  const target = path.resolve(path.dirname(document.uri.fsPath), moduleSymbol.modulePath);
  if (!/\.bt$/i.test(target)) return null;
  try {
    const source = await fs.promises.readFile(target, 'utf8');
    return {
      fileName: target,
      analysis: analyze.analyzeDocument(source)
    };
  } catch {
    return null;
  }
}

async function moduleCompletionItems(moduleSymbol, document) {
  const loaded = await loadModule(moduleSymbol, document);
  if (!loaded) {
    const target = path.resolve(path.dirname(document.uri.fsPath), moduleSymbol.modulePath);
    if (!/\.btl$/i.test(target)) return [];
    try {
      const source = await fs.promises.readFile(target, 'utf8');
      const base = path.basename(target, '.btl');
      const pattern = new RegExp(`\\b${escapeRegExp(base)}_([A-Za-z_][A-Za-z0-9_]*)\\s*\\(([^)]*)\\)`, 'g');
      const items = [];
      let match;
      while ((match = pattern.exec(source)) !== null) {
        const item = new vscode.CompletionItem(match[1], vscode.CompletionItemKind.Function);
        item.detail = `${base}.${match[1]}(${match[2].trim()})`;
        item.documentation = new vscode.MarkdownString(`C function from \`${path.basename(target)}\`.`);
        item.sortText = `0_${match[1]}`;
        items.push(item);
      }
      return items;
    } catch {
      return [];
    }
  }

  const analysis = loaded.analysis;
  const exposed = analysis.exposed.size ? analysis.exposed : null;
  const items = [];
  for (const symbol of analysis.symbols) {
    if (symbol.block !== analysis.root) continue;
    if (exposed && !exposed.has(symbol.name)) continue;
    if (symbol.kind === 'namespace') {
      for (const member of symbol.members || []) {
        items.push(symbolItem(member, loaded.fileName));
      }
    } else if (symbol.kind === 'function' || symbol.kind === 'extern' ||
               symbol.kind === 'struct' || symbol.kind === 'constant' ||
               symbol.kind === 'global') {
      items.push(symbolItem(symbol, loaded.fileName));
    }
  }
  return items;
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function memberCompletions(context, analysis, document, position) {
  const offset = document.offsetAt(position);
  const result = analyze.memberSymbols(analysis, context.qualifier, offset);

  if (result) {
    if (result.source === 'symbols') {
      return result.entries.map((symbol) =>
        symbolItem(symbol, document.uri.fsPath));
    }
    return Object.entries(result.entries).map(([name, info]) => memberItem(name, info));
  }

  const symbol = analyze.findSymbol(analysis, context.qualifier, offset);
  if (symbol && symbol.kind === 'module') {
    return moduleCompletionItems(symbol, document);
  }

  return [];
}

async function provideCompletionItems(document, position) {
  const analysis = getAnalysis(document);
  const offset = document.offsetAt(position);
  const context = analyze.completionContext(analysis, offset);
  if (!context) return undefined;

  if (context.kind === 'member') {
    return memberCompletions(context, analysis, document, position);
  }

  const items = [];
  const seen = new Set();

  const visible = analyze.visibleSymbols(analysis, offset)
    .slice()
    .sort((a, b) => b.offset - a.offset);
  for (const symbol of visible) {
    if (symbol.kind === 'field') continue;
    if (seen.has(symbol.name)) continue;
    seen.add(symbol.name);
    items.push(symbolItem(symbol, document.uri.fsPath));
  }

  for (const [name, info] of Object.entries(data.BUILTINS)) {
    if (seen.has(name)) continue;
    seen.add(name);
    items.push(builtinItem(name, info));
  }

  for (const [name, info] of Object.entries(data.NAMESPACES)) {
    if (seen.has(name)) continue;
    seen.add(name);
    items.push(namespaceItem(name, info));
  }

  for (const [name, info] of Object.entries(data.TYPES)) {
    if (seen.has(name)) continue;
    seen.add(name);
    items.push(typeItem(name, info));
  }

  for (const [name, info] of Object.entries(data.KEYWORDS)) {
    if (seen.has(name)) continue;
    seen.add(name);
    items.push(keywordItem(name, info));
  }

  return items;
}

// -- hover ---------------------------------------------------------------

function qualifierBefore(document, range) {
  const line = document.lineAt(range.start.line).text;
  const prefix = line.slice(0, range.start.character);
  const match = /([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*$/.exec(prefix);
  return match ? match[1] : null;
}

async function moduleHover(symbol, document, name) {
  const loaded = await loadModule(symbol, document);
  if (!loaded) return null;
  const analysis = loaded.analysis;
  const exposed = analysis.exposed.size ? analysis.exposed : null;

  for (const candidate of analysis.symbols) {
    if (candidate.block !== analysis.root) continue;
    if (exposed && !exposed.has(candidate.name)) continue;
    if (candidate.kind === 'namespace') {
      const member = (candidate.members || []).find((entry) => entry.name === name);
      if (member) return new vscode.Hover(symbolMarkdown(member, loaded.fileName));
    } else if (candidate.name === name) {
      return new vscode.Hover(symbolMarkdown(candidate, loaded.fileName));
    }
  }
  return null;
}

async function provideHover(document, position) {
  const analysis = getAnalysis(document);
  const offset = document.offsetAt(position);
  if (analyze.isInsideNonCode(analysis.tokens, offset)) return undefined;

  const range = document.getWordRangeAtPosition(position, /[A-Za-z_][A-Za-z0-9_-]*/);
  if (!range) return undefined;
  const name = document.getText(range);
  const qualifier = qualifierBefore(document, range);

  if (qualifier) {
    const result = analyze.memberSymbols(analysis, qualifier, offset);
    if (result) {
      if (result.source === 'symbols') {
        const symbol = result.entries.find((entry) => entry.name === name);
        if (symbol) return new vscode.Hover(symbolMarkdown(symbol, document.uri.fsPath), range);
      } else if (result.entries[name]) {
        return new vscode.Hover(dataMarkdown(result.entries[name]), range);
      }
    }

    const symbol = analyze.findSymbol(analysis, qualifier, offset);
    if (symbol && symbol.kind === 'module') {
      const hover = await moduleHover(symbol, document, name);
      if (hover) {
        hover.range = range;
        return hover;
      }
    }
    return undefined;
  }

  if (data.BUILTINS[name]) {
    return new vscode.Hover(dataMarkdown(data.BUILTINS[name]), range);
  }
  if (data.KEYWORDS[name]) {
    const info = data.KEYWORDS[name];
    return new vscode.Hover(dataMarkdown({
      signature: info.detail,
      documentation: info.documentation
    }), range);
  }
  if (data.TYPES[name]) {
    return new vscode.Hover(dataMarkdown({
      signature: data.TYPES[name].detail,
      documentation: data.TYPES[name].documentation
    }), range);
  }
  if (data.NAMESPACES[name]) {
    const info = data.NAMESPACES[name];
    return new vscode.Hover(new vscode.MarkdownString(info.documentation || info.detail || name), range);
  }

  const symbol = analyze.findSymbol(analysis, name, offset);
  if (symbol) {
    return new vscode.Hover(symbolMarkdown(symbol, document.uri.fsPath), range);
  }

  return undefined;
}

// -- signature help ------------------------------------------------------

function signatureFromSymbol(symbol) {
  const params = (symbol.params || [])
    .map((param) => param.name ? `${param.type} ${param.name}` : param.type);
  const signature = new vscode.SignatureInformation(
    symbol.signature || `${symbol.name}(${params.join(', ')})`,
    symbolMarkdown(symbol)
  );
  signature.parameters = params.map((param) => new vscode.ParameterInformation(param));
  return signature;
}

function signatureFromData(label, info) {
  const params = info.parameters || [];
  const signature = new vscode.SignatureInformation(
    label || info.signature || '',
    dataMarkdown(info)
  );
  signature.parameters = params.map((param) => new vscode.ParameterInformation(param));
  return signature;
}

function provideSignatureHelp(document, position) {
  const analysis = getAnalysis(document);
  const context = analyze.signatureContext(analysis, document.offsetAt(position));
  if (!context) return undefined;

  const signatures = [];
  const callee = context.callee;

  if (callee.includes('.')) {
    const dot = callee.indexOf('.');
    const qualifier = callee.slice(0, dot);
    const name = callee.slice(dot + 1);

    const symbol = analysis.functions.get(callee);
    if (symbol) {
      signatures.push(signatureFromSymbol(symbol));
    } else if (data.NAMESPACES[qualifier] && data.NAMESPACES[qualifier].members[name]) {
      signatures.push(signatureFromData(
        data.NAMESPACES[qualifier].members[name].signature,
        data.NAMESPACES[qualifier].members[name]
      ));
    } else if (data.FILE_METHODS[name]) {
      const offset = document.offsetAt(position);
      const variable = analyze.findSymbol(analysis, qualifier, offset);
      if (variable && analyze.baseType(variable.type) === 'File') {
        signatures.push(signatureFromData(
          data.FILE_METHODS[name].signature,
          data.FILE_METHODS[name]
        ));
      }
    }
  } else {
    const symbol = analysis.functions.get(callee);
    if (symbol) {
      signatures.push(signatureFromSymbol(symbol));
    } else if (data.BUILTINS[callee]) {
      signatures.push(signatureFromData(data.BUILTINS[callee].signature, data.BUILTINS[callee]));
    }
  }

  if (!signatures.length) return undefined;

  const help = new vscode.SignatureHelp();
  help.signatures = signatures;
  help.activeSignature = 0;
  const count = signatures[0].parameters.length;
  help.activeParameter = count
    ? Math.min(context.activeParameter, count - 1)
    : 0;
  return help;
}

// -- document outline ----------------------------------------------------

function fullRange(symbol, analysis) {
  const start = new vscode.Position(symbol.line, symbol.character);
  if (symbol.bodyBlock) {
    const offset = symbol.bodyBlock.end === null
      ? analysis.text.length
      : symbol.bodyBlock.end;
    const end = analyze.positionAt(analysis.starts, offset);
    return new vscode.Range(start, new vscode.Position(end.line, end.character));
  }
  return new vscode.Range(start, new vscode.Position(start.line, start.character + symbol.name.length));
}

function documentSymbolKind(symbol) {
  switch (symbol.kind) {
    case 'function':
    case 'extern':
      return vscode.SymbolKind.Function;
    case 'struct':
      return vscode.SymbolKind.Struct;
    case 'namespace':
    case 'module':
      return vscode.SymbolKind.Namespace;
    case 'constant':
      return vscode.SymbolKind.Constant;
    case 'field':
      return vscode.SymbolKind.Field;
    default:
      return vscode.SymbolKind.Variable;
  }
}

function toDocumentSymbol(symbol, analysis) {
  const range = fullRange(symbol, analysis);
  const selection = new vscode.Range(
    symbol.line,
    symbol.character,
    symbol.line,
    symbol.character + symbol.name.length
  );
  const result = new vscode.DocumentSymbol(
    symbol.name,
    symbol.detail || symbol.type || '',
    documentSymbolKind(symbol),
    range,
    selection
  );

  if (symbol.kind === 'struct') {
    for (const field of symbol.fields || []) {
      result.children.push(toDocumentSymbol(field, analysis));
    }
  } else if (symbol.kind === 'namespace') {
    for (const member of symbol.members || []) {
      result.children.push(toDocumentSymbol(member, analysis));
    }
  }

  return result;
}

function provideDocumentSymbols(document) {
  const analysis = getAnalysis(document);
  return analysis.symbols
    .filter((symbol) => symbol.block === analysis.root)
    .filter((symbol) => symbol.kind !== 'parameter' &&
                       symbol.kind !== 'loop' &&
                       symbol.kind !== 'field')
    .map((symbol) => toDocumentSymbol(symbol, analysis));
}

// -- compiler diagnostics -------------------------------------------------

function splitCommand(text) {
  const parts = text.match(/"[^"]*"|'[^']*'|\S+/g) || [];
  return parts.map((part) => {
    if ((part.startsWith('"') && part.endsWith('"')) ||
        (part.startsWith("'") && part.endsWith("'"))) {
      return part.slice(1, -1);
    }
    return part;
  });
}

function runProcess(command, args, cwd) {
  return new Promise((resolve) => {
    execFile(command, args, {
      cwd,
      timeout: 20000,
      maxBuffer: 4 * 1024 * 1024,
      windowsHide: true
    }, (error, stdout, stderr) => {
      resolve({
        error,
        stdout: stdout || '',
        stderr: stderr || '',
        code: error && typeof error.code === 'number' ? error.code : (error ? -1 : 0)
      });
    });
  });
}

function compilerCandidates(document) {
  const configuration = vscode.workspace.getConfiguration('baton', document.uri);
  const configured = String(configuration.get('executable', 'baton') || '').trim();
  const folder = vscode.workspace.getWorkspaceFolder(document.uri);
  const folders = folder ? [folder] : (vscode.workspace.workspaceFolders || []);
  const documentDir = path.dirname(document.uri.fsPath);
  const candidates = [];
  const workspaceCandidates = [];

  const inspected = typeof configuration.inspect === 'function'
    ? configuration.inspect('executable')
    : null;
  const explicitlyConfigured = !!inspected && [
    'globalValue', 'workspaceValue', 'workspaceFolderValue', 'languageValue'
  ].some((key) => inspected[key] !== undefined);

  const configuredCandidate = (() => {
    if (!configured) return null;
    const parts = splitCommand(configured);
    if (!parts.length) return null;
    return {
      command: parts[0],
      args: parts.slice(1),
      cwd: documentDir,
      label: configured
    };
  })();

  for (const workspaceFolder of folders) {
    const root = workspaceFolder.uri.fsPath;
    if (fs.existsSync(path.join(root, 'baton', '__init__.py'))) {
      workspaceCandidates.push({
        command: 'python3',
        args: ['-m', 'baton'],
        cwd: root,
        label: 'python3 -m baton'
      });
    }
    const shim = path.join(root, 'bin', 'baton');
    if (fs.existsSync(shim)) {
      workspaceCandidates.push({
        command: shim,
        args: [],
        cwd: root,
        label: shim
      });
    }
  }

  // An explicit setting wins. The default of `baton` should not hide a newer
  // compiler in the open checkout, so use the workspace one first in that case.
  if (explicitlyConfigured && configuredCandidate) candidates.push(configuredCandidate);
  candidates.push(...workspaceCandidates);
  if (!explicitlyConfigured && configuredCandidate) candidates.push(configuredCandidate);

  candidates.push({
    command: 'python3',
    args: ['-m', 'baton'],
    cwd: documentDir,
    label: 'python3 -m baton'
  });

  return candidates;
}

async function canRun(candidate) {
  const key = `${candidate.command}\u0000${candidate.args.join('\u0000')}\u0000${candidate.cwd}`;
  if (compilerCache.has(key)) return compilerCache.get(key);
  const result = await runProcess(candidate.command, candidate.args.concat('--version'), candidate.cwd);
  const ok = !(result.error && result.error.code === 'ENOENT');
  compilerCache.set(key, ok);
  return ok;
}

async function findCompiler(document) {
  for (const candidate of compilerCandidates(document)) {
    if (await canRun(candidate)) return candidate;
  }
  return null;
}

function notifyMissingCompiler() {
  output.appendLine('Could not find the baton compiler. Set "baton.executable" to the command that runs it.');
  if (missingCompilerNotified) return;
  missingCompilerNotified = true;
  vscode.window.showWarningMessage(
    'Baton: could not find the compiler. Set "baton.executable" in Settings.',
    'Open Settings'
  ).then((choice) => {
    if (choice === 'Open Settings') {
      vscode.commands.executeCommand('workbench.action.openSettings', 'baton.executable');
    }
  });
}

function shellQuote(value) {
  if (/^[A-Za-z0-9_@%+=:,./-]+$/.test(value)) return value;
  if (process.platform === 'win32') {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return `'${value.replace(/'/g, "'\\''")}'`;
}

async function runDocument(document) {
  if (document.languageId !== LANGUAGE) {
    vscode.window.showInformationMessage('Open a Baton file first.');
    return;
  }

  if (document.isDirty) {
    const saved = await document.save();
    if (!saved) return;
  }

  const compiler = await findCompiler(document);
  if (!compiler) {
    notifyMissingCompiler();
    return;
  }

  const command = [compiler.command]
    .concat(compiler.args, ['run', document.uri.fsPath])
    .map(shellQuote)
    .join(' ');
  const terminal = vscode.window.createTerminal({ name: 'Baton', cwd: compiler.cwd });
  terminal.show(true);
  terminal.sendText(command, true);
}

function toDiagnostic(document, item) {
  const line = Math.max(0, Math.min(item.line - 1, document.lineCount - 1));
  const lineLength = document.lineAt(line).text.length;
  const startCharacter = Math.max(0, Math.min(item.column - 1, lineLength));
  const endCharacter = Math.max(
    startCharacter + 1,
    Math.min(startCharacter + Math.max(1, item.span), lineLength)
  );
  const range = new vscode.Range(line, startCharacter, line, endCharacter);
  const diagnostic = new vscode.Diagnostic(
    range,
    item.message,
    item.severity === 'error'
      ? vscode.DiagnosticSeverity.Error
      : vscode.DiagnosticSeverity.Warning
  );
  diagnostic.source = 'baton';
  return diagnostic;
}

async function checkDocument(document) {
  if (document.languageId !== LANGUAGE) return;

  const uri = document.uri;
  const mode = vscode.workspace.getConfiguration('baton', uri).get('diagnostics.run', 'onSave');
  if (mode === 'off') {
    diagnostics.delete(uri);
    return;
  }

  const generation = (checkGeneration.get(uri.toString()) || 0) + 1;
  checkGeneration.set(uri.toString(), generation);

  let directory = null;
  try {
    directory = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'baton-vscode-'));
    const base = path.basename(document.uri.fsPath) || 'untitled.bt';
    const file = path.join(directory, base.endsWith('.bt') ? base : `${base}.bt`);
    await fs.promises.writeFile(file, document.getText(), 'utf8');

    const compiler = await findCompiler(document);
    if (!compiler) {
      diagnostics.delete(uri);
      notifyMissingCompiler();
      return;
    }

    const result = await runProcess(compiler.command, compiler.args.concat(['check', file]), compiler.cwd);

    if (result.error && result.error.code === 'ENOENT') {
      compilerCache.clear();
      diagnostics.delete(uri);
      notifyMissingCompiler();
      return;
    }

    if (checkGeneration.get(uri.toString()) !== generation) return;

    const outputText = `${result.stderr}\n${result.stdout}`;
    const items = parseDiagnostics(outputText);

    if (!items.length && result.code !== 0 && outputText.trim()) {
      output.appendLine(`$ ${compiler.label || compiler.command} check ${base}`);
      output.appendLine(outputText.trim());
    }

    diagnostics.set(uri, items.map((item) => toDiagnostic(document, item)));
  } catch (error) {
    output.appendLine(`Baton check failed: ${error && error.message ? error.message : error}`);
  } finally {
    if (directory) {
      fs.promises.rm(directory, { recursive: true, force: true }).catch(() => {});
    }
  }
}

function scheduleCheck(document, delay) {
  const key = document.uri.toString();
  const existing = typeTimers.get(key);
  if (existing) clearTimeout(existing);
  const timer = setTimeout(() => {
    typeTimers.delete(key);
    checkDocument(document);
  }, delay);
  typeTimers.set(key, timer);
}

// -- activation -----------------------------------------------------------

function activate(context) {
  output = vscode.window.createOutputChannel('Baton');
  diagnostics = vscode.languages.createDiagnosticCollection(LANGUAGE);
  context.subscriptions.push(output, diagnostics);

  context.subscriptions.push(
    vscode.languages.registerCompletionItemProvider(LANGUAGE, {
      provideCompletionItems
    }, '.'),

    vscode.languages.registerHoverProvider(LANGUAGE, {
      provideHover
    }),

    vscode.languages.registerSignatureHelpProvider(LANGUAGE, {
      provideSignatureHelp
    }, '(', ','),

    vscode.languages.registerDocumentSymbolProvider(LANGUAGE, {
      provideDocumentSymbols
    }),

    vscode.commands.registerCommand('baton.check', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.document.languageId !== LANGUAGE) {
        vscode.window.showInformationMessage('Open a Baton file first.');
        return;
      }
      await checkDocument(editor.document);
    }),

    vscode.commands.registerCommand('baton.run', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.document.languageId !== LANGUAGE) {
        vscode.window.showInformationMessage('Open a Baton file first.');
        return;
      }
      await runDocument(editor.document);
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((document) => {
      if (document.languageId === LANGUAGE) checkDocument(document);
    }),

    vscode.workspace.onDidSaveTextDocument((document) => {
      if (document.languageId !== LANGUAGE) return;
      const key = document.uri.toString();
      const timer = typeTimers.get(key);
      if (timer) {
        clearTimeout(timer);
        typeTimers.delete(key);
      }
      checkDocument(document);
    }),

    vscode.workspace.onDidChangeTextDocument((event) => {
      const document = event.document;
      if (document.languageId !== LANGUAGE) return;
      const mode = vscode.workspace.getConfiguration('baton', document.uri)
        .get('diagnostics.run', 'onSave');
      if (mode === 'onType') scheduleCheck(document, 450);
    }),

    vscode.workspace.onDidCloseTextDocument((document) => {
      const key = document.uri.toString();
      analysisCache.delete(key);
      checkGeneration.delete(key);
      const timer = typeTimers.get(key);
      if (timer) {
        clearTimeout(timer);
        typeTimers.delete(key);
      }
      diagnostics.delete(document.uri);
    }),

    vscode.workspace.onDidChangeConfiguration((event) => {
      if (!event.affectsConfiguration('baton')) return;
      compilerCache.clear();
      missingCompilerNotified = false;
      for (const document of vscode.workspace.textDocuments) {
        if (document.languageId !== LANGUAGE) continue;
        const mode = vscode.workspace.getConfiguration('baton', document.uri)
          .get('diagnostics.run', 'onSave');
        if (mode === 'off') diagnostics.delete(document.uri);
        else checkDocument(document);
      }
    })
  );

  for (const document of vscode.workspace.textDocuments) {
    if (document.languageId === LANGUAGE) checkDocument(document);
  }
}

function deactivate() {
  for (const timer of typeTimers.values()) clearTimeout(timer);
  typeTimers.clear();
}

module.exports = { activate, deactivate };
