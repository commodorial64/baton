'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const analyze = require('../src/analyze');

test('finds functions, locals and parameters', () => {
  const source = [
    'fn add(i a, i b) -> i {',
    '    return a + b',
    '}',
    '',
    'fn main() -> i {',
    '    i local total = add(1, 2)',
    '    return total',
    '}'
  ].join('\n');

  const result = analyze.analyzeDocument(source);
  const names = result.symbols.map((symbol) => symbol.name);

  assert.deepEqual(names, ['add', 'a', 'b', 'main', 'total']);

  const fn = result.functions.get('add');
  assert.equal(fn.signature, 'fn add(i a, i b) -> i');
  assert.equal(fn.params.length, 2);

  const total = result.symbols.find((symbol) => symbol.name === 'total');
  assert.equal(total.type, 'i');
  assert.equal(total.kind, 'variable');
});

test('tracks block scope for visible symbols', () => {
  const source = [
    'fn main() -> i {',
    '    if true {',
    '        i local inner = 1',
    '    }',
    '    i local outer = 2',
    '    return outer',
    '}'
  ].join('\n');

  const result = analyze.analyzeDocument(source);
  const atReturn = source.indexOf('return outer');
  const visible = analyze.visibleSymbols(result, atReturn).map((symbol) => symbol.name);

  assert.ok(visible.includes('outer'));
  assert.ok(!visible.includes('inner'));
});

test('understands structs, namespaces and their members', () => {
  const source = [
    'struct Point {',
    '    i x',
    '    i y',
    '}',
    '',
    'ns math(i a, i b) -> det {',
    '    functions {',
    '        add() { return a + b }',
    '        scale(i k) { return (a + b) * k }',
    '    }',
    '}',
    '',
    'fn dist2(Point p, Point q) -> i {',
    '    return p.x - q.x',
    '}'
  ].join('\n');

  const result = analyze.analyzeDocument(source);

  const point = result.structs.get('Point');
  assert.deepEqual(point.fields.map((field) => field.name), ['x', 'y']);

  const math = result.namespaces.get('math');
  assert.deepEqual(math.members.map((member) => member.name), ['add', 'scale']);
  assert.equal(math.members[1].signature, 'fn scale(i a, i b, i k)');

  const atReturn = source.indexOf('return p.x');
  const pType = result.symbols.find((symbol) => symbol.name === 'p' && symbol.kind === 'parameter');
  assert.equal(pType.type, 'Point');

  const members = analyze.memberSymbols(result, 'p', atReturn);
  assert.equal(members.source, 'symbols');
  assert.deepEqual(members.entries.map((entry) => entry.name), ['x', 'y']);

  const namespaceMembers = analyze.memberSymbols(result, 'math', atReturn);
  assert.deepEqual(namespaceMembers.entries.map((entry) => entry.name), ['add', 'scale']);
});

test('infers per-name types from multiple returns', () => {
  const source = [
    'fn main() -> i {',
    '    i local n, b ok = tryi("42")',
    '    s local text, b got = readfile("x")',
    '    File local f, b open = fopen("x", "r")',
    '    return n',
    '}'
  ].join('\n');

  const result = analyze.analyzeDocument(source);
  const typeOf = (name) => result.symbols.find((symbol) => symbol.name === name).type;

  assert.equal(typeOf('n'), 'i');
  assert.equal(typeOf('ok'), 'b');
  assert.equal(typeOf('text'), 's');
  assert.equal(typeOf('got'), 'b');
  assert.equal(typeOf('f'), 'File');
  assert.equal(typeOf('open'), 'b');
});

test('offers file methods after a File variable', () => {
  const source = [
    'File local f, b ok = fopen("x", "r")',
    'f.write("hi")'
  ].join('\n');

  const result = analyze.analyzeDocument(source);
  const members = analyze.memberSymbols(result, 'f', source.indexOf('f.write') + 2);

  assert.equal(members.source, 'data');
  assert.ok(members.entries.write);
  assert.ok(members.entries.line);
});

test('finds the call and active parameter for signature help', () => {
  const source = [
    'fn add(i a, i b) -> i { return a + b }',
    'fn main() -> i {',
    '    print(add(1, 2), 3)',
    '    return 0',
    '}'
  ].join('\n');

  const result = analyze.analyzeDocument(source);
  let offset = source.indexOf('print(add(1,') + 'print(add(1,'.length;
  let context = analyze.signatureContext(result, offset);
  assert.equal(context.callee, 'add');
  assert.equal(context.activeParameter, 1);

  offset = source.indexOf('2), 3') + 3;
  context = analyze.signatureContext(result, offset);
  assert.equal(context.callee, 'print');
  assert.equal(context.activeParameter, 1);
});

test('recognises completion context after a dot', () => {
  const source = 'math.sqrt(2)';
  const result = analyze.analyzeDocument(source);
  const context = analyze.completionContext(result, source.indexOf('.') + 1);
  assert.deepEqual(context, { kind: 'member', qualifier: 'math', prefix: '' });
});

test('does not offer completion inside strings or comments', () => {
  const source = 's local text = "math."\n-- a comment\n';
  const result = analyze.analyzeDocument(source);

  const inString = source.indexOf('math.') + 'math.'.length;
  assert.equal(analyze.completionContext(result, inString), null);

  const inComment = source.indexOf('comment');
  assert.equal(analyze.completionContext(result, inComment), null);
});
