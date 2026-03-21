import { promises as fs } from 'node:fs';
import path from 'node:path';
import { execFile as execFileCallback } from 'node:child_process';
import { promisify } from 'node:util';

const execFile = promisify(execFileCallback);
const CACHE_DIR = '.repomind';
const CACHE_FILE = 'index.json';
const MAX_FILE_BYTES = 32_000;
const MAX_FILE_COUNT = 400;
const MAX_DIRECTORY_COUNT = 80;
const MAX_RECENT_COMMITS = 25;

const SKIP_DIRS = new Set([
  '.git',
  'node_modules',
  'dist',
  'build',
  'coverage',
  '.next',
  '.turbo',
  '.cache',
  '.idea',
  '.vscode'
]);

const IMPORTANT_FILENAMES = [
  'README.md',
  'package.json',
  'tsconfig.json',
  'Cargo.toml',
  'go.mod',
  'requirements.txt',
  'pyproject.toml',
  'docker-compose.yml',
  'Dockerfile',
  'Makefile',
  'vite.config.ts',
  'next.config.js',
  'next.config.mjs',
  'app.ts',
  'main.ts',
  'main.py',
  'server.ts',
  'server.js',
  'index.ts',
  'index.js'
];

export type RepoIndex = {
  repoRoot: string;
  repoName: string;
  generatedAt: string;
  summary: string;
  languages: string[];
  stats: {
    totalFiles: number;
    totalDirectories: number;
  };
  git: {
    branch: string | null;
    isDirty: boolean;
  };
  directories: Array<{
    path: string;
    fileCount: number;
    sampleFiles: string[];
    reason: string;
  }>;
  files: Array<{
    path: string;
    score: number;
    summary: string;
    topTokens: string[];
  }>;
  criticalFiles: Array<{
    path: string;
    score: number;
    reason: string;
  }>;
  recentChanges: Array<{
    sha: string;
    author: string;
    date: string;
    subject: string;
  }>;
};

async function exists(filePath: string) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function runGit(repoRoot: string, args: string[]) {
  const { stdout } = await execFile('git', ['-C', repoRoot, ...args], {
    maxBuffer: 1024 * 1024 * 8
  });
  return stdout.trim();
}

export async function detectRepoRoot(repoPath?: string) {
  const cwd = repoPath ? path.resolve(repoPath) : process.cwd();
  try {
    const root = await runGit(cwd, ['rev-parse', '--show-toplevel']);
    return root || cwd;
  } catch {
    return cwd;
  }
}

async function readCachedIndex(repoRoot: string) {
  const cachePath = path.join(repoRoot, CACHE_DIR, CACHE_FILE);
  if (!(await exists(cachePath))) return null;
  try {
    const raw = await fs.readFile(cachePath, 'utf8');
    return JSON.parse(raw) as RepoIndex;
  } catch {
    return null;
  }
}

async function writeCachedIndex(repoRoot: string, index: RepoIndex) {
  const cacheDir = path.join(repoRoot, CACHE_DIR);
  await fs.mkdir(cacheDir, { recursive: true });
  await fs.writeFile(path.join(cacheDir, CACHE_FILE), JSON.stringify(index, null, 2) + '\n', 'utf8');
}

function inferLanguageFromExtension(filePath: string) {
  const ext = path.extname(filePath).toLowerCase();
  switch (ext) {
    case '.ts':
    case '.tsx':
      return 'TypeScript';
    case '.js':
    case '.jsx':
    case '.mjs':
    case '.cjs':
      return 'JavaScript';
    case '.py':
      return 'Python';
    case '.go':
      return 'Go';
    case '.rs':
      return 'Rust';
    case '.java':
      return 'Java';
    case '.rb':
      return 'Ruby';
    case '.php':
      return 'PHP';
    case '.md':
      return 'Markdown';
    case '.json':
    case '.yaml':
    case '.yml':
    case '.toml':
      return 'Config';
    default:
      return null;
  }
}

function tokenize(content: string) {
  const words = content.toLowerCase().match(/[a-z_][a-z0-9_\-]{2,}/g) ?? [];
  const counts = new Map<string, number>();

  for (const word of words) {
    if (['const', 'function', 'return', 'import', 'from', 'export', 'class', 'true', 'false'].includes(word)) {
      continue;
    }
    counts.set(word, (counts.get(word) ?? 0) + 1);
  }

  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([word]) => word);
}

function summarizeFile(relPath: string, content: string, tokens: string[]) {
  const firstCodeLine = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith('//') && !line.startsWith('#') && !line.startsWith('*'));

  if (relPath.toLowerCase() === 'readme.md') {
    return 'Project overview and setup instructions.';
  }

  if (relPath.endsWith('package.json')) {
    return 'Node package manifest with scripts and dependencies.';
  }

  if (!firstCodeLine) {
    return tokens.length ? `Contains: ${tokens.slice(0, 6).join(', ')}` : 'Small or mostly empty file.';
  }

  return firstCodeLine.slice(0, 160);
}

function directoryReason(relDir: string, sampleFiles: string[]) {
  if (relDir === '.') return 'Repository root and top-level project shape';
  const lower = relDir.toLowerCase();
  if (lower.includes('src')) return 'Primary source code';
  if (lower.includes('test')) return 'Tests, fixtures, or validation code';
  if (lower.includes('doc')) return 'Documentation and design notes';
  if (lower.includes('script')) return 'Automation scripts and developer utilities';
  if (lower.includes('config')) return 'Configuration and environment setup';
  if (lower.includes('example')) return 'Examples or sample usage';
  if (sampleFiles.length) return `Contains files like ${sampleFiles.join(', ')}`;
  return 'Repository subdirectory';
}

