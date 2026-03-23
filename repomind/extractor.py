"""Metadata extractor: file classification, path tokens, and header comment tokens."""

from __future__ import annotations

import re

from repomind.models import ClassifiedFile, FileRecord

# ---------------------------------------------------------------------------
# Manifest names (lowercase)
# ---------------------------------------------------------------------------

_MANIFEST_NAMES: frozenset[str] = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "cargo.toml",
        "go.mod",
        "go.sum",
        "setup.py",
        "setup.cfg",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "gemfile",
        "composer.json",
        "requirements.txt",
        "requirements-dev.txt",
        "pipfile",
        "pipfile.lock",  # lockfile but still manifest-adjacent; classified manifest
    }
)

_MANIFEST_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".csproj",
        ".sln",
        ".podspec",
    }
)

# ---------------------------------------------------------------------------
# Config names and patterns (lowercase)
# ---------------------------------------------------------------------------

_CONFIG_NAMES: frozenset[str] = frozenset(
    {
        "makefile",
        "gnumakefile",
        "dockerfile",
        ".env",
        ".env.example",
        ".env.sample",
        ".env.local",
        ".env.test",
        ".gitignore",
        ".gitattributes",
        ".dockerignore",
        "docker-compose.yml",
        "docker-compose.yaml",
        "docker-compose.override.yml",
        "docker-compose.override.yaml",
        "tsconfig.json",
        "jsconfig.json",
        ".eslintrc",
        ".eslintrc.json",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".prettierrc",
        ".prettierrc.json",
        ".prettierrc.js",
        ".babelrc",
        "babel.config.js",
        "babel.config.json",
        "jest.config.js",
        "jest.config.ts",
        "jest.config.cjs",
        "vitest.config.js",
        "vitest.config.ts",
        "vite.config.js",
        "vite.config.ts",
        "webpack.config.js",
        "webpack.config.ts",
        "rollup.config.js",
        "rollup.config.ts",
        ".editorconfig",
        ".nvmrc",
        ".python-version",
        "mypy.ini",
        "pytest.ini",
        "tox.ini",
        "ruff.toml",
        ".flake8",
        ".pylintrc",
        "codecov.yml",
        "codecov.yaml",
        ".travis.yml",
        "renovate.json",
        ".renovaterc",
        "conftest.py",  # pytest fixture root; config role
        "procfile",
        "heroku.yml",
        "app.yaml",       # GCP / App Engine
        "serverless.yml",
        "serverless.yaml",
        "netlify.toml",
        "vercel.json",
    }
)

# Suffix patterns that signal config regardless of exact name.
_CONFIG_SUFFIX_RE: tuple[re.Pattern[str], ...] = (
    re.compile(r"\.config\.(js|ts|mjs|cjs)$"),
    re.compile(r"\.conf$"),
    re.compile(r"\.ini$"),
    re.compile(r"\.cfg$"),
)

# YAML/JSON files inside these top-level directory names are config.
_CI_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".github",
        ".circleci",
        ".gitlab",
        ".bitbucket",
        "jenkins",
        ".drone",
        ".buildkite",
    }
)

# ---------------------------------------------------------------------------
# Entrypoint names (lowercase)
# ---------------------------------------------------------------------------

_ENTRYPOINT_NAMES: frozenset[str] = frozenset(
    {
        "main.py",
        "main.go",
        "main.js",
        "main.ts",
        "main.jsx",
        "main.tsx",
        "server.py",
        "server.js",
        "server.ts",
        "app.py",
        "app.js",
        "app.ts",
        "app.jsx",
        "app.tsx",
        "index.py",
        "index.js",
        "index.ts",
        "index.jsx",
        "index.tsx",
        "manage.py",
        "wsgi.py",
        "asgi.py",
        "cli.py",
        "__main__.py",
        "run.py",
        "start.py",
        "bootstrap.py",
        "application.py",
    }
)

# Files deeper than this are classified as source, not entrypoint.
_ENTRYPOINT_MAX_DEPTH: int = 2

# ---------------------------------------------------------------------------
# Docs names, extensions, and directory names (lowercase)
# ---------------------------------------------------------------------------

