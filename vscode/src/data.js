'use strict';

// Language reference data shared by completion, hover and signature help.
// The source of truth is baton-spec.md; keep this file in step with it.

const KEYWORDS = {
  local: {
    detail: 'local',
    documentation: 'Declares a mutable variable or global. `i local count = 0`.\n\nThe type prefix is optional, but omitting it produces an inference warning in the current compiler.'
  },
  const: {
    detail: 'const',
    documentation: 'Declares an immutable variable or global. The value must be known at compile time for a top-level `const`.'
  },
  fn: {
    detail: 'fn',
    documentation: 'Declares a function: `fn add(i a, i b) -> i { return a + b }`.\n\nFunctions must be declared at the top level, before they are called.'
  },
  ns: {
    detail: 'ns',
    documentation: 'Declares a namespace. Parameters on the `ns` line are shared by every function inside `functions { }`.'
  },
  functions: {
    detail: 'functions',
    documentation: 'Marks the functions that belong to an `ns` namespace.'
  },
  struct: {
    detail: 'struct',
    documentation: 'Declares a value type with named fields: `struct Point { i x; i y }`. Structs copy by value.'
  },
  if: {
    detail: 'if',
    documentation: 'Runs a block when its condition is `true`. The condition must be `b`; Baton has no truthiness.'
  },
  elf: {
    detail: 'elf',
    documentation: 'The else-if keyword: `if a { } elf b { } else { }`.'
  },
  else: {
    detail: 'else',
    documentation: 'The fallback branch of an `if` / `elf` chain.'
  },
  while: {
    detail: 'while',
    documentation: 'Runs a block while its condition is `true`.'
  },
  for: {
    detail: 'for',
    documentation: 'Iterates a range (`for i in 0..10`) or a list (`for x in items`). The loop variable is read-only.'
  },
  in: {
    detail: 'in',
    documentation: 'Separates the loop variable from the range or collection in a `for` loop.'
  },
  by: {
    detail: 'by',
    documentation: 'Sets the step of a range: `for i in 10..0 by -1`. A negative step counts down.'
  },
  loop: {
    detail: 'loop',
    documentation: 'An unconditional loop. Leave it with `break` or `return`.'
  },
  break: {
    detail: 'break',
    documentation: 'Leaves the nearest loop. `break outer` leaves the loop labelled `outer:`.'
  },
  continue: {
    detail: 'continue',
    documentation: 'Skips to the next pass of the nearest loop. `continue outer` targets a labelled loop.'
  },
  return: {
    detail: 'return',
    documentation: 'Returns a value from a function. `return value -> i` states the type explicitly.'
  },
  as: {
    detail: 'as',
    documentation: 'Explicit conversion: `count as u8`, `2.7 as i`. Required for narrowing and signed/unsigned changes.'
  },
  and: {
    detail: 'and',
    documentation: 'Short-circuit logical and. Both operands must be `b`.'
  },
  or: {
    detail: 'or',
    documentation: 'Short-circuit logical or. Both operands must be `b`.'
  },
  not: {
    detail: 'not',
    documentation: 'Logical negation of a `b`.'
  },
  true: {
    detail: 'true',
    documentation: 'The boolean true value.'
  },
  false: {
    detail: 'false',
    documentation: 'The boolean false value.'
  },
  det: {
    detail: 'det',
    documentation: 'The determined return type on an `ns` declaration: each function’s type is worked out from its `return`.'
  },
  mod: {
    detail: 'mod',
    documentation: 'Imports a module: `mod calc get-from "lib/calc.bt"`. Omit the alias to use the file’s name.'
  },
  getfrom: {
    detail: 'get-from',
    documentation: 'Follows `mod [alias]` and the quoted module path.'
  },
  expose: {
    detail: 'expose',
    documentation: 'Publishes names from a `.bt` module. Everything not listed stays private to the file.'
  },
  extern: {
    detail: 'extern',
    documentation: 'Declares an existing C function: `extern fn puts(s) -> i`.'
  },
  match: {
    detail: 'match',
    documentation: 'Selects one arm by value or range: `match n { 0 { } 1..=9 { } else { } }`.'
  }
};

// `get-from` is a keyword with a hyphen; the completion code looks for this
// alias so the key above can stay a normal identifier.
KEYWORDS['get-from'] = KEYWORDS.getfrom;
delete KEYWORDS.getfrom;