async function walk(repoRoot: string) {
  const files: string[] = [];
  const directories = new Map<string, string[]>();

  async function visit(current: string) {
    const entries = await fs.readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      if (SKIP_DIRS.has(entry.name)) continue;
      const fullPath = path.join(current, entry.name);
      const relPath = path.relative(repoRoot, fullPath) || '.';

      if (entry.isDirectory()) {
        await visit(fullPath);
        continue;
      }

      if (!entry.isFile()) continue;
      files.push(relPath);

      const dir = path.dirname(relPath) === '' ? '.' : path.dirname(relPath);
      const sample = directories.get(dir) ?? [];
      if (sample.length < 5) sample.push(path.basename(relPath));
      directories.set(dir, sample);

      if (files.length >= MAX_FILE_COUNT) return;
    }
  }

  await visit(repoRoot);
  return { files, directories };
}

async function getGitInfo(repoRoot: string) {
  try {
    const [branch, status, log] = await Promise.all([
      runGit(repoRoot, ['branch', '--show-current']).catch(() => ''),
      runGit(repoRoot, ['status', '--short']).catch(() => ''),
      runGit(repoRoot, ['log', `--max-count=${MAX_RECENT_COMMITS}`, '--date=short', '--pretty=format:%H%x09%an%x09%ad%x09%s']).catch(() => '')
    ]);

    const recentChanges = log
      ? log.split(/\r?\n/).filter(Boolean).map((line: string) => {
          const [sha, author, date, subject] = line.split('\t');
          return { sha, author, date, subject };
        })
      : [];

    return {
      branch: branch || null,
      isDirty: Boolean(status),
      recentChanges
    };
  } catch {
    return {
      branch: null,
      isDirty: false,
      recentChanges: []
    };
  }
}

export async function buildIndex({ repoPath, refresh }: { repoPath?: string; refresh?: boolean }) {
  const repoRoot = await detectRepoRoot(repoPath);
  if (!refresh) {
    const cached = await readCachedIndex(repoRoot);
    if (cached) return cached;
  }

  const { files, directories } = await walk(repoRoot);
  const languageCounts = new Map<string, number>();
  const fileEntries: RepoIndex['files'] = [];
  const criticalFiles: RepoIndex['criticalFiles'] = [];

  for (const relPath of files) {
    const fullPath = path.join(repoRoot, relPath);
    const stat = await fs.stat(fullPath);
    if (stat.size > MAX_FILE_BYTES) continue;

    const content = await fs.readFile(fullPath, 'utf8').catch(() => '');
    const tokens = tokenize(content);
    const summary = summarizeFile(relPath, content, tokens);
    const language = inferLanguageFromExtension(relPath);
    if (language) languageCounts.set(language, (languageCounts.get(language) ?? 0) + 1);

    let score = tokens.length + Math.min(20, Math.ceil(content.length / 300));
    const base = path.basename(relPath);
    if (IMPORTANT_FILENAMES.includes(base)) score += 25;
    if (relPath.startsWith('src/')) score += 8;
    if (relPath.startsWith('docs/')) score += 3;
    if (relPath.includes('test')) score -= 5;

    fileEntries.push({
      path: relPath,
      score,
      summary,
      topTokens: tokens
    });

    if (IMPORTANT_FILENAMES.includes(base) || score >= 28) {
      criticalFiles.push({
        path: relPath,
        score,
        reason: IMPORTANT_FILENAMES.includes(base)
          ? `High-signal project file (${base})`
          : `Dense file with useful identifiers: ${tokens.slice(0, 5).join(', ') || 'general project logic'}`
      });
    }
  }

  const git = await getGitInfo(repoRoot);
  const sortedLanguages = [...languageCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([language]) => language);

  const directoryEntries = [...directories.entries()]
    .map(([dirPath, sampleFiles]) => ({
      path: dirPath,
      fileCount: files.filter((file) => (path.dirname(file) === '' ? '.' : path.dirname(file)) === dirPath).length,
      sampleFiles,
      reason: directoryReason(dirPath, sampleFiles)
    }))
    .sort((a, b) => b.fileCount - a.fileCount)
    .slice(0, MAX_DIRECTORY_COUNT);

  const repoName = path.basename(repoRoot);
  const summaryBits = [
    `Repomind indexed ${fileEntries.length} readable files`,
    sortedLanguages.length ? `mostly ${sortedLanguages.join(', ')}` : 'with unknown primary languages',
    directoryEntries.length ? `across directories like ${directoryEntries.slice(0, 4).map((dir) => dir.path).join(', ')}` : 'with a shallow repository structure'
  ];

  const index: RepoIndex = {
    repoRoot,
    repoName,
    generatedAt: new Date().toISOString(),
    summary: `${summaryBits[0]}, ${summaryBits[1]}, ${summaryBits[2]}.`,
    languages: sortedLanguages,
    stats: {
      totalFiles: fileEntries.length,
      totalDirectories: directoryEntries.length
    },
    git: {
      branch: git.branch,
      isDirty: git.isDirty
    },
    directories: directoryEntries,
    files: fileEntries.sort((a, b) => b.score - a.score),
    criticalFiles: criticalFiles.sort((a, b) => b.score - a.score).slice(0, 25),
    recentChanges: git.recentChanges
  };

  await writeCachedIndex(repoRoot, index);
  return index;
}
