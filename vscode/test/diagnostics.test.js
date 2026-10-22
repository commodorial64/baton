'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { parseDiagnostics } = require('../src/diagnostics');

test('parses an error, its line and its caret span', () => {
  const output = [
    'error: hello.bt:3: expected an expression',
    '    3 | local x =',
    '      |         ^^^',
    ''
  ].join('\n');

  const diagnostics = parseDiagnostics(output);

  assert.equal(diagnostics.length, 1);
  assert.equal(diagnostics[0].severity, 'error');
  assert.equal(diagnostics[0].file, 'hello.bt');
  assert.equal(diagnostics[0].line, 3);
  assert.equal(diagnostics[0].column, 9);
  assert.equal(diagnostics[0].span, 3);
  assert.equal(diagnostics[0].message, 'expected an expression');
});

test('parses warnings and falls back to column one without a caret', () => {
  const output = [
    'warning: hello.bt:2: no type prefix on \'x\', inferred \'i\' (int)',
    'error: hello.bt:5: unknown type \'T\''
  ].join('\n');

  const diagnostics = parseDiagnostics(output);

  assert.equal(diagnostics.length, 2);
  assert.equal(diagnostics[0].severity, 'warning');
  assert.equal(diagnostics[0].column, 1);
  assert.equal(diagnostics[0].span, 1);
  assert.equal(diagnostics[1].severity, 'error');
  assert.equal(diagnostics[1].line, 5);
});

test('ignores output that is not a source diagnostic', () => {
  const output = [
    'baton: no such file: missing.bt',
    'baton: gcc not found on PATH'
  ].join('\n');

  assert.deepEqual(parseDiagnostics(output), []);
});
