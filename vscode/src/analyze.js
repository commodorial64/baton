'use strict';

// A small, dependency-free scanner for baton source. It is deliberately not a
// full parser: IntelliSense only needs the declarations and the block they live
// in. The compiler remains the source of truth for correctness.

const { KEYWORDS, TYPES, BUILTINS, NAMESPACES, FILE_METHODS } = require('./data');

const KEYWORD_SET = new Set(Object.keys(KEYWORDS));
const TYPE_SET = new Set(Object.keys(TYPES));
const EXTRA_TYPES = new Set(['File', 'Task', 'det']);

const OPERATORS = [
  '..=', '**=', '<<=', '>>=',
  '..', '**', '<<', '>>', '<=', '>=', '==', '!=', '+=', '-=', '*=', '/=', '%=',
  '->',
  '&', '|', '^', '~', '+', '-', '*', '/', '%', '<', '>', '=', '!',
  '(', ')', '{', '}', '[', ']', ',', '.', ':', ';'
];

function isDigit(ch) {
  return ch >= '0' && ch <= '9';
}

function isIdentStart(ch) {
  return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || ch === '_';
}

function isIdentPart(ch) {
  return isIdentStart(ch) || isDigit(ch);
}

function lineStarts(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '\n') starts.push(i + 1);
  }
  return starts;
}

function positionAt(starts, offset) {
  let low = 0;
  let high = starts.length - 1;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (starts[mid] <= offset) low = mid;
    else high = mid - 1;
  }
  return { line: low, character: offset - starts[low] };
}

function tokenize(text) {
  const tokens = [];
  const starts = lineStarts(text);
  const length = text.length;

  function push(type, start, end, value) {
    const position = positionAt(starts, start);
    tokens.push({
      type,
      start,
      end,
      value: value === undefined ? text.slice(start, end) : value,
      line: position.line,
      character: position.character
    });
  }

  let i = 0;
  while (i < length) {
    const ch = text[i];

    if (ch === ' ' || ch === '\t' || ch === '\r') {
      i++;
      continue;
    }

    if (ch === '\n') {
      push('newline', i, i + 1);
      i++;
      continue;
    }

    if (ch === '-' && text[i + 1] === '-') {
      const start = i;
      while (i < length && text[i] !== '\n') i++;
      push('comment', start, i);
      continue;
    }

    if (ch === '-' && text[i + 1] === '/') {
      const start = i;
      i += 2;
      while (i < length && !(text[i] === '/' && text[i + 1] === '-')) i++;
      if (i < length) i += 2;
      push('comment', start, i);
      continue;
    }

    if (ch === '"') {
      const start = i;
      i++;
      while (i < length) {
        if (text[i] === '\\') { i += 2; continue; }
        if (text[i] === '\n') break;
        if (text[i] === '"') { i++; break; }
        i++;
      }
      push('string', start, i);
      continue;
    }

    if (ch === "'") {
      const start = i;
      i++;
      while (i < length) {
        if (text[i] === '\\') { i += 2; continue; }
        if (text[i] === '\n') break;
        if (text[i] === "'") { i++; break; }
        i++;
      }
      push('char', start, i);
      continue;
    }

    if (isDigit(ch)) {
      const start = i;
      if (ch === '0' && /[xXoObB]/.test(text[i + 1] || '')) {
        i += 2;
        while (i < length && (isIdentPart(text[i]) || text[i] === '_')) i++;
      } else {
        while (i < length && (isDigit(text[i]) || text[i] === '_')) i++;
        if (text[i] === '.' && text[i + 1] !== '.' && isDigit(text[i + 1])) {
          i++;
          while (i < length && (isDigit(text[i]) || text[i] === '_')) i++;
        }
        if ((text[i] === 'e' || text[i] === 'E') &&
            (isDigit(text[i + 1]) ||
             ((text[i + 1] === '+' || text[i + 1] === '-') && isDigit(text[i + 2])))) {
          i += 2;
          while (i < length && isDigit(text[i])) i++;
        }
      }
      push('number', start, i);
      continue;
    }

    if (isIdentStart(ch)) {
      const start = i;
      i++;
      while (i < length && isIdentPart(text[i])) i++;
      let value = text.slice(start, i);
      if (value === 'get' && text.startsWith('-from', i)) {
        i += 5;
        value = 'get-from';
      }
      push(KEYWORD_SET.has(value) ? 'keyword' : 'ident', start, i, value);
      continue;
    }

    let matched = false;
    for (const operator of OPERATORS) {
      if (text.startsWith(operator, i)) {
        push('op', i, i + operator.length, operator);
        i += operator.length;
        matched = true;
        break;
      }
    }
    if (!matched) {
      push('op', i, i + 1);
      i++;
    }
  }

  return { tokens, starts };
}

