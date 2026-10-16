import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useSkills(opts?: { source?: string; agent?: string }) {
  return useQuery({
    queryKey: ['skills', opts],
    queryFn: () => api.getSkills(opts),
    staleTime: 2 * 60 * 1000,
  })
}

export function useSkillAgents() {
  return useQuery({
    queryKey: ['skillAgents'],
    queryFn: () => api.getSkillAgents(),
    staleTime: 5 * 60 * 1000,
  })
}

export function useCreateSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; description: string; body: string; agents?: string[] }) =>
      api.createSkill(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
    },
  })
}

export function useUpdateSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, ...body }: { name: string; description?: string; body?: string }) =>
      api.updateSkill(name, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
    },
  })
}

export function useDeleteSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.deleteSkill(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
    },
  })
}

export function usePublishSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, agents }: { name: string; agents?: string[] }) =>
      api.publishSkill(name, agents),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
    },
  })
}

export function useUnpublishSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, agents }: { name: string; agents?: string[] }) =>
      api.unpublishSkill(name, agents),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
    },
  })
}

export function useImportSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sourcePath: string) => api.importSkill(sourcePath),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
    },
  })
}
