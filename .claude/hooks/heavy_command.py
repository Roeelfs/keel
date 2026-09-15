"""Classify shell command positions without treating quoted prose as execution."""
import re
import shlex
from pathlib import Path, PurePosixPath

PACKAGE_MANAGERS = frozenset({'pnpm', 'npm', 'npx', 'yarn', 'bun', 'bunx', 'corepack'})
PACKAGE_VERBS = frozenset({'test', 'build', 'install', 'ci', 'i'})
TEST_RUNNERS = frozenset({'vitest', 'vitest.mjs', 'vitest.js', 'jest', 'jest.js'})

# A project-command that owns its own heavy-slot lock internally (enforced by that project's own
# lint) can carry this marker to opt out of the shared runner. Only the custom-rule branch below
# ever consults it; built-in kinds (turbo, vitest, pnpm test, cdk, next build) are never exempt.
SELF_LOCKING_MARKER_BYTES = 8192
SELF_LOCKING_MARKER = re.compile(rb'(?m)^# keel:self-locking\b')


def is_self_locking(word, cwd):
    """Resolve `word` to a script and check its first 8KiB for the self-locking marker.

    Fails closed: an absolute path is used as-is; a path containing '/' resolves against `cwd`
    (never exempt if `cwd` is missing); a bare name is never exempt, even via PATH. Anything that
    is not a readable regular file (missing, a directory, unreadable) is never exempt. Symlinks
    are followed.
    """
    if not word:
        return False
    if word.startswith('/'):
        candidate = Path(word)
    elif '/' in word:
        if not cwd:
            return False
        candidate = Path(cwd) / word
    else:
        return False
    try:
        if not candidate.is_file():
            return False
        with candidate.open('rb') as handle:
            head = handle.read(SELF_LOCKING_MARKER_BYTES)
    except OSError:
        return False
    return SELF_LOCKING_MARKER.search(head) is not None


# Any of these words anywhere can move the directory a later relative path resolves against, including
# from inside a group, a loop, a function body, `builtin`, `eval` or a sourced file.
CWD_CHANGING_WORDS = frozenset({'cd', 'pushd', 'popd', 'builtin', 'source', '.', 'eval', '{', '}'})
FUNCTION_DEFINITION = re.compile(r'\w+\s*\(\s*\)')


def may_change_cwd(command, parsed):
    """True if the payload cwd may be stale anywhere in `command`; the exemption is then off for all of it.

    Position is deliberately ignored: a shell keyword, group or function can run a `cd` before a
    segment that follows it in the text. `git -C <dir>` never moves the shell, but over-refusing is
    the safe direction, so it counts too.
    """
    if FUNCTION_DEFINITION.search(strip_heredocs(command)):
        return True
    for segment in parsed:
        if any(word in CWD_CHANGING_WORDS for word in segment):
            return True
        words = without_prefixes(list(segment))
        if words and PurePosixPath(words[0]).name == 'git' and any(w.split('=', 1)[0] == '-C' for w in words[1:]):
            return True
    return False


def strip_heredocs(command):
    output, pending = [], []
    pattern = re.compile(r"(?<!<)<<-?\s*(?!<)(?:'([^']+)'|\"([^\"]+)\"|([\w]+))")
    for line in command.splitlines():
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        output.append(line)
        pending.extend(next(x for x in match.groups() if x) for match in pattern.finditer(line))
    return '\n'.join(output)


VALUE_FLAGS = frozenset({'--filter', '-F', '--dir', '-C', '--cwd', '--prefix', '--workspace',
                          '-w', '--package', '-p', '--config', '-c', '--userconfig', '-u',
                          '--unset', '--chdir'})
# A flag that changes the directory a following relative path resolves against. Present on
# `env` (`-C`/`--chdir`) and on package managers (`pnpm -C/--dir`, `npm --prefix`, `yarn --cwd`).
CWD_FLAGS = frozenset({'-C', '--chdir', '--dir', '--prefix', '--cwd'})


def without_options(words, boolean_flags=frozenset()):
    result = list(words)
    while result and result[0].startswith('-'):
        first, *result = result
        bare = first.split('=', 1)[0]
        if bare in VALUE_FLAGS and bare not in boolean_flags and '=' not in first and result:
            result = result[1:]
    return result


def has_cwd_flag(words, boolean_flags=frozenset()):
    """True if a leading option in `words` changes the directory a relative path resolves
    against (`-C dir`, `--chdir[=dir]`, `--dir[=dir]`, `--prefix[=dir]`, `--cwd[=dir]`). Walks
    the same leading-option run as `without_options`, so a value-consuming flag before it does
    not shift a later cwd flag out of view."""
    remaining = list(words)
    while remaining and remaining[0].startswith('-'):
        first, *remaining = remaining
        bare = first.split('=', 1)[0]
        if bare in CWD_FLAGS:
            return True
        if bare in VALUE_FLAGS and bare not in boolean_flags and '=' not in first and remaining:
            remaining = remaining[1:]
    return False


def without_prefixes(words):
    while words and (re.match(r'^\w+=', words[0]) or words[0] in {'then', 'do', 'if', '!', 'exec', 'command', 'time'}):
        words = words[1:]
    return words


