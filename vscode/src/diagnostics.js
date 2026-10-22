'use strict';

// Turn the compiler's human-readable diagnostics into positions. The reporter
// prints one header per diagnostic, then the source line and a caret line:
//
//   error: hello.bt:3: expected an expression
//       3 | local x =
//         |         ^

const HEADER = /^(error|warning): (.+?):(\d+): (.*)$/;
const CARET = /^ *\| ( *)(\^+)/;

function parseDiagnostics(output) {
  const lines = String(output || '').split(/\r?\n/);
  const diagnostics = [];

  for (let i = 0; i < lines.length; i++) {
    const match = HEADER.exec(lines[i]);
    if (!match) continue;

    let column = 1;
    let span = 1;
    for (let j = i + 1; j < Math.min(i + 4, lines.length); j++) {
      const caret = CARET.exec(lines[j]);
      if (caret) {
        column = caret[1].length + 1;
        span = caret[2].length;
        break;
      }
    }

    diagnostics.push({
      severity: match[1],
      file: match[2],
      line: Number(match[3]),
      column,
      span,
      message: match[4]
    });
  }

  return diagnostics;
}

module.exports = { parseDiagnostics };
