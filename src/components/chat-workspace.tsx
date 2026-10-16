import { BrandMark } from "@/components/brand-mark";
import { ChatKitPanel } from "@/components/chatkit-panel";

export function ChatWorkspace() {
  const isConfigured = Boolean(
    process.env.NEXT_PUBLIC_CHATKIT_DOMAIN_KEY,
  );

  return (
    <main className="workspace">
      <header className="topbar">
        <a className="brand" href="#main-chat" aria-label="Northstar home">
          <BrandMark />
          <span className="brand-copy">
            <strong>Northstar</strong>
            <small>AI workspace</small>
          </span>
        </a>

        <div className="topbar-meta" aria-label="Application status">
          <span className="model-label">Gemini agent</span>
          <span className="status-pill">
            <span
              className={`status-dot ${isConfigured ? "" : "status-dot-pending"}`}
            />
            {isConfigured ? "Ready" : "Setup"}
          </span>
        </div>
      </header>

      <section className="hero" aria-labelledby="workspace-title">
        <div className="hero-copy">
          <p className="eyebrow">Private AI assistant</p>
          <h1 id="workspace-title">A focused place to think, ask, and act.</h1>
          <p>
            The conversation surface below is OpenAI ChatKit. The agent behind
            it routes each request to Gemini without exposing your API key.
          </p>
        </div>

        <div className="agent-card" aria-label="Agent role">
          <span className="agent-index">01</span>
          <div>
            <p>Agent role</p>
            <strong>Chat orchestrator</strong>
            <span>Context · Gemini · streaming · actions</span>
          </div>
        </div>
      </section>

      <section className="chat-stage" id="main-chat" aria-label="Chat assistant">
        <div className="chat-stage-header">
          <div>
            <span
              className={`live-indicator ${isConfigured ? "" : "status-dot-pending"}`}
            />
            <p>{isConfigured ? "Live workspace" : "Workspace preview"}</p>
          </div>
          <p className="privacy-note">Gemini key stays on the server</p>
        </div>
        <ChatKitPanel />
      </section>

      <footer className="page-footer">
        <span>ChatKit interface</span>
        <span>Gemini intelligence</span>
        <span>Server-side credentials</span>
      </footer>
    </main>
  );
}
