import { demoApi, type DemoQuestion } from "./demoApi";
import type {
  AskResponse, ChunkItem, Country, DocumentItem, Health, Mode, SessionDetail, SessionSummary, Translation,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

function adminHeader(): Record<string, string> {
  let token = "";
  try {
    token = localStorage.getItem("gmpass.adminToken") ?? "";
  } catch {
    /* 저장소를 못 쓰는 환경이면 토큰 없이 요청 */
  }
  return token ? { "X-Admin-Token": token } : {};
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join(", ");
    } catch {
      /* JSON이 아닌 오류 응답 */
    }
    throw new Error(detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const DEFAULT_EXAMPLES: DemoQuestion[] = [
  { q: "출하 승인에 대해 한국과 미국은 어떻게 달라?", group: "나라별 차이" },
  { q: "전산 시스템의 Audit Trail 요구사항은?", group: "실무 질문" },
  { q: "변경관리 절차에서 꼭 평가해야 할 항목은?", group: "실무 질문" },
];

const realApi = {
  examples: async () => DEFAULT_EXAMPLES,
  health: () => request<Health>("/api/health"),
  countries: () => request<Country[]>("/api/countries"),

  ask: (question: string, countries: string[], mode: Mode, sessionId?: number) =>
    request<AskResponse>("/api/chat/ask", json({ question, countries, mode, session_id: sessionId ?? null })),
  sessions: () => request<SessionSummary[]>("/api/chat/sessions"),
  session: (id: number) => request<SessionDetail>(`/api/chat/sessions/${id}`),
  deleteSession: (id: number) => request<void>(`/api/chat/sessions/${id}`, { method: "DELETE" }),
  feedback: (messageId: number, rating: "up" | "down", comment = "") =>
    request(`/api/messages/${messageId}/feedback`, json({ rating, comment })),

  translate: (chunkId: number) => request<Translation>("/api/translate", json({ chunk_id: chunkId })),

  documents: (country?: string) =>
    request<DocumentItem[]>(`/api/documents${country ? `?country=${encodeURIComponent(country)}` : ""}`),
  chunks: (id: number) => request<ChunkItem[]>(`/api/documents/${id}/chunks?limit=50`),
  upload: (form: FormData) =>
    request<DocumentItem>("/api/documents", { method: "POST", body: form, headers: adminHeader() }),
  reindex: (id: number) =>
    request<DocumentItem>(`/api/documents/${id}/reindex`, { method: "POST", headers: adminHeader() }),
  deleteDocument: (id: number) =>
    request<void>(`/api/documents/${id}`, { method: "DELETE", headers: adminHeader() }),
};

/** VITE_DEMO=1로 빌드하면 서버 없이 미리 저장한 답변(public/demo/snapshot.json)으로 동작한다 */
export const IS_DEMO = import.meta.env.VITE_DEMO === "1";
export const api: typeof realApi = IS_DEMO ? demoApi : realApi;