const TYPES = {
  i: { detail: 'i — signed 64-bit integer', documentation: 'Signed 64-bit integer.' },
  i8: { detail: 'i8 — signed 8-bit integer', documentation: 'Signed 8-bit integer.' },
  i16: { detail: 'i16 — signed 16-bit integer', documentation: 'Signed 16-bit integer.' },
  i32: { detail: 'i32 — signed 32-bit integer', documentation: 'Signed 32-bit integer.' },
  i64: { detail: 'i64 — signed 64-bit integer', documentation: 'Signed 64-bit integer; the same type as `i`.' },
  u: { detail: 'u — unsigned 64-bit integer', documentation: 'Unsigned 64-bit integer.' },
  u8: { detail: 'u8 — unsigned 8-bit integer', documentation: 'Unsigned 8-bit integer.' },
  u16: { detail: 'u16 — unsigned 16-bit integer', documentation: 'Unsigned 16-bit integer.' },
  u32: { detail: 'u32 — unsigned 32-bit integer', documentation: 'Unsigned 32-bit integer.' },
  u64: { detail: 'u64 — unsigned 64-bit integer', documentation: 'Unsigned 64-bit integer; the same type as `u`.' },
  f: { detail: 'f — 64-bit float', documentation: 'Double-precision floating point.' },
  f32: { detail: 'f32 — 32-bit float', documentation: 'Single-precision floating point.' },
  b: { detail: 'b — bool', documentation: 'Boolean. Conditions must be `b`; there is no truthiness.' },
  c: { detail: 'c — char', documentation: 'A single byte (ASCII).' },
  s: { detail: 's — string', documentation: 'An immutable, reference-counted byte string.' },
  File: { detail: 'File — file handle', documentation: 'An opaque, reference-counted file handle. Zero-initialization is the closed handle.' },
  Task: { detail: 'Task — task handle', documentation: 'An opaque, reference-counted handle to a cooperative task.' }
};

const FILE_METHODS = {
  write: {
    signature: 'f.write(s value) -> b',
    parameters: ['s value'],
    documentation: 'Writes a string to the file. Returns `false` if the write failed.'
  },
  line: {
    signature: 'f.line() -> s, b',
    parameters: [],
    documentation: 'Reads the next line without its newline. The `b` is `false` at end of file.'
  },
  read: {
    signature: 'f.read(i count) -> s',
    parameters: ['i count'],
    documentation: 'Reads up to `count` bytes. Returns `""` at end of file.'
  },
  close: {
    signature: 'f.close()',
    parameters: [],
    documentation: 'Closes the file now. The handle is also closed when the last reference goes out of scope.'
  },
  seek: {
    signature: 'f.seek(i position) -> b',
    parameters: ['i position'],
    documentation: 'Moves to an absolute byte position from the start of the file.'
  },
  tell: {
    signature: 'f.tell() -> i',
    parameters: [],
    documentation: 'Returns the current byte position in the file.'
  }
};

