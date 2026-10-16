# Northstar — ChatKit UI with a Gemini agent

A Next.js application that renders OpenAI's official ChatKit interface and
connects it to a custom Python ChatKit server backed by Gemini.

## Architecture

```text
Browser
  -> Next.js + @openai/chatkit-react
  -> POST /api/chatkit
  -> Python openai-chatkit server
  -> Gemini API
```

The Gemini API key is read only by the Python service. It is never included in
browser JavaScript and must not use a `NEXT_PUBLIC_` prefix.

## Prerequisites

- Node.js 20 or newer
- pnpm
- Python 3.11 or newer
- A Gemini API key
- A ChatKit domain key for the hostname where the frontend runs

## 1. Configure environment variables

Copy `.env.example` to `.env.local`. Copy `server/.env.example` to
`server/.env`. Use the same long random value for `CHATKIT_INTERNAL_TOKEN` in
both files, add the ChatKit domain key to `.env.local`, then add your Gemini
key to `server/.env`.

For local development, add `localhost` as an allowed domain when creating the
ChatKit domain key. Do not put the Gemini API key in `.env.local` or any
variable whose name begins with `NEXT_PUBLIC_`.

```dotenv
# server/.env
GEMINI_API_KEY=your-real-key
GEMINI_MODEL=gemini-3.6-flash
CHATKIT_INTERNAL_TOKEN=the-shared-internal-token
```

## 2. Install dependencies

```bash
pnpm install
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
```

## 3. Start both services

Terminal one:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server.app:app --reload --port 8000
```

Terminal two:

```bash
pnpm dev
```

Open `http://localhost:3000`.

## Agent role

The agent is the chat orchestrator. It loads thread history, applies the system
instruction, streams Gemini output into ChatKit events, updates thread titles,
and will own tool and widget actions as they are added. ChatKit remains the UI;
Gemini remains the model.

## Current scope

- Official ChatKit React surface
- Thread history and starter prompts
- Streaming Gemini responses
- Same-origin Next.js proxy
- Server-only API key
- In-memory development store
- Responsive application shell

File uploads are intentionally disabled until a durable attachment store is
implemented. The in-memory store must be replaced before production.
