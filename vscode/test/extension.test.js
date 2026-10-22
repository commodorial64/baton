'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Module = require('module');

class Position {
  constructor(line, character) {
    this.line = line;
    this.character = character;
  }
}

class Range {
  constructor(startLine, startCharacter, endLine, endCharacter) {
    this.start = new Position(startLine, startCharacter);
    this.end = new Position(endLine, endCharacter);
  }
}

class MarkdownString {
  constructor(value) {
    this.value = value || '';
  }

  appendCodeblock(value, language) {
    this.value += `\`\`\`${language}\n${value}\n\`\`\``;
  }

  appendMarkdown(value) {
    this.value += value;
  }
}

class CompletionItem {
  constructor(label, kind) {
    this.label = label;
    this.kind = kind;
  }
}

class Hover {
  constructor(contents, range) {
    this.contents = contents;
    this.range = range;
  }
}

class SignatureInformation {
  constructor(label, documentation) {
    this.label = label;
    this.documentation = documentation;
    this.parameters = [];
  }
}

class ParameterInformation {
  constructor(label) {
    this.label = label;
  }
}

class SignatureHelp {
  constructor() {
    this.signatures = [];
    this.activeSignature = 0;
    this.activeParameter = 0;
  }
}

class DocumentSymbol {
  constructor(name, detail, kind, range, selectionRange) {
    this.name = name;
    this.detail = detail;
    this.kind = kind;
    this.range = range;
    this.selectionRange = selectionRange;
    this.children = [];
  }
}

class Diagnostic {
  constructor(range, message, severity) {
    this.range = range;
    this.message = message;
    this.severity = severity;
  }
}

function fileUri(fsPath) {
  return {
    fsPath,
    path: fsPath,
    scheme: 'file',
    toString: () => `file://${fsPath}`
  };
}

function fakeWorkspace() {
  return {
    workspaceFolders: [],
    textDocuments: [],
    getWorkspaceFolder: () => null,
    getConfiguration: () => ({ get: (_key, fallback) => fallback }),
    onDidOpenTextDocument: () => ({ dispose() {} }),
    onDidSaveTextDocument: () => ({ dispose() {} }),
    onDidChangeTextDocument: () => ({ dispose() {} }),
    onDidCloseTextDocument: () => ({ dispose() {} }),
    onDidChangeConfiguration: () => ({ dispose() {} })
  };
}

function makeVscode() {
  const providers = {};
  const vscode = {
    Position,
    Range,
    MarkdownString,
    CompletionItem,
    CompletionItemKind: {
      Function: 2,
      Method: 1,
      Variable: 5,
      Constant: 14,
      Struct: 22,
      Module: 8,
      Field: 4,
      Keyword: 13,
      TypeParameter: 24,
      Class: 6
    },
    Hover,
    SignatureInformation,
    ParameterInformation,
    SignatureHelp,
    DocumentSymbol,
    SymbolKind: {
      Function: 11,
      Struct: 22,
      Namespace: 3,
      Constant: 14,
      Field: 7,
      Variable: 12
    },
    Diagnostic,
    DiagnosticSeverity: { Error: 0, Warning: 1 },
    Uri: { file: fileUri },
    commands: {
      registerCommand: () => ({ dispose() {} }),
      executeCommand: () => Promise.resolve()
    },
    window: {
      createOutputChannel: () => ({ appendLine() {}, dispose() {} }),
      showWarningMessage: () => Promise.resolve(),
      showInformationMessage: () => {},
      activeTextEditor: undefined
    },
    languages: {
      createDiagnosticCollection: () => ({
        set() {},
        delete() {},
        clear() {},
        dispose() {}
      }),
      registerCompletionItemProvider: (_language, provider) => {
        providers.completion = provider;
        return { dispose() {} };
      },
      registerHoverProvider: (_language, provider) => {
        providers.hover = provider;
        return { dispose() {} };
      },
      registerSignatureHelpProvider: (_language, provider) => {
        providers.signature = provider;
        return { dispose() {} };
      },
      registerDocumentSymbolProvider: (_language, provider) => {
        providers.symbols = provider;
        return { dispose() {} };
      }
    },
    workspace: fakeWorkspace()
  };
  return { vscode, providers };
}

function fakeDocument(text) {
  const lines = text.split('\n');
  const starts = [0];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '\n') starts.push(i + 1);
  }
  return {
    languageId: 'baton',
    uri: fileUri('/tmp/hello.bt'),
    version: 1,
    lineCount: lines.length,
    getText: (range) => {
      if (!range) return text;
      const start = starts[range.start.line] + range.start.character;
      const end = starts[range.end.line] + range.end.character;
      return text.slice(start, end);
    },
    offsetAt: (position) => starts[position.line] + position.character,
    lineAt: (line) => ({
      text: lines[line],
      range: new Range(line, 0, line, lines[line].length)
    }),
    getWordRangeAtPosition(position) {
      const line = lines[position.line];
      let start = position.character;
      let end = position.character;
      while (start > 0 && /[A-Za-z0-9_-]/.test(line[start - 1])) start--;
      while (end < line.length && /[A-Za-z0-9_-]/.test(line[end])) end++;
      if (start === end) return null;
      return new Range(position.line, start, position.line, end);
    }
  };
}

function loadExtension() {
  const { vscode, providers } = makeVscode();
  const original = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return vscode;
    return original.call(this, request, parent, isMain);
  };
  try {
    delete require.cache[require.resolve('../src/extension')];
    const extension = require('../src/extension');
    return { extension, providers };
  } finally {
    Module._load = original;
  }
}

test('extension activates and serves the language features', async () => {
  const { extension, providers } = loadExtension();
  const text = [
    'fn main() -> i {',
    '    math.',
    '    print(1)',
    '    return 0',
    '}'
  ].join('\n');
  const document = fakeDocument(text);

  extension.activate({ subscriptions: [] });

  const completion = await providers.completion.provideCompletionItems(
    document,
    new Position(1, '    math.'.length)
  );
  assert.ok(completion.some((item) => item.label === 'sqrt'));

  const hover = await providers.hover.provideHover(document, new Position(2, 5));
  assert.ok(hover);
  assert.match(String(hover.contents.value), /print/);

  const signature = providers.signature.provideSignatureHelp(
    document,
    new Position(2, '    print('.length)
  );
  assert.ok(signature);
  assert.equal(signature.signatures[0].label, 'print(...values)');

  const outline = providers.symbols.provideDocumentSymbols(document);
  assert.equal(outline.length, 1);
  assert.equal(outline[0].name, 'main');
});