const NAMESPACES = {
  math: {
    detail: 'math — standard library',
    documentation: 'Mathematical functions. Using `math` links libm.',
    members: {
      sqrt: { signature: 'math.sqrt(f x) -> f', parameters: ['f x'], documentation: 'Square root.' },
      abs: { signature: 'math.abs(f x) -> f', parameters: ['f x'], documentation: 'Absolute value.' },
      floor: { signature: 'math.floor(f x) -> f', parameters: ['f x'], documentation: 'Largest integer not greater than `x`.' },
      ceil: { signature: 'math.ceil(f x) -> f', parameters: ['f x'], documentation: 'Smallest integer not less than `x`.' },
      round: { signature: 'math.round(f x) -> f', parameters: ['f x'], documentation: 'Rounds to the nearest integer.' },
      min: { signature: 'math.min(f a, f b) -> f', parameters: ['f a', 'f b'], documentation: 'The smaller of two values.' },
      max: { signature: 'math.max(f a, f b) -> f', parameters: ['f a', 'f b'], documentation: 'The larger of two values.' },
      sin: { signature: 'math.sin(f x) -> f', parameters: ['f x'], documentation: 'Sine, in radians.' },
      cos: { signature: 'math.cos(f x) -> f', parameters: ['f x'], documentation: 'Cosine, in radians.' },
      tan: { signature: 'math.tan(f x) -> f', parameters: ['f x'], documentation: 'Tangent, in radians.' },
      atan: { signature: 'math.atan(f x) -> f', parameters: ['f x'], documentation: 'Arctangent, in radians.' },
      atan2: { signature: 'math.atan2(f y, f x) -> f', parameters: ['f y', 'f x'], documentation: 'Arctangent of `y / x`, using the signs to choose the quadrant.' },
      pow: { signature: 'math.pow(f x, f y) -> f', parameters: ['f x', 'f y'], documentation: '`x` raised to `y`.' },
      exp: { signature: 'math.exp(f x) -> f', parameters: ['f x'], documentation: '`e` raised to `x`.' },
      log: { signature: 'math.log(f x) -> f', parameters: ['f x'], documentation: 'Natural logarithm.' },
      pi: { signature: 'math.pi', detail: 'f const', documentation: 'The constant pi.' },
      e: { signature: 'math.e', detail: 'f const', documentation: 'The constant e.' }
    }
  },
  str: {
    detail: 'str — standard library',
    documentation: 'String helpers. Strings are immutable, so these return new strings.',
    members: {
      lower: { signature: 'str.lower(s value) -> s', parameters: ['s value'], documentation: 'Converts to lower case.' },
      upper: { signature: 'str.upper(s value) -> s', parameters: ['s value'], documentation: 'Converts to upper case.' },
      has: { signature: 'str.has(s value, s part) -> b', parameters: ['s value', 's part'], documentation: 'Whether `value` contains `part`.' },
      starts: { signature: 'str.starts(s value, s prefix) -> b', parameters: ['s value', 's prefix'], documentation: 'Whether `value` starts with `prefix`.' },
      ends: { signature: 'str.ends(s value, s suffix) -> b', parameters: ['s value', 's suffix'], documentation: 'Whether `value` ends with `suffix`.' },
      trim: { signature: 'str.trim(s value) -> s', parameters: ['s value'], documentation: 'Removes surrounding whitespace.' },
      split: { signature: 'str.split(s value, s separator) -> s[]', parameters: ['s value', 's separator'], documentation: 'Splits a string into a list of parts.' },
      join: { signature: 'str.join(s[] parts, s separator) -> s', parameters: ['s[] parts', 's separator'], documentation: 'Joins a list of strings with a separator.' }
    }
  },
  list: {
    detail: 'list — standard library',
    documentation: 'Operations on growable lists. Lists share on assignment; `clone()` makes an independent copy.',
    members: {
      sort: { signature: 'list.sort(T[] items)', parameters: ['T[] items'], documentation: 'Sorts a list in place. Requires an ordered item type.' },
      reverse: { signature: 'list.reverse(T[] items)', parameters: ['T[] items'], documentation: 'Reverses a list in place.' },
      indexof: { signature: 'list.indexof(T[] items, T value) -> i, b', parameters: ['T[] items', 'T value'], documentation: 'Returns the index and `true`, or `0` and `false` when the value is absent.' }
    }
  },
  rand: {
    detail: 'rand — standard library',
    documentation: 'C’s `rand`. Fine for games, not for cryptography.',
    members: {
      int: { signature: 'rand.int(i low, i high) -> i, b', parameters: ['i low', 'i high'], documentation: 'A random integer in the inclusive range.' },
      float: { signature: 'rand.float() -> f', parameters: [], documentation: 'A random float between 0 and 1.' },
      seed: { signature: 'rand.seed(i seed)', parameters: ['i seed'], documentation: 'Seeds the generator.' }
    }
  },
  time: {
    detail: 'time — standard library',
    documentation: 'Clock helpers.',
    members: {
      now: { signature: 'time.now() -> i', parameters: [], documentation: 'Milliseconds since the Unix epoch.' },
      tick: { signature: 'time.tick() -> i', parameters: [], documentation: 'Milliseconds since the program started.' }
    }
  },
  fs: {
    detail: 'fs — standard library',
    documentation: 'Directory helpers. `fs.err()` gives the detail behind a `false` result.',
    members: {
      exists: { signature: 'fs.exists(s path) -> b', parameters: ['s path'], documentation: 'Whether a path exists.' },
      list: { signature: 'fs.list(s path) -> s[], b', parameters: ['s path'], documentation: 'Entry names in a directory, not full paths.' },
      mkdir: { signature: 'fs.mkdir(s path) -> b', parameters: ['s path'], documentation: 'Creates a directory.' },
      remove: { signature: 'fs.remove(s path) -> b', parameters: ['s path'], documentation: 'Removes a file or directory.' },
      err: { signature: 'fs.err() -> s', parameters: [], documentation: 'The message from the last failed file operation.' }
    }
  },
  task: {
    detail: 'task — standard library',
    documentation: 'Cooperative tasks. Tasks run on one thread and yield at `task.wait` and `task.join`.',
    members: {
      spawn: { signature: 'task.spawn(call) -> Task', parameters: ['call'], documentation: 'Starts a new task. The call is evaluated where it is written.' },
      wait: { signature: 'task.wait(i ms)', parameters: ['i ms'], documentation: 'Yields the current task for a number of milliseconds. `wait(0)` yields immediately.' },
      join: { signature: 'task.join(Task task) -> i', parameters: ['Task task'], documentation: 'Waits for a task and returns its `-> i` result.' },
      stop: { signature: 'task.stop(Task task)', parameters: ['Task task'], documentation: 'Cancels a task that has not finished.' }
    }
  }
};

