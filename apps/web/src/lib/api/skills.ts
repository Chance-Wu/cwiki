import { request } from './base'
import type { Skill } from './types'

export const getSkills = (opts?: { source?: string; agent?: string }) => {
  const params = new URLSearchParams()
  if (opts?.source) params.set('source', opts.source)
  if (opts?.agent) params.set('agent', opts.agent)
  const qs = params.toString()
  return request<Skill[]>(`/skills${qs ? `?${qs}` : ''}`)
}

export const getSkillAgents = () => request<string[]>('/skills/agents')

export const getSkillDetail = (name: string) => request<Skill>(`/skills/${name}`)

export const createSkill = (body: {
  name: string
  description: string
  body: string
  agents?: string[]
}) => request<Skill>('/skills', { method: 'POST', body: JSON.stringify(body) })

export const updateSkill = (name: string, body: { description?: string; body?: string }) =>
  request<Skill>(`/skills/${name}`, { method: 'PATCH', body: JSON.stringify(body) })

export const deleteSkill = (name: string) => request<void>(`/skills/${name}`, { method: 'DELETE' })

export const publishSkill = (name: string, agents?: string[]) =>
  request<Skill>(`/skills/${name}/publish`, {
    method: 'POST',
    body: JSON.stringify(agents ? { agents } : {}),
  })

export const unpublishSkill = (name: string, agents?: string[]) =>
  request<Skill>(`/skills/${name}/unpublish`, {
    method: 'POST',
    body: JSON.stringify(agents ? { agents } : {}),
  })

export const importSkill = (sourcePath: string) =>
  request<Skill>('/skills/import', {
    method: 'POST',
    body: JSON.stringify({ source_path: sourcePath }),
  })
