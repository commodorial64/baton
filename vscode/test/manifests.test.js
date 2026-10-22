'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');

function readJson(relative) {
  return JSON.parse(fs.readFileSync(path.join(root, relative), 'utf8'));
}

test('package manifest points at files that exist', () => {
  const manifest = readJson('package.json');

  assert.equal(manifest.main, './src/extension.js');
  assert.ok(fs.existsSync(path.join(root, manifest.main)));
  assert.equal(manifest.contributes.languages[0].id, 'baton');
  assert.deepEqual(manifest.contributes.languages[0].extensions, ['.bt']);

  const grammar = manifest.contributes.grammars[0];
  assert.equal(grammar.scopeName, 'source.baton');
  assert.ok(fs.existsSync(path.join(root, grammar.path)));

  for (const snippet of manifest.contributes.snippets) {
    assert.ok(fs.existsSync(path.join(root, snippet.path)));
  }

  assert.ok(fs.existsSync(path.join(root, manifest.contributes.languages[0].configuration)));
});

test('grammar and language configuration are valid JSON', () => {
  const grammar = readJson('syntaxes/baton.tmLanguage.json');
  assert.equal(grammar.scopeName, 'source.baton');
  assert.ok(grammar.repository.comments);
  assert.ok(grammar.repository.strings);
  assert.ok(grammar.repository.keywords);

  const configuration = readJson('language-configuration.json');
  assert.equal(configuration.comments.lineComment, '--');
  assert.deepEqual(configuration.comments.blockComment, ['-/', '/-']);
});

test('snippets expose the expected prefixes', () => {
  const snippets = readJson('snippets/baton.json');
  for (const prefix of ['fn', 'main', 'local', 'if', 'for', 'struct', 'ns']) {
    assert.ok(Object.values(snippets).some((snippet) => snippet.prefix === prefix), prefix);
  }
});