function isInsideNonCode(tokens, offset) {
  for (const token of tokens) {
    if ((token.type === 'comment' || token.type === 'string' || token.type === 'char') &&
        offset > token.start && offset <= token.end) {
      return true;
    }
  }
  return false;
}

function skipAngle(code, index) {
  let depth = 0;
  for (let i = index; i < code.length; i++) {
    const value = code[i].value;
    if (value === '<') {
      depth++;
    } else if (value === '>') {
      depth--;
      if (depth <= 0) return i;
    } else if (value === '>>') {
      depth -= 2;
      if (depth <= 0) return i;
    }
  }
  return code.length - 1;
}

function skipBracket(code, index) {
  let depth = 0;
  for (let i = index; i < code.length; i++) {
    if (code[i].value === '[') depth++;
    else if (code[i].value === ']') {
      depth--;
      if (depth <= 0) return i;
    }
  }
  return code.length - 1;
}

function findAngleOpen(code, index) {
  let depth = 0;
  for (let i = index; i >= 0; i--) {
    const value = code[i].value;
    if (value === '>') depth++;
    else if (value === '>>') depth += 2;
    else if (value === '<') {
      depth--;
      if (depth <= 0) return i;
    }
  }
  return -1;
}

function findBracketOpen(code, index) {
  let depth = 0;
  for (let i = index; i >= 0; i--) {
    if (code[i].value === ']') depth++;
    else if (code[i].value === '[') {
      depth--;
      if (depth <= 0) return i;
    }
  }
  return -1;
}

function returnTypesFromSignature(signature) {
  if (!signature) return [];
  const arrow = signature.indexOf('->');
  if (arrow < 0) return [];
  return signature.slice(arrow + 2).split(',').map((part) => part.trim()).filter(Boolean);
}

