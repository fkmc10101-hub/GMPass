import { useEffect, useRef, useState } from "react";
import { api, DEFAULT_EXAMPLES, IS_DEMO } from "../api";
import { AnswerCard } from "../components/AnswerCard";
import { countryLabel } from "../countryLabel";
import type { Answer, Country, Message, Mode, SessionSummary } from "../types";

interface Turn {
  question: string;
  mode: Mode;
  answers: Answer[];
  meta?: string;
}


/** 저장된 대화(메시지 목록)를 질문 단위로 묶는다 */
function toTurns(messages: Message[]): Turn[] {
  const turns: Turn[] = [];
  for (const m of messages) {
    if (m.role === "user") turns.push({ question: m.content, mode: m.mode, answers: [] });
    else if (turns.length)
      turns[turns.length - 1].answers.push({
        message_id: m.id, country: m.country, answer: m.content, citations: m.citations,
        review_required: m.review_required, review_reasons: m.review_reasons,
        review_messages: [], top_score: Math.max(0, ...m.citations.map((c) => c.score)), consistency: null,
      });
  }
  return turns;
}

export function ChatPage({ countries }: { countries: Country[] }) {
  const [selected, setSelected] = useState<string[]>(["KR", "US", "JP"]);
  const [mode, setMode] = useState<Mode>("single");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<number | undefined>();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [examples, setExamples] = useState(DEFAULT_EXAMPLES);
  const bottom = useRef<HTMLDivElement>(null);

  const loadSessions = () => api.sessions().then(setSessions).catch(() => setSessions([]));
  useEffect(() => {
    loadSessions();
    api.examples().then(setExamples).catch(() => undefined);
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const toggle = (code: string) =>
    setSelected((s) => (s.includes(code) ? s.filter((c) => c !== code) : [...s, code]));

  const submit = async (q = question) => {
    const text = q.trim();
    if (text.length < 2 || loading) return;
    if (mode === "compare" && selected.length < 2) {
      setError("비교 모드는 국가를 2개 이상 선택해 주세요.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const res = await api.ask(text, selected, mode, sessionId);
      setSessionId(res.session_id);
      const slow = Object.entries(res.timings_ms).sort((a, b) => b[1] - a[1])[0];
      setTurns((t) => [
        ...t,
        {
          question: text,
          mode: res.mode,
          answers: res.answers,
          meta: `${res.model}${res.cached ? " · 캐시" : ""} · ${(res.latency_ms / 1000).toFixed(1)}초${
            slow ? ` · 가장 오래 걸린 단계 ${slow[0]} ${slow[1]}ms` : ""
          }`,
        },
      ]);
      setQuestion("");
      loadSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const openSession = async (id: number) => {
    try {
      const s = await api.session(id);
      setSessionId(s.id);
      setTurns(toTurns(s.messages));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const removeSession = async (id: number) => {
    await api.deleteSession(id).catch(() => undefined);
    if (id === sessionId) newChat();
    loadSessions();
  };

  const newChat = () => {
    setSessionId(undefined);
    setTurns([]);
    setError("");
  };

  return (
    <div className="chat-layout">
      <aside className="sessions">
        <button className="primary block" onClick={newChat}>
          + 새 대화
        </button>
        <ul>
          {sessions.map((s) => (
            <li key={s.id} className={s.id === sessionId ? "active" : ""}>
              <button className="link" onClick={() => openSession(s.id)} title={s.title}>
                {s.title}
              </button>
              <button className="icon" onClick={() => removeSession(s.id)} aria-label="대화 삭제">
                ×
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="chat">
        <div className="controls">
          <div className="chips" role="group" aria-label="국가 선택">
            {countries.map((c) => (
              <label key={c.code} className={`chip ${selected.includes(c.code) ? "on" : ""}`}
                     title={`${c.authority} · 색인 문서 ${c.indexed_documents}건`}>
                <input type="checkbox" checked={selected.includes(c.code)} onChange={() => toggle(c.code)} />
                {countryLabel(c.code)}
                <small>{c.indexed_documents}</small>
              </label>
            ))}
          </div>
          <div className="mode" role="radiogroup" aria-label="답변 방식">
            <button className={mode === "single" ? "on" : ""} onClick={() => setMode("single")}>
              통합 답변
            </button>
            <button className={mode === "compare" ? "on" : ""} onClick={() => setMode("compare")}>
              국가별 비교
            </button>
          </div>
        </div>

        <div className="turns">
          {turns.length === 0 && (
            <div className="empty">
              <h2>나라별 GMP 가이던스를 근거와 함께 찾아 드립니다</h2>
              <p>국가를 고르고 질문해 보세요. 「국가별 비교」를 켜면 나라마다 따로 검색해 나란히 보여 줍니다.</p>
              {IS_DEMO && (
                <p className="demo-note">
                  체험용 데모예요. 실제 서비스에서 받아 둔 답변을 보여 드려요. 아래 질문을 눌러 보세요.
                </p>
              )}
              {[...new Set(examples.map((e) => e.group))].map((g) => (
                <div key={g} className="example-group">
                  <h4>{g}</h4>
                  <div className="examples">
                    {examples.filter((e) => e.group === g).map((e) => (
                      <button key={e.q} onClick={() => submit(e.q)}>
                        {e.q}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className="turn">
              <div className="question">{t.question}</div>
              <div className={t.mode === "compare" ? "answers compare" : "answers"}>
                {t.answers.map((a) => (
                  <AnswerCard key={`${i}-${a.country}`} answer={a} />
                ))}
              </div>
              {t.meta && <div className="turn-meta">{t.meta}</div>}
            </div>
          ))}
          {loading && <div className="loading">근거를 찾고 답변을 만드는 중…</div>}
          <div ref={bottom} />
        </div>

        {error && <div className="error">{error}</div>}

        {IS_DEMO && turns.length > 0 && (
          <details className="more-examples">
            <summary>다른 예시 질문 보기</summary>
            <div className="examples compact">
            {examples.filter((e) => !turns.some((t) => t.question === e.q)).map((e) => (
              <button key={e.q} onClick={() => submit(e.q)} disabled={loading}>
                {e.q}
              </button>
            ))}
            </div>
          </details>
        )}

        <form
          className="ask"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={IS_DEMO ? "체험용 데모는 예시 질문에만 답해요. 위 질문을 눌러 보세요." : "예: 한국과 미국의 데이터 무결성 요구사항 차이는?"}
            rows={2}
            maxLength={1000}
          />
          <button className="primary" disabled={loading || question.trim().length < 2}>
            질문
          </button>
        </form>
        <p className="disclaimer">
          GMPass는 등록된 가이던스 문서를 찾아 요약할 뿐, 규제 해석이나 실사 대응 판단을 대신하지 않습니다. 반드시 원문을 확인하세요.
        </p>
      </section>
    </div>
  );
}
