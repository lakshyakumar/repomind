#!/usr/bin/env node
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import * as z from 'zod/v4';
import { buildIndex, detectRepoRoot, type RepoIndex } from './repo-index.js';

const server = new McpServer({
  name: 'repomind',
  version: '0.1.0'
});

function textResponse(text: string) {
  return {
    content: [{ type: 'text' as const, text }]
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function formatDirectoryMap(index: RepoIndex, limit: number) {
  const dirs = index.directories.slice(0, limit);
  return dirs
    .map((dir) => {
      const rel = dir.path === '.' ? './' : `${dir.path}/`;
      const examples = dir.sampleFiles.length ? `, samples: ${dir.sampleFiles.join(', ')}` : '';
      return `- ${rel} :: ${dir.reason} (${dir.fileCount} files${examples})`;
    })
    .join('\n');
}

function formatCriticalFiles(index: RepoIndex, limit: number) {
  return index.criticalFiles
    .slice(0, limit)
    .map((file, i) => `${i + 1}. ${file.path} [score=${file.score}]\n   ${file.reason}`)
    .join('\n');
}

function formatRecentChanges(index: RepoIndex, limit: number) {
  return index.recentChanges
    .slice(0, limit)
    .map((change) => `- ${change.sha.slice(0, 7)} ${change.subject} (${change.author}, ${change.date})`)
    .join('\n');
}

server.registerTool(
  'repo.get_overview',
  {
    description: 'Return a compact overview of the repository structure, technologies, and important files.',
    inputSchema: {
      repoPath: z.string().optional().describe('Optional path inside the target repository. Defaults to current working directory.'),
      refresh: z.boolean().optional().describe('Force a fresh rebuild instead of using the cached index.')
    }
  },
  async ({ repoPath, refresh }) => {
    const index = await buildIndex({ repoPath, refresh });
    const lines = [
      `Repository: ${index.repoName}`,
      `Root: ${index.repoRoot}`,
      `Primary languages: ${index.languages.length ? index.languages.join(', ') : 'unknown'}`,
      `Files indexed: ${index.stats.totalFiles}`,
      `Directories indexed: ${index.stats.totalDirectories}`,
      `Git branch: ${index.git.branch ?? 'unknown'}`,
      `Working tree: ${index.git.isDirty ? 'dirty' : 'clean'}`,
      '',
      `Summary: ${index.summary}`,
      '',
      'Top directories:',
      formatDirectoryMap(index, 8),
      '',
      'Critical files:',
      formatCriticalFiles(index, 8)
    ];

    if (index.recentChanges.length) {
      lines.push('', 'Recent changes:', formatRecentChanges(index, 5));
    }

    return textResponse(lines.join('\n'));
  }
);

server.registerTool(
  'repo.get_directory_map',
  {
    description: 'List important directories and explain what they likely contain.',
    inputSchema: {
      repoPath: z.string().optional(),
      limit: z.number().int().min(1).max(50).optional(),
      refresh: z.boolean().optional()
    }
  },
  async ({ repoPath, limit = 15, refresh }) => {
    const index = await buildIndex({ repoPath, refresh });
    const clamped = clamp(limit, 1, 50);
    return textResponse(formatDirectoryMap(index, clamped));
  }
);

server.registerTool(
  'repo.get_critical_files',
  {
    description: 'Return the files most likely to matter for understanding or changing the repository.',
    inputSchema: {
      repoPath: z.string().optional(),
      limit: z.number().int().min(1).max(50).optional(),
      refresh: z.boolean().optional()
    }
  },
  async ({ repoPath, limit = 12, refresh }) => {
    const index = await buildIndex({ repoPath, refresh });
    return textResponse(formatCriticalFiles(index, clamp(limit, 1, 50)));
  }
);

server.registerTool(
  'repo.get_recent_changes',
  {
    description: 'Return recent git commits so the agent can understand what changed without re-reading the entire repo.',
    inputSchema: {
      repoPath: z.string().optional(),
      limit: z.number().int().min(1).max(30).optional(),
      refresh: z.boolean().optional()
    }
  },
  async ({ repoPath, limit = 10, refresh }) => {
    const index = await buildIndex({ repoPath, refresh });
    if (!index.recentChanges.length) {
      return textResponse('No recent git history found.');
    }
    return textResponse(formatRecentChanges(index, clamp(limit, 1, 30)));
  }
);

server.registerTool(
  'repo.find_edit_points',
  {
    description: 'Suggest likely files and directories to inspect for a task, based on simple keyword matching against the indexed repository.',
    inputSchema: {
      query: z.string().min(2).describe('Task, bug, or feature description.'),
      repoPath: z.string().optional(),
      limit: z.number().int().min(1).max(20).optional(),
      refresh: z.boolean().optional()
    }
  },
  async ({ query, repoPath, limit = 8, refresh }) => {
    const index = await buildIndex({ repoPath, refresh });
    const tokens = query
      .toLowerCase()
      .split(/[^a-z0-9_\-]+/)
      .filter((token) => token.length > 1);

    const candidates = index.files
      .map((file) => {
        const haystack = `${file.path} ${file.summary} ${file.topTokens.join(' ')}`.toLowerCase();
        const score = tokens.reduce((acc, token) => acc + (haystack.includes(token) ? 1 : 0), 0) + file.score / 100;
        return { file, score };
      })
      .filter((entry) => entry.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, clamp(limit, 1, 20));

    if (!candidates.length) {
      return textResponse(`No obvious edit points found for: ${query}`);
    }

    const text = candidates
      .map((entry, indexPosition) => `${indexPosition + 1}. ${entry.file.path}\n   ${entry.file.summary}`)
      .join('\n');

    return textResponse(text);
  }
);

server.registerTool(
  'repo.refresh_index',
  {
    description: 'Force a rebuild of the repository index and return a short status summary.',
    inputSchema: {
      repoPath: z.string().optional()
    }
  },
  async ({ repoPath }) => {
    const repoRoot = await detectRepoRoot(repoPath);
    const index = await buildIndex({ repoPath: repoRoot, refresh: true });
    return textResponse(`Index refreshed for ${index.repoName}. Indexed ${index.stats.totalFiles} files across ${index.stats.totalDirectories} directories.`);
  }
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error) => {
  console.error('[repomind] fatal:', error);
  process.exit(1);
});