function analyzeDocument(text) {
  const { tokens, starts } = tokenize(text);
  const code = tokens.filter((token) =>
    token.type !== 'newline' && token.type !== 'comment');

  const root = { start: 0, end: text.length, parent: null };
  const stack = [root];
  const symbols = [];
  const structs = new Map();
  const namespaces = new Map();
  const functions = new Map();
  const modules = new Map();
  const exposed = new Set();

  const structStack = [];
  const namespaceStack = [];
  const functionsBlocks = new Set();
  let pendingFunction = null;
  let pendingStruct = null;
  let pendingNamespace = null;
  let pendingFunctionsBlock = false;

  function currentBlock() {
    return stack[stack.length - 1];
  }

  function makeSymbol(props, offset) {
    const position = positionAt(starts, offset);
    return Object.assign({
      line: position.line,
      character: position.character,
      offset
    }, props);
  }

  function isKnownType(name) {
    return TYPE_SET.has(name) || EXTRA_TYPES.has(name) || structs.has(name);
  }

  function parseTypeAt(index, any) {
    let i = index;
    if (!code[i]) return null;
    const start = code[i].start;
    while (code[i] && code[i].value === '*') i++;
    const ident = code[i];
    if (!ident) return null;
    if (ident.type !== 'ident' && !(any && ident.value === 'det')) return null;
    if (!any && !isKnownType(ident.value)) return null;
    i++;
    if (code[i] && code[i].value === '<') i = skipAngle(code, i) + 1;
    if (code[i] && code[i].value === '[') i = skipBracket(code, i) + 1;
    const end = code[i - 1].end;
    return {
      text: text.slice(start, end).trim(),
      name: ident.value,
      next: i
    };
  }

  function typeBefore(index) {
    const end = index - 1;
    if (end < 0 || !code[end]) return null;

    let nameIndex = end;
    if (code[end].value === ']') {
      const open = findBracketOpen(code, end);
      if (open < 1) return null;
      nameIndex = open - 1;
    } else if (code[end].value === '>' || code[end].value === '>>') {
      const open = findAngleOpen(code, end);
      if (open < 1) return null;
      nameIndex = open - 1;
    }

    const ident = code[nameIndex];
    if (!ident || ident.type !== 'ident' || !isKnownType(ident.value)) return null;

    let start = nameIndex;
    let i = nameIndex - 1;
    while (code[i] && code[i].value === '*') {
      start = i;
      i--;
    }

    return {
      text: text.slice(code[start].start, code[end].end).trim(),
      name: ident.value,
      startIndex: start
    };
  }

  function parseParamsAt(openIndex) {
    const params = [];
    let i = openIndex + 1;
    while (i < code.length && code[i].value !== ')') {
      const type = parseTypeAt(i, true);
      if (!type) {
        i++;
        continue;
      }
      i = type.next;
      let name = '';
      let nameToken = null;
      if (code[i] && code[i].type === 'ident') {
        name = code[i].value;
        nameToken = code[i];
        i++;
      }
      params.push({ type: type.text, name, nameToken });
      if (code[i] && code[i].value === ',') i++;
    }
    return { params, close: i };
  }

  function parseReturnType(index) {
    const types = [];
    let i = index;
    while (i < code.length) {
      const type = parseTypeAt(i, true);
      if (!type) break;
      types.push(type.text);
      i = type.next;
      if (code[i] && code[i].value === ',') {
        i++;
        continue;
      }
      break;
    }
    return { text: types.join(', '), next: i };
  }

  function declareFunction(nameToken, indexAfterName, isExtern) {
    let j = indexAfterName;
    if (code[j] && code[j].value === '<') j = skipAngle(code, j) + 1;

    let ownParams = [];
    if (code[j] && code[j].value === '(') {
      const parsed = parseParamsAt(j);
      ownParams = parsed.params;
      j = parsed.close + 1;
    }

    let returnType = '';
    if (code[j] && code[j].value === '->') {
      const parsed = parseReturnType(j + 1);
      returnType = parsed.text;
      j = parsed.next;
    }

    const container = namespaceStack.length
      ? namespaceStack[namespaceStack.length - 1].symbol
      : null;
    const params = container ? container.params.concat(ownParams) : ownParams;
    const parameterText = params
      .map((param) => param.name ? `${param.type} ${param.name}` : param.type)
      .join(', ');
    const signature = `fn ${nameToken.value}(${parameterText})` +
      (returnType ? ` -> ${returnType}` : '');

    const symbol = makeSymbol({
      name: nameToken.value,
      kind: isExtern ? 'extern' : 'function',
      type: returnType || 'void',
      signature,
      detail: container ? `member of ${container.name}` : (isExtern ? 'extern function' : 'function'),
      returnType,
      params,
      ownParams,
      block: currentBlock(),
      container: container ? container.name : undefined
    }, nameToken.start);

    symbols.push(symbol);
    functions.set(nameToken.value, symbol);
    if (container) {
      container.members.push(symbol);
      functions.set(`${container.name}.${nameToken.value}`, symbol);
    }
    if (!isExtern) pendingFunction = symbol;
    return j;
  }

  function lookupSymbol(name, offset) {
    for (let i = symbols.length - 1; i >= 0; i--) {
      const symbol = symbols[i];
      if (symbol.name !== name) continue;
      if (symbol.block && symbol.block.start <= offset &&
          (symbol.block.end === null || offset <= symbol.block.end)) {
        return symbol;
      }
    }
    return null;
  }

  function callSignature(name, qualifier, offset) {
    if (qualifier) {
      const namespace = NAMESPACES[qualifier];
      if (namespace && namespace.members[name]) return namespace.members[name].signature;
      const namespaced = functions.get(`${qualifier}.${name}`);
      if (namespaced) return namespaced.signature;
      const qualifierSymbol = lookupSymbol(qualifier, offset);
      if (qualifierSymbol && baseType(qualifierSymbol.type) === 'File' && FILE_METHODS[name]) {
        return FILE_METHODS[name].signature;
      }
      return null;
    }
    if (BUILTINS[name]) return BUILTINS[name].signature;
    const fn = functions.get(name) || lookupSymbol(name, offset);
    if (fn && fn.kind !== 'variable') return fn.signature || null;
    return null;
  }

  function inferValueType(index) {
    const token = code[index];
    if (!token) return null;
    if (token.type === 'string') return 's';
    if (token.type === 'char') return 'c';
    if (token.type === 'number') return /[.eE]/.test(token.value) ? 'f' : 'i';
    if (token.type === 'keyword' && (token.value === 'true' || token.value === 'false')) return 'b';
    if (token.type === 'ident') {
      if (code[index + 1] && code[index + 1].value === '(') {
        const signature = callSignature(token.value, null, token.start);
        const types = signature ? returnTypesFromSignature(signature) : [];
        return types[0] || null;
      }
      if (code[index + 1] && code[index + 1].value === '.' &&
          code[index + 2] && code[index + 2].type === 'ident' &&
          code[index + 3] && code[index + 3].value === '(') {
        const signature = callSignature(code[index + 2].value, token.value, token.start);
        const types = signature ? returnTypesFromSignature(signature) : [];
        if (types[0]) return types[0];
      }
    }
    return null;
  }

  function inferMultipleTypes(index) {
    const token = code[index];
    if (!token) return [];
    let name = null;
    let qualifier = null;
    let callIndex = -1;
    if (token.type === 'ident' && code[index + 1] && code[index + 1].value === '(') {
      name = token.value;
      callIndex = index;
    } else if (token.type === 'ident' && code[index + 1] && code[index + 1].value === '.' &&
               code[index + 2] && code[index + 2].type === 'ident' &&
               code[index + 3] && code[index + 3].value === '(') {
      qualifier = token.value;
      name = code[index + 2].value;
      callIndex = index;
    }
    if (!name || callIndex < 0) return [];
    const signature = callSignature(name, qualifier, token.start);
    return signature ? returnTypesFromSignature(signature) : [];
  }

  function parseDeclNames(startIndex) {
    const names = [];
    let i = startIndex;
    while (i < code.length) {
      let explicit = null;
      const type = parseTypeAt(i, false);
      if (type && code[type.next] && code[type.next].type === 'ident') {
        explicit = type;
        i = type.next;
      }
      const nameToken = code[i];
      if (!nameToken || nameToken.type !== 'ident') break;
      names.push({ name: nameToken.value, token: nameToken, explicit: explicit ? explicit.text : null });
      i++;
      if (!code[i] || code[i].value !== ',') break;
      i++;
    }
    return { names, next: i };
  }

  for (let i = 0; i < code.length; i++) {
    const token = code[i];

    if (token.type === 'op' && token.value === '{') {
      const block = { start: token.start, end: null, parent: currentBlock() };
      stack.push(block);

      if (pendingFunction) {
        pendingFunction.bodyBlock = block;
        for (const param of pendingFunction.ownParams) {
          if (!param.name) continue;
          symbols.push(makeSymbol({
            name: param.name,
            kind: 'parameter',
            type: param.type,
            signature: `${param.type} ${param.name}`,
            detail: `parameter of ${pendingFunction.name}`,
            block,
            container: pendingFunction.name
          }, param.nameToken ? param.nameToken.start : token.start));
        }
        pendingFunction = null;
      }

      if (pendingStruct) {
        pendingStruct.bodyBlock = block;
        structStack.push({ symbol: pendingStruct, block });
        pendingStruct = null;
      }

      if (pendingNamespace) {
        pendingNamespace.bodyBlock = block;
        for (const param of pendingNamespace.params) {
          if (!param.name) continue;
          symbols.push(makeSymbol({
            name: param.name,
            kind: 'parameter',
            type: param.type,
            signature: `${param.type} ${param.name}`,
            detail: `shared parameter of ${pendingNamespace.name}`,
            block
          }, param.nameToken ? param.nameToken.start : token.start));
        }
        namespaceStack.push({ symbol: pendingNamespace, block });
        pendingNamespace = null;
      }

      if (pendingFunctionsBlock) {
        functionsBlocks.add(block);
        pendingFunctionsBlock = false;
      }

      continue;
    }

    if (token.type === 'op' && token.value === '}') {
      const closing = stack.length > 1 ? stack.pop() : currentBlock();
      if (closing) closing.end = token.end;
      if (structStack.length && structStack[structStack.length - 1].block === closing) {
        structStack.pop();
      }
      if (namespaceStack.length && namespaceStack[namespaceStack.length - 1].block === closing) {
        namespaceStack.pop();
      }
      functionsBlocks.delete(closing);
      continue;
    }

    if (token.type === 'keyword') {
      if (token.value === 'fn' || (token.value === 'extern' && code[i + 1] && code[i + 1].value === 'fn')) {
        const isExtern = token.value === 'extern';
        let j = i + 1;
        if (isExtern) j++;
        const nameToken = code[j];
        if (!nameToken || nameToken.type !== 'ident') continue;
        i = declareFunction(nameToken, j + 1, isExtern) - 1;
        continue;
      }

      if (token.value === 'functions') {
        pendingFunctionsBlock = true;
        continue;
      }

      if (token.value === 'ns' && code[i + 1] && code[i + 1].type === 'ident') {
        const nameToken = code[i + 1];
        let j = i + 2;
        let params = [];
        if (code[j] && code[j].value === '(') {
          const parsed = parseParamsAt(j);
          params = parsed.params;
          j = parsed.close + 1;
        }
        let returnType = '';
        if (code[j] && code[j].value === '->') {
          const parsed = parseReturnType(j + 1);
          returnType = parsed.text;
          j = parsed.next;
        }
        const parameterText = params
          .map((param) => param.name ? `${param.type} ${param.name}` : param.type)
          .join(', ');
        const symbol = makeSymbol({
          name: nameToken.value,
          kind: 'namespace',
          type: 'namespace',
          signature: `${nameToken.value}(${parameterText})` +
            (returnType ? ` -> ${returnType}` : ''),
          detail: 'namespace',
          params,
          returnType,
          members: [],
          block: currentBlock()
        }, nameToken.start);
        symbols.push(symbol);
        namespaces.set(nameToken.value, symbol);
        pendingNamespace = symbol;
        i = j - 1;
        continue;
      }

      if (token.value === 'struct' && code[i + 1] && code[i + 1].type === 'ident') {
        const nameToken = code[i + 1];
        let j = i + 2;
        if (code[j] && code[j].value === '<') j = skipAngle(code, j) + 1;
        const symbol = makeSymbol({
          name: nameToken.value,
          kind: 'struct',
          type: nameToken.value,
          signature: `struct ${nameToken.value}`,
          detail: 'struct',
          fields: [],
          block: currentBlock()
        }, nameToken.start);
        symbols.push(symbol);
        structs.set(nameToken.value, symbol);
        pendingStruct = symbol;
        i = j - 1;
        continue;
      }

      if (token.value === 'mod') {
        let j = i + 1;
        let alias = null;
        if (code[j] && code[j].type === 'ident' &&
            code[j + 1] && code[j + 1].value === 'get-from') {
          alias = code[j].value;
          j++;
        }
        if (code[j] && code[j].value === 'get-from' &&
            code[j + 1] && code[j + 1].type === 'string') {
          const modulePath = code[j + 1].value.replace(/^"|"$/g, '');
          const base = modulePath.split(/[\\/]/).pop().replace(/\.(bt|btl)$/i, '');
          const name = alias || base;
          const symbol = makeSymbol({
            name,
            kind: 'module',
            type: 'module',
            signature: `mod ${alias ? alias + ' ' : ''}get-from "${modulePath}"`,
            detail: 'module',
            modulePath,
            block: currentBlock()
          }, token.start);
          symbols.push(symbol);
          modules.set(name, symbol);
          i = j + 1;
          continue;
        }
      }

      if (token.value === 'expose') {
        let j = i + 1;
        while (code[j] && code[j].type === 'ident') {
          exposed.add(code[j].value);
          j++;
          if (code[j] && code[j].value === ',') {
            j++;
            continue;
          }
          break;
        }
        continue;
      }

      if (token.value === 'for' && code[i + 1] && code[i + 1].type === 'ident') {
        const nameToken = code[i + 1];
        const symbol = makeSymbol({
          name: nameToken.value,
          kind: 'loop',
          type: 'i',
          signature: `for ${nameToken.value} in ...`,
          detail: 'loop variable (read-only)',
          block: currentBlock(),
          readOnly: true
        }, nameToken.start);
        symbols.push(symbol);
        i++;
        continue;
      }

      if (token.value === 'local' || token.value === 'const') {
        const explicitType = typeBefore(i);
        const parsed = parseDeclNames(i + 1);
        if (!parsed.names.length) continue;

        let valueTypes = [];
        if (code[parsed.next] && code[parsed.next].value === '=') {
          valueTypes = inferMultipleTypes(parsed.next + 1);
          if (!valueTypes.length) {
            const inferred = inferValueType(parsed.next + 1);
            if (inferred) valueTypes = [inferred];
          }
        }

        const isConst = token.value === 'const';
        const container = namespaceStack.length &&
          currentBlock() === namespaceStack[namespaceStack.length - 1].block
          ? namespaceStack[namespaceStack.length - 1].symbol
          : null;

        for (let index = 0; index < parsed.names.length; index++) {
          const entry = parsed.names[index];
          const type = entry.explicit ||
            (index === 0 && explicitType ? explicitType.text : null) ||
            valueTypes[index] ||
            (valueTypes.length === 1 ? valueTypes[0] : null);
          const kind = isConst ? 'constant'
            : (currentBlock() === root ? 'global' : 'variable');
          const signature = `${type || 'inferred'} ${token.value} ${entry.name}`;
          const symbol = makeSymbol({
            name: entry.name,
            kind,
            type: type || 'inferred',
            signature,
            detail: container ? `member of ${container.name}` :
              (kind === 'global' ? 'global variable' : kind === 'constant' ? 'constant' : 'local variable'),
            block: currentBlock(),
            container: container ? container.name : undefined
          }, entry.token.start);
          symbols.push(symbol);
          if (container) container.members.push(symbol);
        }

        i = parsed.next - 1;
        continue;
      }
    }

    // A namespace member: `add() { ... }` inside `functions { }`, with no `fn`.
    if (token.type === 'ident' && code[i + 1] && code[i + 1].value === '(' &&
        namespaceStack.length && functionsBlocks.has(currentBlock())) {
      i = declareFunction(token, i + 1, false) - 1;
      continue;
    }

    // A field inside a struct body: `<type> <name>`.
    if (structStack.length) {
      const top = structStack[structStack.length - 1];
      if (currentBlock() === top.block) {
        const type = parseTypeAt(i, true);
        if (type && code[type.next] && code[type.next].type === 'ident') {
          const nameToken = code[type.next];
          const field = makeSymbol({
            name: nameToken.value,
            kind: 'field',
            type: type.text,
            signature: `${type.text} ${nameToken.value}`,
            detail: `field of ${top.symbol.name}`,
            block: currentBlock(),
            container: top.symbol.name
          }, nameToken.start);
          top.symbol.fields.push(field);
          symbols.push(field);
          i = type.next;
          continue;
        }
      }
    }
  }

  return {
    text,
    tokens,
    starts,
    root,
    symbols,
    structs,
    namespaces,
    functions,
    modules,
    exposed
  };
}

