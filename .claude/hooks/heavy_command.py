"""Classify shell command positions without treating quoted prose as execution."""
import re
import shlex
from pathlib import PurePosixPath

PACKAGE_MANAGERS = frozenset({'pnpm', 'npm', 'npx', 'yarn', 'bun', 'bunx', 'corepack'})
PACKAGE_VERBS = frozenset({'test', 'build', 'install', 'ci', 'i'})
TEST_RUNNERS = frozenset({'vitest', 'vitest.mjs', 'vitest.js', 'jest', 'jest.js'})


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


def without_options(words, boolean_flags=frozenset()):
    result = list(words)
    value_flags = {'--filter', '-F', '--dir', '-C', '--cwd', '--prefix', '--workspace',
                   '-w', '--package', '-p', '--config', '-c', '--userconfig', '-u', '--unset'}
    while result and result[0].startswith('-'):
        first, *result = result
        if first in value_flags and first not in boolean_flags and result:
            result = result[1:]
    return result


def without_prefixes(words):
    while words and (re.match(r'^\w+=', words[0]) or words[0] in {'then', 'do', 'if', '!', 'exec', 'command', 'time'}):
        words = words[1:]
    return words


def inspect_words(words, custom):
    words = without_prefixes(words)
    if not words:
        return None
    name = PurePosixPath(words[0]).name
    rest = words[1:]
    if name == 'with-heavy-lock':
        return None  # The supervisor, not an environment flag, owns nested admission.
    if name == 'eval':
        return classify(' '.join(rest), custom)
    if name in {'echo', 'printf', 'cat', 'rg', 'grep', 'sed', 'awk'}:
        return None
    if name in {'env', 'nice', 'timeout', 'gtimeout', 'nohup'}:
        if name in {'timeout', 'gtimeout'}:
            rest = without_options(rest)[1:]
        elif name == 'nice' and rest[:1] == ['-n']:
            rest = rest[2:]
        return inspect_words(without_options(rest), custom)
    if name in PACKAGE_MANAGERS:
        if name == 'yarn' and any(x in rest for x in {'--help', '-h', '--version', '-v'}):
            return None
        rest = without_options(rest, {'-w'} if name == 'pnpm' else frozenset())
        if name == 'yarn' and not rest:
            return 'package-install'
        if rest[:1] in (['exec'], ['run'], ['dlx']):
            rest = without_options(rest[1:])
        if rest and rest[0].split(':')[0] in PACKAGE_VERBS:
            return 'package-' + rest[0]
        return inspect_words(rest, custom)
    if name in TEST_RUNNERS:
        return None if any(x in rest for x in ['--version', '--help', '-h']) else 'unit-tests'
    if name in {'node', 'nodejs'}:
        return inspect_words(without_options(rest), custom)
    if name == 'next' and rest[:1] == ['build']:
        return 'build'
    if name == 'cdk' and rest and rest[0] in {'synth', 'diff', 'deploy', 'watch'}:
        return 'cdk'
    if name == 'turbo' and any(x.split(':')[0] in {'test', 'build', 'typecheck'} for x in rest):
        return 'workspace-jobs'
    if name in custom and verbs_match(custom[name], rest):
        return 'project-command'
    for i, word in enumerate(words):
        if PurePosixPath(word).name in {'bash', 'zsh', 'sh'}:
            for j in range(i + 1, len(words)):
                if words[j] in {'-c', '-lc', '-ic'} and j + 1 < len(words):
                    return classify(words[j + 1], custom)
            return inspect_words(words[i + 1:], custom)
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


def classify(command, custom=None):
    for segment in segments(command):
        found = inspect_words(segment, custom or {})
        if found:
            return found
    return None


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
