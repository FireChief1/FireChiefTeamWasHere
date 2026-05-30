export type ProjectRecord = {
  id: number;
  name: string;
  path: string;
  updatedAt: string;
  lastOpenedAt: string;
  brief: string;
  stack: string[];
  entrypoints: string[];
  testCommands: string[];
  risks: string[];
  gitStatus: string;
  lastTask: string;
  lastStatus: string;
};

export type ProjectTimelineEvent = {
  id: number;
  createdAt: string;
  kind: string;
  title: string;
  body: string;
  role: string;
  metadata: Record<string, unknown>;
};

export type ProjectCheckpoint = {
  id: number;
  createdAt: string;
  taskId: string;
  task: string;
  status: string;
  taskProfile: string;
  summary: string;
  plannedFiles: string[];
  writtenFiles: string[];
  previewOnly: boolean;
  diff: string;
  testsPassed: number;
  testsFailed: number;
};

export type RouteDecision = {
  intent: string;
  action?: string;
  actionTarget?: string;
  readOnly?: boolean;
  requiresWorkflow?: boolean;
  safetyStatus?: string;
  safetyMessage?: string;
  responseSource?: string;
  shouldRunWorkflow: boolean;
  confidence: number;
  reason: string;
  routedBy: string;
  label: string;
};

export type ImageAttachmentPayload = {
  name: string;
  mimeType: string;
  data: string;
};

export type ProjectRun = {
  taskId: string;
  status: string;
  taskProfile: string;
  ragStatus: string;
  ragSources: string[];
  projectSummary: string;
  plannedFiles: string[];
  writtenFiles: string[];
  previewOnly: boolean;
  diff: string;
  pendingApply?: PendingProjectApply | null;
  nodeError: string | null;
  devRepairAttempted: boolean;
  devValidationError: string | null;
  rejectedCode: Record<string, string>;
  tests: {
    passed: number;
    failed: number;
    total: number;
    output: string;
  };
};

export type PendingProjectApply = {
  token: string;
  taskId: string;
  targetPath: string;
  mcpRoot: string;
  plannedFiles: string[];
  fileActions: Array<{ file: string; action: string }>;
  diff: string;
};

export type ProjectApplyResponse = ProjectBundle & {
  apply: {
    targetPath: string;
    mcpRoot: string;
    writtenFiles: string[];
  };
};

export type ProjectBundle = {
  project: ProjectRecord;
  timeline: ProjectTimelineEvent[];
  checkpoints: ProjectCheckpoint[];
  memory?: string;
};

export type ProjectChatResponse = ProjectBundle & {
  ranWorkflow: boolean;
  assistantResponse: string;
  route: RouteDecision;
  run?: ProjectRun;
};

export type FolderEntry = {
  name: string;
  path: string;
};

export type FolderListing = {
  current: string;
  parent: string;
  folders: FolderEntry[];
};