function visibleSymbols(analysis, offset) {
  return analysis.symbols.filter((symbol) =>
    symbol.block &&
    symbol.block.start <= offset &&
    (symbol.block.end === null || offset <= symbol.block.end) &&
    symbol.offset <= offset);
}

function findSymbol(analysis, name, offset) {
  const visible = visibleSymbols(analysis, offset).filter((symbol) => symbol.name === name);
  if (visible.length) return visible[visible.length - 1];
  const all = analysis.symbols.filter((symbol) => symbol.name === name);
  return all.length ? all[all.length - 1] : null;
}

function baseType(type) {
  if (!type) return '';
  return String(type)
    .replace(/^\*+/, '')
    .replace(/\[\]?$/, '')
    .replace(/<.*$/, '')
    .trim();
}

function completionContext(analysis, offset) {
  if (isInsideNonCode(analysis.tokens, offset)) return null;
  const before = analysis.text.slice(0, offset);
  const member = /([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)?$/.exec(before);
  if (member) return { kind: 'member', qualifier: member[1], prefix: member[2] || '' };
  const word = /([A-Za-z_][A-Za-z0-9_]*)$/.exec(before);
  return { kind: 'general', prefix: word ? word[1] : '' };
}

function signatureContext(analysis, offset) {
  const tokens = analysis.tokens;
  let depth = 0;
  let open = -1;

  for (let i = tokens.length - 1; i >= 0; i--) {
    const token = tokens[i];
    if (token.start >= offset) continue;
    if (token.type === 'comment' || token.type === 'string' ||
        token.type === 'char' || token.type === 'newline') continue;
    if (token.value === ')') {
      depth++;
    } else if (token.value === '(') {
      if (depth === 0) {
        open = i;
        break;
      }
      depth--;
    }
  }

  if (open < 1) return null;

  let j = open - 1;
  while (j >= 0 && (tokens[j].type === 'comment' || tokens[j].type === 'newline')) j--;
  const nameToken = tokens[j];
  if (!nameToken || nameToken.type !== 'ident') return null;

  let callee = nameToken.value;
  if (j >= 2 && tokens[j - 1].value === '.' && tokens[j - 2].type === 'ident') {
    callee = `${tokens[j - 2].value}.${nameToken.value}`;
  }

  let nested = 0;
  let commas = 0;
  for (let i = open + 1; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.start >= offset) break;
    if (token.type === 'comment' || token.type === 'string' ||
        token.type === 'char' || token.type === 'newline') continue;
    if (token.value === '(' || token.value === '[' || token.value === '{') nested++;
    else if (token.value === ')' || token.value === ']' || token.value === '}') nested--;
    else if (token.value === ',' && nested === 0) commas++;
  }

  return { callee, activeParameter: commas };
}

function memberSymbols(analysis, qualifier, offset) {
  const symbol = findSymbol(analysis, qualifier, offset);
  if (symbol) {
    if (symbol.kind === 'namespace') return { source: 'symbols', entries: symbol.members || [] };
    if (baseType(symbol.type) === 'File') return { source: 'data', entries: FILE_METHODS };
    if (baseType(symbol.type) === 'Task') return { source: 'data', entries: {} };
    const struct = analysis.structs.get(baseType(symbol.type));
    if (struct) return { source: 'symbols', entries: struct.fields || [] };
  }

  const namespace = NAMESPACES[qualifier];
  if (namespace) return { source: 'data', entries: namespace.members };

  if (qualifier === 'File') return { source: 'data', entries: FILE_METHODS };

  return null;
}

module.exports = {
  analyzeDocument,
  tokenize,
  positionAt,
  isInsideNonCode,
  visibleSymbols,
  findSymbol,
  baseType,
  completionContext,
  signatureContext,
  memberSymbols,
  returnTypesFromSignature
};