_DOC_NAMES: frozenset[str] = frozenset(
    {
        "readme",
        "readme.md",
        "readme.rst",
        "readme.txt",
        "readme.adoc",
        "changelog",
        "changelog.md",
        "changes.md",
        "history.md",
        "contributing",
        "contributing.md",
        "license",
        "license.md",
        "license.txt",
        "architecture.md",
        "design.md",
        "spec.md",
        "api.md",
        "faq.md",
    }
)

_DOC_EXTENSIONS: frozenset[str] = frozenset({".md", ".rst", ".adoc", ".tex"})

_DOC_DIR_NAMES: frozenset[str] = frozenset(
    {
        "docs",
        "doc",
        "documentation",
        "guides",
        "wiki",
        "notes",
        "rfcs",
        "proposals",
        "decisions",
        "adr",
    }
)

# ---------------------------------------------------------------------------
# Test directory and name patterns (lowercase)
# ---------------------------------------------------------------------------

_TEST_DIR_NAMES: frozenset[str] = frozenset(
    {
        "tests",
        "test",
        "__tests__",
        "spec",
        "specs",
        "e2e",
        "integration",
        "unit",
    }
)

_TEST_NAME_RE: tuple[re.Pattern[str], ...] = (
    re.compile(r"^test_"),              # test_foo.py  (pytest)
    re.compile(r"_test\.[a-z]+$"),      # foo_test.go
    re.compile(r"\.test\.[a-z]+$"),     # foo.test.ts
    re.compile(r"\.spec\.[a-z]+$"),     # foo.spec.ts
    re.compile(r"\.stories\.[a-z]+$"),  # Storybook stories
)

# ---------------------------------------------------------------------------
# Source extensions (lowercase) — classify as "source" rather than "other"
# ---------------------------------------------------------------------------

_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".c",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
        ".cs",
        ".php",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".r",
        ".m",
        ".lua",
        ".ex",
        ".exs",
        ".clj",
        ".cljs",
        ".hs",
        ".elm",
        ".dart",
        ".vue",
        ".svelte",
        ".nim",
        ".zig",
        ".ml",
        ".mli",
        ".erl",
        ".fs",
        ".fsx",
    }
)

# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------

# Splits on non-alphanumeric runs and camelCase / acronym boundaries.
_SPLIT_RE: re.Pattern[str] = re.compile(
    r"[^a-zA-Z0-9]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)

# Short tokens and common stop words that add no signal.
_STOP_TOKENS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "is",
        "are",
        "was",
        "be",
        "it",
        "this",
        "that",
        "with",
        "as",
        "by",
        "from",
        "not",
        "use",
        "used",
        "using",
        "get",
        "set",
    }
)

_MIN_TOKEN_LEN: int = 2

# Import tokens that carry no domain signal and must be filtered out.
# Applied on top of _STOP_TOKENS and _MIN_TOKEN_LEN when extracting import tokens.
# Covers the Python standard library modules most commonly imported in any codebase.
# This list is intentionally fixed for Iteration 2; stdlib detection is not attempted.
_IMPORT_STOP_TOKENS: frozenset[str] = frozenset(
    {
        "os",
        "sys",
        "re",
        "io",
        "abc",
        "typing",
        "types",
        "collections",
        "functools",
        "itertools",
        "contextlib",
        "dataclasses",
        "pathlib",
        "logging",
        "warnings",
        "string",
        "enum",
        "datetime",
        "threading",
        "asyncio",
        "inspect",
        "traceback",
        "struct",
        "hashlib",
        "base64",
        "uuid",
        "http",
        "urllib",
        "socket",
        "json",
        "math",
        "time",
        "copy",
        "random",
        "subprocess",
    }
)

# Regex patterns for Python import statements (single-line only in Iteration 2).
_IMPORT_FROM_RE: re.Pattern[str] = re.compile(
    r"^from\s+([\w.]+)\s+import\s+(.+)$"
)
_IMPORT_MODULE_RE: re.Pattern[str] = re.compile(
    r"^import\s+([\w.,\s]+)"
)

# How many lines to scan for header comments.
_HEADER_SCAN_LINES: int = 25
# Maximum header tokens to return.
_MAX_HEADER_TOKENS: int = 30

