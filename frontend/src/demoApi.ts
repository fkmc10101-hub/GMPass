/**
 * 체험용 데모 API — GitHub Pages처럼 서버가 없는 곳에서 쓰인다.
 * 실제 백엔드에서 미리 받아 둔 응답(scripts/export_demo.py → public/demo/snapshot.json)을 같은 모양으로 돌려준다.
 * 그래서 화면 코드는 실제 서비스와 데모가 완전히 같다.
 */
import type {
  AskResponse, ChunkItem, Country, DocumentItem, Health, Message, Mode, SessionDetail, SessionSummary, Translation,
} from "./types";

export interface DemoQuestion {
  q: string;
  group: string;
}

interface Snapshot {
  generated_at: string;
  health: Health;
  countries: Country[];
  questions: DemoQuestion[];
  answers: Record<string, AskResponse>;
  translations: Record<string, Translation>;
  documents: DocumentItem[];
  chunks: Record<string, ChunkItem[]>;
}

let snapshotPromise: Promise<Snapshot> | null = null;
export function loadSnapshot(): Promise<Snapshot> {
  snapshotPromise ??= fetch(`${import.meta.env.BASE_URL}demo/snapshot.json`).then((r) => {
    if (!r.ok) throw new Error("데모 데이터를 불러오지 못했습니다.");
    return r.json() as Promise<Snapshot>;
  });
  return snapshotPromise;
}

const READ_ONLY = "체험용 데모에서는 문서를 바꿀 수 없어요. 실제 서비스에서는 관리자가 PDF·XML을 올려 바로 검색에 반영합니다.";
const norm = (s: string) => s.replace(/\s+/g, "").replace(/[?？!.]/g, "");
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

// 데모 대화 기록은 이 탭 안에서만 유지한다
const sessions: SessionDetail[] = [];

export const demoApi = {
  health: async () => (await loadSnapshot()).health,
  countries: async () => (await loadSnapshot()).countries,
  examples: async () => (await loadSnapshot()).questions,

  ask: async (question: string, _countries: string[], _mode: Mode, sessionId?: number): Promise<AskResponse> => {
    const snap = await loadSnapshot();
    const key = Object.keys(snap.answers).find((k) => norm(k) === norm(question));
    if (!key) {
      throw new Error("체험용 데모는 미리 준비한 예시 질문에만 답해요. 위의 예시 질문을 눌러 보세요. (실제 서비스는 어떤 질문이든 실시간으로 검색·답변합니다)");
    }
    await wait(600); // 답변이 '만들어지는' 느낌만 살짝
    const res = snap.answers[key];
    let s = sessions.find((x) => x.id === sessionId);
    if (!s) {
      s = { id: sessions.length + 1, title: question.slice(0, 60), created_at: new Date().toISOString(), messages: [] };
      sessions.unshift(s);
    }
    const base = { countries: res.countries, mode: res.mode, created_at: new Date().toISOString() };
    const userMsg: Message = {
      ...base, id: Date.now(), role: "user", country: "", content: question,
      review_required: false, review_reasons: [], citations: [],
    };
    const replies: Message[] = res.answers.map((a, i) => ({
      ...base, id: Date.now() + i + 1, role: "assistant", country: a.country, content: a.answer,
      review_required: a.review_required, review_reasons: a.review_reasons, citations: a.citations,
    }));
    s.messages.push(userMsg, ...replies);
    return { ...res, session_id: s.id };
  },
  sessions: async () => sessions.map((s): SessionSummary => ({ id: s.id, title: s.title, created_at: s.created_at, message_count: s.messages.length })),
  session: async (id: number) => {
    const s = sessions.find((x) => x.id === id);
    if (!s) throw new Error("대화를 찾을 수 없습니다.");
    return s;
  },
  deleteSession: async (id: number) => {
    const i = sessions.findIndex((x) => x.id === id);
    if (i >= 0) sessions.splice(i, 1);
  },
  feedback: async (_messageId: number, _rating: "up" | "down", _comment = "") => ({}),

  translate: async (chunkId: number): Promise<Translation> => {
    const t = (await loadSnapshot()).translations[String(chunkId)];
    if (!t) throw new Error("데모에서는 미리 번역해 둔 근거만 볼 수 있어요.");
    return t;
  },

  documents: async (country?: string) =>
    (await loadSnapshot()).documents.filter((d) => !country || d.country === country),
  chunks: async (id: number) => (await loadSnapshot()).chunks[String(id)] ?? [],
  upload: async (_form: FormData): Promise<DocumentItem> => { throw new Error(READ_ONLY); },
  reindex: async (_id: number): Promise<DocumentItem> => { throw new Error(READ_ONLY); },
  deleteDocument: async (_id: number): Promise<void> => { throw new Error(READ_ONLY); },
};
