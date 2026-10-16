"use client";

import { ChatKit, useChatKit } from "@openai/chatkit-react";

const apiURL = process.env.NEXT_PUBLIC_CHATKIT_API_URL ?? "/api/chatkit";
const domainKey = process.env.NEXT_PUBLIC_CHATKIT_DOMAIN_KEY;

export function ChatKitPanel() {
  if (!domainKey) {
    return (
      <div className="configuration-state" role="status">
        <span>Configuration needed</span>
        <h2>Add your ChatKit domain key</h2>
        <p>
          Set <code>NEXT_PUBLIC_CHATKIT_DOMAIN_KEY</code> in your local
          environment, then restart Next.js to load the official chat surface.
        </p>
      </div>
    );
  }

  return <ConfiguredChatKit domainKey={domainKey} />;
}

function ConfiguredChatKit({ domainKey }: { domainKey: string }) {
  const { control } = useChatKit({
    api: {
      url: apiURL,
      domainKey,
    },
    theme: {
      colorScheme: "light",
      color: {
        accent: {
          primary: "#0f766e",
          level: 2,
        },
      },
      radius: "round",
      density: "normal",
      typography: {
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
      },
    },
    header: {
      enabled: true,
    },
    history: {
      enabled: true,
    },
    startScreen: {
      greeting: "What can I help you work through?",
      prompts: [
        {
          label: "Plan a project",
          prompt: "Help me turn an idea into a clear project plan.",
          icon: "write",
        },
        {
          label: "Explain a topic",
          prompt: "Explain a difficult topic in simple language.",
          icon: "book-open",
        },
        {
          label: "Compare options",
          prompt: "Help me compare a few options and make a decision.",
          icon: "search",
        },
      ],
    },
    composer: {
      placeholder: "Message Northstar…",
    },
  });

  return <ChatKit control={control} className="chatkit-surface" />;
}