# Comment prefixes per file extension (lowercase extension → tuple of prefixes).
_COMMENT_PREFIXES: dict[str, tuple[str, ...]] = {
    ".py": ("#", '"""', "'''"),
    ".js": ("//", "/*", " *"),
    ".ts": ("//", "/*", " *"),
    ".jsx": ("//", "/*", " *"),
    ".tsx": ("//", "/*", " *"),
    ".mjs": ("//", "/*", " *"),
    ".cjs": ("//", "/*", " *"),
    ".go": ("//", "/*", " *"),
    ".rs": ("///", "//", "/*", " *"),
    ".rb": ("#",),
    ".sh": ("#",),
    ".bash": ("#",),
    ".zsh": ("#",),
    ".fish": ("#",),
    ".c": ("//", "/*", " *"),
    ".cpp": ("//", "/*", " *"),
    ".cc": ("//", "/*", " *"),
    ".h": ("//", "/*", " *"),
    ".hpp": ("//", "/*", " *"),
    ".java": ("//", "/*", " *"),
    ".cs": ("//", "/*", " *"),
    ".php": ("//", "#", "/*", " *"),
    ".swift": ("//", "/*", " *"),
    ".kt": ("//", "/*", " *"),
    ".scala": ("//", "/*", " *"),
    ".r": ("#",),
    ".lua": ("--",),
    ".toml": ("#",),
    ".yaml": ("#",),
    ".yml": ("#",),
    ".dockerfile": ("#",),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dir_names_set(path: str) -> frozenset[str]:
    """Return lowercase directory component names from a forward-slash path."""
    if "/" not in path:
        return frozenset()
    dir_part = path.rsplit("/", 1)[0]
    return frozenset(seg.lower() for seg in dir_part.split("/"))


def _tokenize(text: str) -> list[str]:
    """Split *text* into lowercase, filtered, unique-preserving tokens."""
    raw = _SPLIT_RE.split(text)
    seen: set[str] = set()
    result: list[str] = []
    for part in raw:
        t = part.lower()
        if (
            len(t) >= _MIN_TOKEN_LEN
            and t not in _STOP_TOKENS
            and t.isascii()
            and t.isalpha()
            and t not in seen
        ):
            seen.add(t)
            result.append(t)
    return result


def _count_lines(abs_path: str) -> int | None:
    """Count newlines in *abs_path*. Returns None on read error."""
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Public: classification
# ---------------------------------------------------------------------------


def classify_file(record: FileRecord) -> str:
    """Return the ``file_type`` for *record*.

    Priority order (first match wins):
    1. noisy  → generated
    2. manifest
    3. config
    4. docs
    5. test
    6. entrypoint (depth-gated)
    7. source (known code extension)
    8. other
    """
    name_lower = record.path.rsplit("/", 1)[-1].lower()
    ext = ("." + name_lower.rsplit(".", 1)[-1]) if "." in name_lower else ""
    dir_names = _dir_names_set(record.path)

    # 1. Noisy → generated
    if record.is_noisy:
        return "generated"

    # 2. Manifest
    if name_lower in _MANIFEST_NAMES or ext in _MANIFEST_EXTENSIONS:
        return "manifest"

    # 3. Config: exact name
    if name_lower in _CONFIG_NAMES:
        return "config"

    # 3. Config: suffix pattern
    if any(p.search(name_lower) for p in _CONFIG_SUFFIX_RE):
        return "config"

    # 3. Config: YAML/JSON inside CI directories
    if ext in (".yml", ".yaml", ".json") and dir_names & _CI_DIR_NAMES:
        return "config"

    # 4. Docs: exact name
    if name_lower in _DOC_NAMES:
        return "docs"

    # 4. Docs: light markup extensions (markdown is almost always docs)
    if ext in _DOC_EXTENSIONS:
        return "docs"

    # 5. Test: directory-based
    if dir_names & _TEST_DIR_NAMES:
        return "test"

    # 5. Test: name pattern
    if any(p.search(name_lower) for p in _TEST_NAME_RE):
        return "test"

    # 6. Entrypoint: exact name, depth-gated
    if name_lower in _ENTRYPOINT_NAMES and record.depth <= _ENTRYPOINT_MAX_DEPTH:
        return "entrypoint"

    # 7. Source: known code extension
    if ext in _SOURCE_EXTENSIONS:
        return "source"

    # 8. Other
    return "other"


# ---------------------------------------------------------------------------
# Public: path token extraction
# ---------------------------------------------------------------------------


def extract_path_tokens(path: str) -> list[str]:
    """Return unique lowercase tokens from the directory components and filename stem.

    The file extension is stripped from the filename before tokenizing to
    reduce noise.  CamelCase and snake_case are split into individual words.
    """
    if "/" in path:
        dir_part, filename = path.rsplit("/", 1)
    else:
        dir_part, filename = "", path

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    text = dir_part.replace("/", " ") + " " + stem
    return _tokenize(text)


# ---------------------------------------------------------------------------
# Public: header token extraction
# ---------------------------------------------------------------------------


def extract_header_tokens(abs_path: str, extension: str) -> list[str]:
    """Return tokens from the leading comment / docstring lines of *abs_path*.

    Reads at most ``_HEADER_SCAN_LINES`` lines, extracts lines that start
    with a known comment prefix for *extension*, and tokenizes their text.
    Returns at most ``_MAX_HEADER_TOKENS`` unique tokens.
    Returns an empty list for unknown extensions or unreadable files.
    """
    prefixes = _COMMENT_PREFIXES.get(extension.lower(), ())
    if not prefixes:
        return []

    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            lines = [fh.readline() for _ in range(_HEADER_SCAN_LINES)]
    except OSError:
        return []

    comment_text: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        for prefix in prefixes:
            if stripped.startswith(prefix):
                comment_text.append(stripped[len(prefix):].strip())
                break

    if not comment_text:
        return []

    tokens = _tokenize(" ".join(comment_text))
    result: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
            if len(result) >= _MAX_HEADER_TOKENS:
                break
    return result


# ---------------------------------------------------------------------------
# Public: import token extraction
# ---------------------------------------------------------------------------


def extract_import_tokens(abs_path: str, extension: str) -> list[str]:
    """Return unique, filtered tokens extracted from Python import statements.

    Only ``.py`` files are processed; all other extensions return ``[]``.

    Handles single-line ``from X.Y.Z import a, b, c`` and ``import X.Y.Z``
    statements.  Parenthesised multi-line imports are partially handled: the
    module path on the opening line is captured, but continuation lines are
    not parsed (Iteration 2 scope).

    Tokenization pipeline:
    1. Concatenate module path segments and imported names into a single text.
    2. Run through ``_tokenize`` (applies ``_SPLIT_RE``, ``_STOP_TOKENS``,
       ``_MIN_TOKEN_LEN``).
    3. Filter out ``_IMPORT_STOP_TOKENS``.
    """
    if extension.lower() != ".py":
        return []

    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []

    import_texts: list[str] = []

    for line in lines:
        stripped = line.strip()

        m = _IMPORT_FROM_RE.match(stripped)
        if m:
            module_path = m.group(1).replace(".", " ")
            targets = (
                m.group(2)
                .replace(",", " ")
                .replace("(", " ")
                .replace(")", " ")
                .replace("\\", " ")
            )
            import_texts.append(module_path + " " + targets)
            continue

        m = _IMPORT_MODULE_RE.match(stripped)
        if m:
            modules = m.group(1).replace(".", " ").replace(",", " ")
            import_texts.append(modules)

    if not import_texts:
        return []

    raw_tokens = _tokenize(" ".join(import_texts))
    return [t for t in raw_tokens if t not in _IMPORT_STOP_TOKENS]


# ---------------------------------------------------------------------------
# Public: combined entry point
# ---------------------------------------------------------------------------


def classify_and_extract(record: FileRecord) -> ClassifiedFile:
    """Enrich *record* with classification, token, and line-count data.

    This is the primary function the refresh pipeline (T08) should call for
    each ``FileRecord`` yielded by ``walk_repo()``.
    """
    name = record.path.rsplit("/", 1)[-1]
    name_lower = name.lower()
    ext = ("." + name_lower.rsplit(".", 1)[-1]) if "." in name_lower else ""
    directory_path = record.path.rsplit("/", 1)[0] if "/" in record.path else ""

    file_type = classify_file(record)
    path_tokens = extract_path_tokens(record.path)
    header_tokens = extract_header_tokens(record.abs_path, ext)
    import_tokens = extract_import_tokens(record.abs_path, ext)
    line_count = None if record.is_noisy else _count_lines(record.abs_path)

    return ClassifiedFile(
        **vars(record),
        file_type=file_type,
        extension=ext or None,
        line_count=line_count,
        directory_path=directory_path,
        path_tokens=path_tokens,
        header_tokens=header_tokens,
        import_tokens=import_tokens,
    )
