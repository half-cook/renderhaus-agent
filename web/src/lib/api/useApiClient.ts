"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo } from "react";
import * as api from "./client";

// Binds every client.ts function to the current session's getToken, once
// per component -- mirrors useTimelineStore's narrow-selector convention
// (components read what they need directly) while centralizing auth-header
// attachment in one place instead of threading getToken through every call
// site. Every generation/project/production action originates from a
// component event handler, so there's no need for an imperative
// getState()-style accessor here the way lib/timeline/import.ts needs one
// for the timeline store.
export function useApiClient() {
  const { getToken } = useAuth();

  return useMemo(
    () => ({
      getConfig: () => api.getConfig(getToken),
      getMe: () => api.getMe(getToken),
      uploadReferenceAsset: (file: File) => api.uploadReferenceAsset(file, getToken),

      createGeneration: (body: Parameters<typeof api.createGeneration>[0]) =>
        api.createGeneration(body, getToken),
      listGenerations: (params: Parameters<typeof api.listGenerations>[0]) =>
        api.listGenerations(params, getToken),
      getGeneration: (jobId: string) => api.getGeneration(jobId, getToken),
      refineGeneration: (jobId: string, body: Parameters<typeof api.refineGeneration>[1]) =>
        api.refineGeneration(jobId, body, getToken),

      createProject: (body: Parameters<typeof api.createProject>[0]) =>
        api.createProject(body, getToken),
      listProjects: () => api.listProjects(getToken),
      getProject: (projectId: string) => api.getProject(projectId, getToken),
      updateProject: (projectId: string, body: Parameters<typeof api.updateProject>[1]) =>
        api.updateProject(projectId, body, getToken),
      deleteProject: (projectId: string) => api.deleteProject(projectId, getToken),
      addProjectArtifact: (projectId: string, jobId: string) =>
        api.addProjectArtifact(projectId, jobId, getToken),
      removeProjectArtifact: (projectId: string, jobId: string) =>
        api.removeProjectArtifact(projectId, jobId, getToken),
      putProjectTimeline: (projectId: string, items: Parameters<typeof api.putProjectTimeline>[1]) =>
        api.putProjectTimeline(projectId, items, getToken),
      mergeProject: (projectId: string) => api.mergeProject(projectId, getToken),

      createProduction: (body: Parameters<typeof api.createProduction>[0]) =>
        api.createProduction(body, getToken),
      listProductions: () => api.listProductions(getToken),
      getProduction: (productionId: string) => api.getProduction(productionId, getToken),
      deleteProduction: (productionId: string) => api.deleteProduction(productionId, getToken),
      planProduction: (productionId: string) => api.planProduction(productionId, getToken),
      approveProductionPlan: (
        productionId: string,
        body: Parameters<typeof api.approveProductionPlan>[1],
      ) => api.approveProductionPlan(productionId, body, getToken),
    }),
    [getToken],
  );
}
