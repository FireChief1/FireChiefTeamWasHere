import type { ChangeEvent, FormEvent, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  applyProjectChanges,
  loadCapabilities,
  loadFolder,
  loadProjects,
  openProject,
  sendProjectMessage
} from "./api";
import type {
  Capabilities,
  FolderListing,
  ImageAttachmentPayload,
  ProjectBundle,
  ProjectCheckpoint,
  ProjectRecord,
  ProjectRun,
  ProjectTimelineEvent,
  RouteDecision
} from "./types";

const DEFAULT_PATH = "/Users/erkutates/Desktop/FinalProject";
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const SUPPORTED_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

type Notice = {
  tone: "info" | "error" | "success";
  text: string;
};

type AttachedImageDraft = ImageAttachmentPayload & {
  size: number;
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
  const [isApplying, setIsApplying] = useState(false);
  const [pendingMessage, setPendingMessage] = useState("");
  const [attachedImage, setAttachedImage] = useState<AttachedImageDraft | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [route, setRoute] = useState<RouteDecision | null>(null);
  const [run, setRun] = useState<ProjectRun | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [codeBackend, setCodeBackend] = useState<string>(() => {
    try {
      return localStorage.getItem("ct-code-backend") || "";
    } catch {
      return "";
    }
  });
  const [theme, setTheme] = useState<"space" | "light">(() => {
    try {
      return localStorage.getItem("ct-theme") === "light" ? "light" : "space";
    } catch {
      return "space";
    }
  });

  useEffect(() => {
    void refreshProjects();
    void refreshFolder(DEFAULT_PATH);
    void loadCapabilities()
      .then((caps) => {
        setCapabilities(caps);
        // Keep the user's saved choice; fall back to the server default when
        // unset, or to local if their saved cloud choice is no longer available.
        setCodeBackend((prev) => {
          if (prev === "anthropic" && !caps.anthropicAvailable) return "ollama";
          return prev || caps.defaultCodeBackend;
        });
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!codeBackend) return;
    try {
      localStorage.setItem("ct-code-backend", codeBackend);
    } catch {
      /* storage unavailable; selection still applies for this session */
    }
  }, [codeBackend]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("ct-theme", theme);
    } catch {
      /* storage unavailable; theme still applies for this session */
    }
  }, [theme]);

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
  const visibleProjects = useMemo(() => dedupeProjects(projects), [projects]);

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
      setSidebarOpen(false);
      setNotice({ tone: "success", text: "Proje açıldı." });
      await refreshProjects();
    } catch (error) {
      setNotice({ tone: "error", text: formatError(error) });
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanMessage = message.trim() || (attachedImage ? "Bu görseli yorumla." : "");
    if (!cleanMessage || !bundle) {
      return;
    }
    setIsSending(true);
    setPendingMessage(cleanMessage);
    setMessage("");
    setNotice({ tone: "info", text: "Mesaj işleniyor." });
    setRoute(null);
    setRun(null);
    try {
      const response = await sendProjectMessage({
        projectPath: bundle.project.path,
        message: cleanMessage,
        maxIterations,
        useRag,
        codeBackend,
        image: attachedImage
          ? {
              name: attachedImage.name,
              mimeType: attachedImage.mimeType,
              data: attachedImage.data
            }
          : undefined
      });
      setBundle({
        project: response.project,
        timeline: response.timeline,
        checkpoints: response.checkpoints
      });
      setRoute(response.route);
      setRun(response.run || null);
      setMessage("");
      setAttachedImage(null);
      setNotice({
        tone: response.ranWorkflow ? "success" : "info",
        text: response.ranWorkflow
          ? "Teknik ajan akışı tamamlandı."
          : "Sohbet olarak yanıtlandı."
      });
      await refreshProjects();
    } catch (error) {
      setMessage(cleanMessage);
      setNotice({ tone: "error", text: formatError(error) });
    } finally {
      setIsSending(false);
      setPendingMessage("");
    }
  }

  async function handleImageSelect(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
      setNotice({ tone: "error", text: "Sadece PNG, JPEG veya WebP yükleyebilirsin." });
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setNotice({ tone: "error", text: "Görsel en fazla 5 MB olabilir." });
      return;
    }
    try {
      const data = await readFileAsDataUrl(file);
      setAttachedImage({
        name: file.name,
        mimeType: file.type,
        data,
        size: file.size
      });
      setNotice({ tone: "info", text: "Görsel eklendi; mesajla birlikte analiz edilir." });
    } catch (error) {
      setNotice({ tone: "error", text: formatError(error) });
    }
  }

  async function handleApplyChanges(applyToken: string) {
    if (!bundle || !applyToken) {
      return;
    }
    setIsApplying(true);
    setNotice({ tone: "info", text: "Değişiklikler uygulanıyor." });
    try {
      const response = await applyProjectChanges({
        projectPath: bundle.project.path,
        applyToken
      });
      setBundle({
        project: response.project,
        timeline: response.timeline,
        checkpoints: response.checkpoints
      });
      setRun((current) =>
        current
          ? {
              ...current,
              previewOnly: false,
              pendingApply: null,
              writtenFiles: response.apply.writtenFiles
            }
          : current
      );
      const writtenFiles = response.apply.writtenFiles;
      setNotice({
        tone: "success",
        text: writtenFiles.length
          ? `Değişiklikler uygulandı: ${writtenFiles.join(", ")}`
          : "Değişiklikler uygulandı; yazılan dosya yok."
      });
      await refreshProjects();
    } catch (error) {
      setNotice({ tone: "error", text: formatError(error) });
    } finally {
      setIsApplying(false);
    }
  }

  return (
    <main className={sidebarOpen ? "app-shell sidebar-open" : "app-shell"}>
      <button
        type="button"
        className="sidebar-scrim"
        aria-label="Menüyü kapat"
        tabIndex={sidebarOpen ? 0 : -1}
        onClick={() => setSidebarOpen(false)}
      />
      <aside className="sidebar">
        <header className="brand">
          <span className="brand-mark">CT</span>
          <div>
            <h1>Code Team</h1>
            <p>React Project Workspace</p>
          </div>
          <button
            type="button"
            className="sidebar-close"
            aria-label="Menüyü kapat"
            onClick={() => setSidebarOpen(false)}
          >
            ✕
          </button>
        </header>

        <section className="panel">
          <div className="panel-heading">
            <h2>Projeler</h2>
            <button className="icon-button" onClick={() => void refreshProjects()}>
              Yenile
            </button>
          </div>
          <div className="project-list">
            {visibleProjects.length === 0 ? (
              <p className="muted">Kayıtlı proje yok.</p>
            ) : (
              visibleProjects.map((project) => (
                <button
                  className={
                    bundle?.project.path === project.path
                      ? "project-row selected"
                      : "project-row"
                  }
                  key={project.id}
                  onClick={() => void handleOpenProject(project.path)}
                >
                  <span className="project-main">
                    <strong>{project.name}</strong>
                    <code>{project.path}</code>
                  </span>
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
          {capabilities?.anthropicAvailable && (
            <div className="field-label">
              Kod motoru
              <div className="segmented">
                <button
                  type="button"
                  className={codeBackend === "ollama" ? "seg active" : "seg"}
                  onClick={() => setCodeBackend("ollama")}
                >
                  Lokal
                </button>
                <button
                  type="button"
                  className={codeBackend === "anthropic" ? "seg active" : "seg"}
                  onClick={() => setCodeBackend("anthropic")}
                >
                  Claude
                </button>
              </div>
            </div>
          )}
        </section>
      </aside>

      <section className="workspace">
        <div className="mobile-bar">
          <button
            type="button"
            className="hamburger"
            aria-label="Menüyü aç"
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((open) => !open)}
          >
            <span />
            <span />
            <span />
          </button>
          <span className="mobile-brand">
            <span className="brand-mark sm">CT</span>
            Code Team
          </span>
        </div>
        <header className="workspace-header">
          <div>
            <p className="eyebrow">Project Mode</p>
            <h2>{bundle?.project.name || "Proje seç"}</h2>
            <p>{bundle?.project.path || "Sol taraftan bir klasör aç."}</p>
          </div>
          <div className="header-actions">
            <button
              type="button"
              className="theme-toggle"
              onClick={() => setTheme((t) => (t === "space" ? "light" : "space"))}
              aria-label="Temayı değiştir"
              title="Temayı değiştir"
            >
              {theme === "space" ? "☀ Light" : "☾ Space"}
            </button>
            <StatusBadge status={bundle?.project.lastStatus || "READY"} />
          </div>
        </header>

        {notice && <NoticeBar notice={notice} />}

        <section className="content-grid">
          <div className="chat-column">
            <ProjectSummary project={bundle?.project || null} />
            <ChatTimeline
              events={chatEvents}
              pendingMessage={pendingMessage}
              ready={!!bundle}
              onPick={(text) => setMessage(text)}
            />
            <form className="composer" onSubmit={handleSend}>
              <div className="composer-main">
                <textarea
                  value={message}
                  disabled={!bundle || isSending}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder="Projeye mesaj yaz..."
                />
                {attachedImage && (
                  <div className="image-attachment">
                    <img alt="" src={attachedImage.data} />
                    <div>
                      <strong>{attachedImage.name}</strong>
                      <span>{formatBytes(attachedImage.size)}</span>
                    </div>
                    <button
                      disabled={isSending}
                      onClick={() => setAttachedImage(null)}
                      type="button"
                    >
                      Kaldır
                    </button>
                  </div>
                )}
                <label className={bundle && !isSending ? "file-picker" : "file-picker disabled"}>
                  Resim ekle
                  <input
                    accept="image/png,image/jpeg,image/webp"
                    disabled={!bundle || isSending}
                    onChange={handleImageSelect}
                    type="file"
                  />
                </label>
              </div>
              <button className="primary" disabled={!bundle || isSending}>
                {isSending ? "Çalışıyor" : "Gönder"}
              </button>
            </form>
          </div>

          <aside className="detail-column">
            <RoutePanel route={displayRoute} />
            <MemoryPanel memory={bundle?.memory || ""} />
            <CheckpointPanel checkpoints={bundle?.checkpoints || []} />
            <RunPanel
              isApplying={isApplying}
              onApply={handleApplyChanges}
              run={run}
            />
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

const CHAT_SUGGESTIONS = [
  "Bu projeyi analiz et ve bir sonraki adımı öner",
  "Python ile bir Stack sınıfı yaz",
  "Node ile bir argümanları toplayan modül yaz ve test et",
  "Basit bir HTML/CSS landing page oluştur",
];

function ChatTimeline({
  events,
  pendingMessage,
  ready,
  onPick,
}: {
  events: ProjectTimelineEvent[];
  pendingMessage: string;
  ready: boolean;
  onPick: (text: string) => void;
}) {
  if (events.length === 0 && !pendingMessage) {
    return (
      <div className="empty-chat">
        <span className="empty-orbit" aria-hidden="true" />
        <h3>Sohbete başla</h3>
        <p>
          Mesaj sohbet ise direkt yanıtlanır; analiz veya kod görevi ise çok-ajanlı
          akış başlar. Python, Node.js ve statik web üretebilir, var olan dosyaları
          düzenleyebilir.
        </p>
        {ready ? (
          <div className="suggestion-chips">
            {CHAT_SUGGESTIONS.map((text) => (
              <button
                type="button"
                key={text}
                className="suggestion-chip"
                onClick={() => onPick(text)}
              >
                {text}
              </button>
            ))}
          </div>
        ) : (
          <p className="muted">Başlamak için soldan bir proje aç.</p>
        )}
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
          <div className="message-body">{renderMessageBody(event.body)}</div>
          {event.role === "assistant" && responseSourceFromEvent(event) && (
            <span className="message-source">
              {sourceLabel(responseSourceFromEvent(event))}
            </span>
          )}
          <time>{formatTime(event.createdAt)}</time>
        </article>
      ))}
      {pendingMessage && (
        <>
          <article className="message user pending">
            <p>{pendingMessage}</p>
            <span className="message-source">gönderiliyor</span>
          </article>
          <article className="message assistant pending">
            <p>
              <span className="pulse-dot" aria-hidden="true" /> Yanıt hazırlanıyor…{" "}
              <PendingTimer />
            </p>
            <p className="pending-hint">
              Lokal modellerde bir görev 1–3 dk sürebilir. Sayfayı yenileme veya
              tekrar gönderme — bittiğinde sonuç burada belirir.
            </p>
            <span className="message-source">çalışıyor</span>
          </article>
        </>
      )}
    </div>
  );
}

function PendingTimer() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const mm = Math.floor(seconds / 60);
  const ss = String(seconds % 60).padStart(2, "0");
  return <span className="pending-timer">{mm}:{ss}</span>;
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
          <div className="metric">
            <span>Response</span>
            <strong>{sourceLabel(route.responseSource || "unknown")}</strong>
          </div>
          <div className="metric">
            <span>Mode</span>
            <strong>{route.shouldRunWorkflow ? "Workflow" : "Direct"}</strong>
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

function MemoryPanel({ memory }: { memory: string }) {
  return (
    <section className="panel detail-panel">
      <h2>Project Memory</h2>
      {!memory ? (
        <p className="muted">Henüz compact memory yok.</p>
      ) : (
        <details>
          <summary>Özet ve semantic memory</summary>
          <pre className="memory-preview">{memory}</pre>
        </details>
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
                {checkpoint.taskProfile ? (
                  <ProfileBadge profile={checkpoint.taskProfile} />
                ) : (
                  <span>profile yok</span>
                )}
              </div>
              <p>{checkpoint.task}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function RunPanel({
  isApplying,
  onApply,
  run
}: {
  isApplying: boolean;
  onApply: (applyToken: string) => void;
  run: ProjectRun | null;
}) {
  return (
    <section className="panel detail-panel">
      <div className="panel-heading">
        <h2>Teknik Sonuç</h2>
        {run?.taskProfile && <ProfileBadge profile={run.taskProfile} />}
      </div>
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
          <RunDiagnostics run={run} />
          <ProjectFileSummary run={run} />
          {run.pendingApply && (
            <PendingApplyPanel
              isApplying={isApplying}
              onApply={onApply}
              pendingApply={run.pendingApply}
            />
          )}
          {run.ragSources.length > 0 && (
            <div className="tag-list">
              {run.ragSources.map((source) => (
                <span key={source}>{source}</span>
              ))}
            </div>
          )}
          {!run.pendingApply && run.diff && <pre className="diff-preview">{run.diff}</pre>}
        </>
      )}
    </section>
  );
}

function RunDiagnostics({ run }: { run: ProjectRun }) {
  const rejectedEntries = Object.entries(run.rejectedCode || {});
  if (
    !run.nodeError &&
    !run.devValidationError &&
    !run.devRepairAttempted &&
    rejectedEntries.length === 0
  ) {
    return null;
  }

  return (
    <div className="run-diagnostics">
      {run.devRepairAttempted && (
        <span className="status-note">Developer repair attempted</span>
      )}
      {run.nodeError && (
        <p>
          Node hatası: <code>{run.nodeError}</code>
        </p>
      )}
      {run.devValidationError && (
        <p>
          Developer doğrulama hatası: <code>{run.devValidationError}</code>
        </p>
      )}
      {rejectedEntries.length > 0 && (
        <details>
          <summary>Reddedilen kod</summary>
          {rejectedEntries.map(([filename, content]) => (
            <div className="rejected-code" key={filename}>
              <strong>{filename}</strong>
              <pre>{content}</pre>
            </div>
          ))}
        </details>
      )}
    </div>
  );
}

function ProjectFileSummary({ run }: { run: ProjectRun }) {
  if (
    run.plannedFiles.length === 0 &&
    run.writtenFiles.length === 0 &&
    !run.previewOnly
  ) {
    return null;
  }

  return (
    <div className="file-summary">
      {run.previewOnly && <span className="status-note">Preview only</span>}
      {run.plannedFiles.length > 0 && (
        <p>
          Planlanan:{" "}
          {run.plannedFiles.map((file) => (
            <code key={file}>{file}</code>
          ))}
        </p>
      )}
      {run.writtenFiles.length > 0 && (
        <p>
          Yazılan:{" "}
          {run.writtenFiles.map((file) => (
            <code key={file}>{file}</code>
          ))}
        </p>
      )}
    </div>
  );
}

function PendingApplyPanel({
  isApplying,
  onApply,
  pendingApply
}: {
  isApplying: boolean;
  onApply: (applyToken: string) => void;
  pendingApply: NonNullable<ProjectRun["pendingApply"]>;
}) {
  return (
    <div className="apply-panel">
      <h3>Project Mode Diff Preview</h3>
      <p>Dosyalar henüz yazılmadı. İncele, sonra uygula.</p>
      <p>
        Hedef: <code>{pendingApply.targetPath}</code>
      </p>
      {pendingApply.mcpRoot && (
        <p>
          MCP kökü: <code>{pendingApply.mcpRoot}</code>
        </p>
      )}
      {pendingApply.fileActions.length > 0 && (
        <div className="file-actions">
          {pendingApply.fileActions.map((item) => (
            <span key={`${item.file}-${item.action}`}>
              <code>{item.file}</code> {item.action}
            </span>
          ))}
        </div>
      )}
      {pendingApply.diff ? (
        <pre className="diff-preview">{pendingApply.diff}</pre>
      ) : (
        <p className="muted">Üretilen dosyalar mevcut içerikle aynı görünüyor.</p>
      )}
      <button
        className="primary"
        disabled={isApplying}
        onClick={() => onApply(pendingApply.token)}
      >
        {isApplying ? "Uygulanıyor" : "Değişiklikleri uygula"}
      </button>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge ${status.toLowerCase()}`}>{status}</span>;
}

const PROFILE_LABELS: Record<string, string> = {
  python: "Python",
  node_js: "Node.js",
  static_web: "Web",
  docs: "Docs",
  project: "Project",
};

function ProfileBadge({ profile }: { profile: string }) {
  const key = profile.toLowerCase();
  return (
    <span className={`profile-badge profile-${key}`}>
      {PROFILE_LABELS[key] || profile}
    </span>
  );
}

function stripLanguageTag(block: string): string {
  const newline = block.indexOf("\n");
  if (newline === -1) {
    return block;
  }
  const firstLine = block.slice(0, newline).trim();
  if (firstLine && /^[a-zA-Z0-9_+#.-]{1,15}$/.test(firstLine)) {
    return block.slice(newline + 1);
  }
  return block;
}

function renderMessageBody(text: string): ReactNode {
  // Lightweight, dependency-free rendering: split on ``` fences so code blocks
  // get monospace styling while prose stays readable.
  const segments = text.split("```");
  return segments.map((segment, index) => {
    if (index % 2 === 1) {
      return (
        <pre className="code-block" key={index}>
          <code>{stripLanguageTag(segment).replace(/\n+$/, "")}</code>
        </pre>
      );
    }
    const trimmed = segment.replace(/^\n+|\n+$/g, "");
    return trimmed ? <p key={index}>{trimmed}</p> : null;
  });
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
      responseSource:
        typeof event.metadata.response_source === "string"
          ? event.metadata.response_source
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

function dedupeProjects(projects: ProjectRecord[]): ProjectRecord[] {
  const seen = new Set<string>();
  const result: ProjectRecord[] = [];
  for (const project of projects) {
    if (seen.has(project.path)) {
      continue;
    }
    seen.add(project.path);
    result.push(project);
  }
  return result;
}

function responseSourceFromEvent(event: ProjectTimelineEvent): string {
  const source = event.metadata.response_source;
  return typeof source === "string" ? source : "";
}

function sourceLabel(source: string): string {
  switch (source) {
    case "action":
      return "action";
    case "fallback":
      return "fallback";
    case "model":
      return "model";
    case "router":
      return "router";
    case "vision":
      return "vision";
    case "workflow":
      return "workflow";
    default:
      return "unknown";
  }
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Görsel okunamadı."));
    reader.readAsDataURL(file);
  });
}

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${Math.round(size / 1024)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export default App;
