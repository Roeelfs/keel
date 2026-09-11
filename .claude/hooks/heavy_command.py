"""Classify shell command positions without treating quoted prose as execution."""
import re
import shlex
from pathlib import PurePosixPath


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


def inspect_words(words, custom):
    while words and (re.match(r'^\w+=', words[0]) or words[0] in {'then', 'do', 'if', '!', 'exec', 'command', 'time'}):
        words = words[1:]
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
    if name in {'pnpm', 'npm', 'npx', 'yarn', 'bun', 'bunx', 'corepack'}:
        if name == 'yarn' and any(x in rest for x in {'--help', '-h', '--version', '-v'}):
            return None
        rest = without_options(rest, {'-w'} if name == 'pnpm' else frozenset())
        if name == 'yarn' and not rest:
            return 'package-install'
        if rest[:1] in (['exec'], ['run'], ['dlx']):
            rest = without_options(rest[1:])
        if rest and rest[0].split(':')[0] in {'test', 'build', 'install', 'ci', 'i'}:
            return 'package-' + rest[0]
        return inspect_words(rest, custom)
    if name in {'vitest', 'vitest.mjs', 'vitest.js', 'jest', 'jest.js'}:
        return None if any(x in rest for x in ['--version', '--help', '-h']) else 'unit-tests'
    if name in {'node', 'nodejs'}:
        return inspect_words(without_options(rest), custom)
    if name == 'next' and rest[:1] == ['build']:
        return 'build'
    if name == 'cdk' and rest and rest[0] in {'synth', 'diff', 'deploy', 'watch'}:
        return 'cdk'
    if name == 'turbo' and any(x.split(':')[0] in {'test', 'build', 'typecheck'} for x in rest):
        return 'workspace-jobs'
    if name in custom and ('*' in custom[name] or (rest and rest[0] in custom[name])):
        return 'project-command'
    for i, word in enumerate(words):
        if PurePosixPath(word).name in {'bash', 'zsh', 'sh'}:
            for j in range(i + 1, len(words)):
                if words[j] in {'-c', '-lc', '-ic'} and j + 1 < len(words):
                    return classify(words[j + 1], custom)
            return inspect_words(words[i + 1:], custom)
    return None


def classify(command, custom=None):
    lexer = shlex.shlex(strip_heredocs(command), posix=True, punctuation_chars=';&|()\n')
    lexer.whitespace = ' \t\r'
    lexer.whitespace_split = True
    segment = []
    for token in lexer:
        if token and all(c in ';&|()\n' for c in token):
            found = inspect_words(segment, custom or {})
            if found:
                return found
            segment = []
        else:
            segment.append(token)
    return inspect_words(segment, custom or {})
