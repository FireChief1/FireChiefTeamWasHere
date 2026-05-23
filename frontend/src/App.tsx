import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  loadFolder,
  loadProjects,
  openProject,
  sendProjectMessage
} from "./api";
import type {
  FolderListing,
  ProjectBundle,
  ProjectCheckpoint,
  ProjectRecord,
  ProjectRun,
  ProjectTimelineEvent,
  RouteDecision
} from "./types";

const DEFAULT_PATH = "/Users/erkutates/Desktop/FinalProject";

type Notice = {
  tone: "info" | "error" | "success";
  text: string;
};

function App() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [bundle, setBundle] = useState<ProjectBundle | null>(null);
  const [folder, setFolder] = useState<FolderListing | null>(null);
  const [selectedPath, setSelectedPath] = useState(DEFAULT_PATH);
  const [message, setMessage] = useState("");
  const [maxIterations, setMaxIterations] = useState(3);
  const [useRag, setUseRag] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [route, setRoute] = useState<RouteDecision | null>(null);
  const [run, setRun] = useState<ProjectRun | null>(null);

  useEffect(() => {
    void refreshProjects();
    void refreshFolder(DEFAULT_PATH);
  }, []);

  const chatEvents = useMemo(
    () =>
      (bundle?.timeline || []).filter(
        (event) => event.kind === "user_message" || event.kind === "assistant_message"
      ),
    [bundle]
  );
  const displayRoute = useMemo(
    () => route || routeFromTimeline(bundle?.timeline || []),
    [bundle?.timeline, route]
  );

  async function refreshProjects() {
    try {
      setProjects(await loadProjects());
    } catch (error) {
      setNotice({ tone: "error", text: formatError(error) });
    }
  }

  async function refreshFolder(path: string) {
    try {
      const nextFolder = await loadFolder(path);
      setFolder(nextFolder);
      setSelectedPath(nextFolder.current);
    } catch (error) {
      setNotice({ tone: "error", text: formatError(error) });
    }
  }

  async function handleOpenProject(path = selectedPath) {
    try {
      const nextBundle = await openProject(path);
      setBundle(nextBundle);
      setSelectedPath(nextBundle.project.path);
      setRoute(null);
      setRun(null);
      setNotice({ tone: "success", text: "Proje açıldı." });
      await refreshProjects();
    } catch (error) {
      setNotice({ tone: "error", text: formatError(error) });
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanMessage = message.trim();
    if (!cleanMessage || !bundle) {
      return;
    }
    setIsSending(true);
    setNotice({ tone: "info", text: "Mesaj işleniyor." });
    setRoute(null);
    setRun(null);
    try {
      const response = await sendProjectMessage({
        projectPath: bundle.project.path,
        message: cleanMessage,
        maxIterations,
        useRag
      });
      setBundle({
        project: response.project,
        timeline: response.timeline,
        checkpoints: response.checkpoints
      });
      setRoute(response.route);
      setRun(response.run || null);
      setMessage("");
      setNotice({
        tone: response.ranWorkflow ? "success" : "info",
        text: response.ranWorkflow
          ? "Teknik ajan akışı tamamlandı."
          : "Sohbet olarak yanıtlandı."
      });
      await refreshProjects();
    } catch (error) {
      setNotice({ tone: "error", text: formatError(error) });
    } finally {
      setIsSending(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <header className="brand">
          <span className="brand-mark">CT</span>
          <div>
            <h1>Code Team</h1>
            <p>React Project Workspace</p>
          </div>
        </header>

        <section className="panel">
          <div className="panel-heading">
            <h2>Projeler</h2>
            <button className="icon-button" onClick={() => void refreshProjects()}>
              Yenile
            </button>
          </div>
          <div className="project-list">
            {projects.length === 0 ? (
              <p className="muted">Kayıtlı proje yok.</p>
            ) : (
              projects.map((project) => (
                <button
                  className={
                    bundle?.project.path === project.path
                      ? "project-row selected"
                      : "project-row"
                  }
                  key={project.id}
                  onClick={() => void handleOpenProject(project.path)}
                >
                  <span>{project.name}</span>
                  <small>{project.lastStatus || "NEW"}</small>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="panel">
          <h2>Proje Klasörü</h2>
          <input
            value={selectedPath}
            onChange={(event) => setSelectedPath(event.target.value)}
            spellCheck={false}
          />
          <div className="button-row">
            <button onClick={() => void refreshFolder(selectedPath)}>Gez</button>
            <button className="primary" onClick={() => void handleOpenProject()}>
              Aç
            </button>
          </div>
          {folder && (
            <div className="folder-browser">
              <div className="folder-current">{folder.current}</div>
              {folder.parent && (
                <button onClick={() => void refreshFolder(folder.parent)}>Üst klasör</button>
              )}
              <div className="folder-list">
                {folder.folders.slice(0, 80).map((entry) => (
                  <button key={entry.path} onClick={() => void refreshFolder(entry.path)}>
                    {entry.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="panel">
          <h2>Ayarlar</h2>
          <label className="field-label">
            Maksimum iterasyon
            <input
              type="number"
              min={1}
              max={5}
              value={maxIterations}
              onChange={(event) => setMaxIterations(Number(event.target.value))}
            />
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={useRag}
              onChange={(event) => setUseRag(event.target.checked)}
            />
            <span>RAG bilgi tabanı</span>
          </label>
        </section>
      </aside>

      <section className="workspace">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">Project Mode</p>
            <h2>{bundle?.project.name || "Proje seç"}</h2>
            <p>{bundle?.project.path || "Sol taraftan bir klasör aç."}</p>
          </div>
          <StatusBadge status={bundle?.project.lastStatus || "READY"} />
        </header>

        {notice && <NoticeBar notice={notice} />}

        <section className="content-grid">
          <div className="chat-column">
            <ProjectSummary project={bundle?.project || null} />
            <ChatTimeline events={chatEvents} />
            <form className="composer" onSubmit={handleSend}>
              <textarea
                value={message}
                disabled={!bundle || isSending}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Projeye mesaj yaz..."
              />
              <button className="primary" disabled={!bundle || isSending}>
                {isSending ? "Çalışıyor" : "Gönder"}
              </button>
            </form>
          </div>

          <aside className="detail-column">
            <RoutePanel route={displayRoute} />
            <CheckpointPanel checkpoints={bundle?.checkpoints || []} />
            <RunPanel run={run} />
          </aside>
        </section>
      </section>
    </main>
  );
}

function ProjectSummary({ project }: { project: ProjectRecord | null }) {
  if (!project) {
    return (
      <section className="summary-strip">
        <span>Proje seçilmedi</span>
        <p>React UI, lokal API ve Postgres registry ile çalışır.</p>
      </section>
    );
  }

  return (
    <section className="summary-strip">
      <span>{project.stack.length ? project.stack.join(", ") : "Stack belirsiz"}</span>
      <p>{project.brief || project.lastTask || "Bu proje için henüz brief yok."}</p>
      {project.risks.length > 0 && <strong>{project.risks[0]}</strong>}
    </section>
  );
}

function ChatTimeline({ events }: { events: ProjectTimelineEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="empty-chat">
        <h3>Henüz sohbet yok</h3>
        <p>Mesaj sohbet ise direkt yanıtlanır; analiz veya kod görevi ise ajan akışı başlar.</p>
      </div>
    );
  }

  return (
    <div className="chat-timeline">
      {events.map((event) => (
        <article
          className={event.role === "user" ? "message user" : "message assistant"}
          key={event.id}
        >
          <p>{event.body}</p>
          <time>{formatTime(event.createdAt)}</time>
        </article>
      ))}
    </div>
  );
}

function RoutePanel({ route }: { route: RouteDecision | null }) {
  return (
    <section className="panel detail-panel">
      <h2>Router</h2>
      {!route ? (
        <p className="muted">Henüz karar yok.</p>
      ) : (
        <>
          <div className="metric">
            <span>Intent</span>
            <strong>{route.intent}</strong>
          </div>
          {route.action && (
            <div className="metric">
              <span>Action</span>
              <strong>{route.action}</strong>
            </div>
          )}
          <div className="metric">
            <span>Confidence</span>
            <strong>{route.confidence.toFixed(2)}</strong>
          </div>
          {route.actionTarget && (
            <p>
              Hedef: <code>{route.actionTarget}</code>
            </p>
          )}
          {route.safetyStatus === "blocked" && (
            <p className="danger-text">{route.safetyMessage || "Action blocked."}</p>
          )}
          <p>{route.reason || route.label}</p>
        </>
      )}
    </section>
  );
}

function CheckpointPanel({ checkpoints }: { checkpoints: ProjectCheckpoint[] }) {
  return (
    <section className="panel detail-panel">
      <h2>Checkpoint</h2>
      {checkpoints.length === 0 ? (
        <p className="muted">Bu proje için checkpoint yok.</p>
      ) : (
        <div className="checkpoint-list">
          {checkpoints.slice(0, 5).map((checkpoint) => (
            <article key={checkpoint.id}>
              <div>
                <strong>{checkpoint.status}</strong>
                <span>{checkpoint.taskProfile || "profile yok"}</span>
              </div>
              <p>{checkpoint.task}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function RunPanel({ run }: { run: ProjectRun | null }) {
  return (
    <section className="panel detail-panel">
      <h2>Teknik Sonuç</h2>
      {!run ? (
        <p className="muted">Ajan akışı çalışınca burada görünür.</p>
      ) : (
        <>
          <div className="metric-grid">
            <div className="metric">
              <span>Status</span>
              <strong>{run.status}</strong>
            </div>
            <div className="metric">
              <span>Tests</span>
              <strong>
                {run.tests.passed}/{run.tests.total}
              </strong>
            </div>
          </div>
          {run.projectSummary && <p>{run.projectSummary}</p>}
          {run.ragSources.length > 0 && (
            <div className="tag-list">
              {run.ragSources.map((source) => (
                <span key={source}>{source}</span>
              ))}
            </div>
          )}
          {run.diff && <pre className="diff-preview">{run.diff}</pre>}
        </>
      )}
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge ${status.toLowerCase()}`}>{status}</span>;
}

function NoticeBar({ notice }: { notice: Notice }) {
  return <div className={`notice ${notice.tone}`}>{notice.text}</div>;
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : "Bilinmeyen hata";
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function routeFromTimeline(events: ProjectTimelineEvent[]): RouteDecision | null {
  const assistantEvents = [...events]
    .reverse()
    .filter((event) => event.kind === "assistant_message");
  for (const event of assistantEvents) {
    const intent = event.metadata.intent;
    const routedBy = event.metadata.router_source;
    const confidence = event.metadata.router_confidence;
    if (typeof intent !== "string" || typeof routedBy !== "string") {
      continue;
    }
    const numericConfidence =
      typeof confidence === "number" ? confidence : Number(confidence || 0);
    return {
      intent,
      routedBy,
      confidence: Number.isFinite(numericConfidence) ? numericConfidence : 0,
      action:
        typeof event.metadata.action === "string" ? event.metadata.action : undefined,
      actionTarget:
        typeof event.metadata.action_target === "string"
          ? event.metadata.action_target
          : undefined,
      readOnly:
        typeof event.metadata.action_read_only === "boolean"
          ? event.metadata.action_read_only
          : undefined,
      requiresWorkflow:
        typeof event.metadata.action_requires_workflow === "boolean"
          ? event.metadata.action_requires_workflow
          : undefined,
      safetyStatus:
        typeof event.metadata.action_safety_status === "string"
          ? event.metadata.action_safety_status
          : undefined,
      safetyMessage:
        typeof event.metadata.action_safety_message === "string"
          ? event.metadata.action_safety_message
          : undefined,
      reason:
        typeof event.metadata.router_reason === "string"
          ? event.metadata.router_reason
          : "",
      shouldRunWorkflow: event.metadata.routed_direct !== true,
      label: `${routedBy}: ${intent}, confidence: ${
        Number.isFinite(numericConfidence) ? numericConfidence.toFixed(2) : "0.00"
      }`
    };
  }
  return null;
}

export default App;