const BUILTINS = {
  print: {
    signature: 'print(...values)',
    parameters: ['...values'],
    documentation: 'Writes its values separated by spaces, then a newline. Accepts `s`, `i`, `f`, `b` and `c`.'
  },
  write: {
    signature: 'write(...values)',
    parameters: ['...values'],
    documentation: 'Like `print`, without the trailing newline.'
  },
  input: {
    signature: 'input() -> s',
    parameters: [],
    documentation: 'Reads one line from stdin without its newline. Returns `""` at end of file.'
  },
  panic: {
    signature: 'panic(s message)',
    parameters: ['s message'],
    documentation: 'Prints the message and a source line, then exits with a nonzero status.'
  },
  toi: {
    signature: 'toi(value) -> i',
    parameters: ['value'],
    documentation: 'Converts a string or float to an integer. Returns `0` on bad input.'
  },
  tof: {
    signature: 'tof(value) -> f',
    parameters: ['value'],
    documentation: 'Converts a string or integer to a float. Returns `0.0` on bad input.'
  },
  tos: {
    signature: 'tos(value) -> s',
    parameters: ['value'],
    documentation: 'Converts a value to a string.'
  },
  tob: {
    signature: 'tob(value) -> b',
    parameters: ['value'],
    documentation: 'Converts a value to a boolean.'
  },
  tryi: {
    signature: 'tryi(s text) -> i, b',
    parameters: ['s text'],
    documentation: 'Parses an integer and reports whether it worked: `i local n, b ok = tryi("42")`.'
  },
  tryf: {
    signature: 'tryf(s text) -> f, b',
    parameters: ['s text'],
    documentation: 'Parses a float and reports whether it worked.'
  },
  len: {
    signature: 'len(value) -> i',
    parameters: ['value'],
    documentation: 'Length of a string, fixed array or list.'
  },
  push: {
    signature: 'push(T[] list, T value)',
    parameters: ['T[] list', 'T value'],
    documentation: 'Appends a value to a growable list.'
  },
  pop: {
    signature: 'pop(T[] list) -> T',
    parameters: ['T[] list'],
    documentation: 'Removes and returns the last item of a list.'
  },
  clone: {
    signature: 'clone(value)',
    parameters: ['value'],
    documentation: 'Makes an independent copy of a list. Strings inside stay shared.'
  },
  isnull: {
    signature: 'isnull(*T pointer) -> b',
    parameters: ['*T pointer'],
    documentation: 'Tests a raw pointer for the null address.'
  },
  cstr: {
    signature: 'cstr(s text) -> *c',
    parameters: ['s text'],
    documentation: 'Hands C the null-terminated bytes of a string. Do not free the result.'
  },
  alloc: {
    signature: 'alloc(TYPE, i count) -> *TYPE',
    parameters: ['TYPE', 'i count'],
    documentation: 'Allocates zero-filled storage for `count` values of `TYPE`. Allocation failure panics.'
  },
  free: {
    signature: 'free(*T pointer)',
    parameters: ['*T pointer'],
    documentation: 'Releases a block returned by `alloc`. Refcounted values are never freed by hand.'
  },
  fopen: {
    signature: 'fopen(s path, s mode) -> File, b',
    parameters: ['s path', 's mode'],
    documentation: 'Opens a file in `"r"`, `"w"` or `"a"` mode. The `b` is `false` when the file cannot be opened.'
  },
  readfile: {
    signature: 'readfile(s path) -> s, b',
    parameters: ['s path'],
    documentation: 'Reads a whole file. The `b` reports success.'
  },
  writefile: {
    signature: 'writefile(s path, s text) -> b',
    parameters: ['s path', 's text'],
    documentation: 'Writes a whole file. The `b` reports success.'
  }
};

module.exports = {
  KEYWORDS,
  TYPES,
  BUILTINS,
  NAMESPACES,
  FILE_METHODS
};