def inspect_words(words, custom, cwd=None, allow_exempt=True):
    words = without_prefixes(words)
    if not words:
        return None
    name = PurePosixPath(words[0]).name
    rest = words[1:]
    if name == 'with-heavy-lock':
        return None  # The supervisor, not an environment flag, owns nested admission.
    if name == 'eval':
        return _classify(' '.join(rest), custom, cwd, allow_exempt)
    if name in {'echo', 'printf', 'cat', 'rg', 'grep', 'sed', 'awk'}:
        return None
    if name in {'env', 'nice', 'timeout', 'gtimeout', 'nohup'}:
        if name in {'timeout', 'gtimeout'}:
            rest = without_options(rest)[1:]
        elif name == 'nice' and rest[:1] == ['-n']:
            rest = rest[2:]
        elif name == 'env' and has_cwd_flag(rest):
            allow_exempt = False  # -C/--chdir changes where a later relative path resolves.
        return inspect_words(without_options(rest), custom, cwd, allow_exempt)
    if name in PACKAGE_MANAGERS:
        if name == 'yarn' and any(x in rest for x in {'--help', '-h', '--version', '-v'}):
            return None
        manager_boolean = {'-w'} if name == 'pnpm' else frozenset()
        if has_cwd_flag(rest, manager_boolean):
            allow_exempt = False  # -C/--dir/--prefix/--cwd changes the resolution directory.
        rest = without_options(rest, manager_boolean)
        if name == 'yarn' and not rest:
            return 'package-install'
        if rest[:1] in (['exec'], ['run'], ['dlx']):
            if has_cwd_flag(rest[1:]):
                allow_exempt = False  # `exec --prefix <dir>` / `exec -C <dir>` moves resolution too.
            rest = without_options(rest[1:])
        if rest and rest[0].split(':')[0] in PACKAGE_VERBS:
            return 'package-' + rest[0]
        return inspect_words(rest, custom, cwd, allow_exempt)
    if name in TEST_RUNNERS:
        return None if any(x in rest for x in ['--version', '--help', '-h']) else 'unit-tests'
    if name in {'node', 'nodejs'}:
        return inspect_words(without_options(rest), custom, cwd, allow_exempt)
    if name == 'next' and rest[:1] == ['build']:
        return 'build'
    if name == 'cdk' and rest and rest[0] in {'synth', 'diff', 'deploy', 'watch'}:
        return 'cdk'
    if name == 'turbo' and any(x.split(':')[0] in {'test', 'build', 'typecheck'} for x in rest):
        return 'workspace-jobs'
    if name in custom and verbs_match(custom[name], rest):
        if allow_exempt and is_self_locking(words[0], cwd):
            return None
        return 'project-command'
    for i, word in enumerate(words):
        if PurePosixPath(word).name in {'bash', 'zsh', 'sh'}:
            for j in range(i + 1, len(words)):
                if words[j] in {'-c', '-lc', '-ic'} and j + 1 < len(words):
                    return _classify(words[j + 1], custom, cwd, allow_exempt)
            return inspect_words(words[i + 1:], custom, cwd, allow_exempt)
    return None


def segments(command):
    lexer = shlex.shlex(strip_heredocs(command), posix=True, punctuation_chars=';&|()\n')
    lexer.whitespace = ' \t\r'
    lexer.whitespace_split = True
    segment = []
    for token in lexer:
        if token and all(c in ';&|()\n' for c in token):
            yield segment
            segment = []
        else:
            segment.append(token)
    yield segment


def _classify(command, custom, cwd, allow_exempt):
    parsed = list(segments(command))
    allow_exempt = allow_exempt and not may_change_cwd(command, parsed)
    for segment in parsed:
        found = inspect_words(segment, custom, cwd, allow_exempt)
        if found:
            return found
    return None


def classify(command, custom=None, cwd=None):
    """`cwd` is the PreToolUse payload's cwd (Claude and Codex both send it); used only to
    resolve a relative self-locking script path. Never guessed from the current process."""
    return _classify(command, custom or {}, cwd, True)


def raw_words(command):
    """Word basenames of text shlex rejected: quoting erased, every shell operator a break."""
    text = re.sub(r"[\"'\\]", '', strip_heredocs(command))
    return [PurePosixPath(word).name for word in re.split(r"[\s;&|()<>`$={}]+", text) if word]


def unparsed_heavy_token(command, custom=None):
    """Name a heavy token anywhere in unparseable text; ignoring word position over-reports by design."""
    found, later = None, set()
    for name in reversed(raw_words(command)):
        if (name in TEST_RUNNERS or name in {'turbo', 'cdk'} or name in (custom or {})
                or name in PACKAGE_MANAGERS and (name == 'yarn' or later & PACKAGE_VERBS)
                or name == 'next' and 'build' in later):
            found = name
        later.add(name.split(':')[0])
    return found


def unparsed_rule_name(command, rules):
    """Name the first rule command anywhere in unparseable text."""
    return next((name for name in raw_words(command) if name in rules), None)


def verbs_match(verbs, args):
    """Match the first argument or `*`; a `!word ...` entry excludes args that start with those words."""
    for entry in verbs:
        excluded = entry[1:].split() if entry.startswith('!') else None
        if excluded and args[:len(excluded)] == excluded:
            return False
    return '*' in verbs or bool(args and args[0] in verbs)


def background_required(command, rules):
    """Name the rule a command segment matches, looking through a leading with-heavy-lock."""
    for segment in segments(command):
        words = without_prefixes(segment)
        if words and PurePosixPath(words[0]).name == 'with-heavy-lock':
            words = words[2:] if words[1:2] == ['--'] else words[1:]
        name = PurePosixPath(words[0]).name if words else None
        if name in rules and verbs_match(rules[name], words[1:]):
            return name
    return None
