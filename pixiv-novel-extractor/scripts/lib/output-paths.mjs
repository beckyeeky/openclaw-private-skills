import { tmpdir } from 'node:os'
import { dirname, isAbsolute, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptFile = fileURLToPath(import.meta.url)
const skillRoot = resolve(dirname(scriptFile), '..', '..')

function isInsidePath(parentPath, candidatePath) {
  const rel = relative(parentPath, candidatePath)
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel))
}

export function getManagedOutputBaseDir({
  cwd = process.cwd(),
  env = process.env,
  tempRoot = tmpdir(),
  skillRootPath = skillRoot,
} = {}) {
  const explicitRoot = typeof env.PIXIV_NOVEL_OUTPUT_DIR === 'string' ? env.PIXIV_NOVEL_OUTPUT_DIR.trim() : ''
  if (explicitRoot) return resolve(explicitRoot)

  const resolvedCwd = resolve(cwd)
  const resolvedSkillRoot = resolve(skillRootPath)

  if (!isInsidePath(resolvedSkillRoot, resolvedCwd)) {
    return resolvedCwd
  }

  return resolve(tempRoot)
}

export function resolveManagedOutputDir(outputDir, options = {}) {
  if (!outputDir) {
    throw new Error('Missing output directory')
  }

  if (isAbsolute(outputDir)) {
    return resolve(outputDir)
  }

  return resolve(getManagedOutputBaseDir(options), outputDir)
}
