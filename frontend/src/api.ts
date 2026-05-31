import type {
  Capabilities,
  FolderListing,
  ProjectBundle,
  ProjectApplyResponse,
  ProjectChatResponse,
  ImageAttachmentPayload,
  ProjectRecord
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init
  });
  const payload = (await response.json()) as unknown;
  if (!response.ok) {
    const error =
      typeof payload === "object" && payload !== null && "error" in payload
        ? String((payload as { error?: unknown }).error || "")
        : "Request failed";
    throw new Error(error || "Request failed");
  }
  return payload as T;
}

export function loadCapabilities(): Promise<Capabilities> {
  return request<Capabilities>("/api/capabilities");
}

export async function loadProjects(): Promise<ProjectRecord[]> {
  const payload = await request<{ projects: ProjectRecord[] }>("/api/projects");
  return payload.projects;
}

export function openProject(path: string): Promise<ProjectBundle> {
  return request<ProjectBundle>("/api/projects/open", {
    method: "POST",
    body: JSON.stringify({ path })
  });
}

export function loadFolder(path: string): Promise<FolderListing> {
  const suffix = path ? `?path=${encodeURIComponent(path)}` : "";
  return request<FolderListing>(`/api/fs/list${suffix}`);
}

export function sendProjectMessage(args: {
  projectPath: string;
  message: string;
  maxIterations: number;
  useRag: boolean;
  codeBackend?: string;
  image?: ImageAttachmentPayload;
}): Promise<ProjectChatResponse> {
  return request<ProjectChatResponse>("/api/project-chat", {
    method: "POST",
    body: JSON.stringify(args)
  });
}

export function applyProjectChanges(args: {
  projectPath: string;
  applyToken: string;
}): Promise<ProjectApplyResponse> {
  return request<ProjectApplyResponse>("/api/project-apply", {
    method: "POST",
    body: JSON.stringify(args)
  });
}
