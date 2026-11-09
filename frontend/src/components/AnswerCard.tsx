import { useState } from "react";
import { api } from "../api";
import type { Answer, Citation } from "../types";
import { countryLabel } from "../countryLabel";

const REASON_LABEL: Record<string, string> = {
  NO_EVIDENCE: "근거 없음",
  LOW_RETRIEVAL_SCORE: "근거 유사도 낮음",
  NO_CITATION: "인용 없음",
  INVALID_CITATION: "잘못된 인용",
  INSUFFICIENT_CONTEXT: "근거 부족",
  LOW_CONSISTENCY: "답변 일관성 낮음",
  DRY_RUN: "테스트 모드",
};

/** 본문의 [1] 같은 인용 표시를 눌러 해당 근거로 이동할 수 있게 바꾼다 */
function renderWithRefs(text: string, onRef: (n: number) => void) {
  return text.split(/(\[\d+\])/g).map((part, i) => {
    const m = part.match(/^\[(\d+)\]$/);
    return m ? (
      <button key={i} className="ref" onClick={() => onRef(Number(m[1]))} title="근거 보기">
        {part}
      </button>
    ) : (
      <span key={i}>{part}</span>
    );
  });
}

function CitationItem({ c, open }: { c: Citation; open: boolean }) {
  const [ko, setKo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const canTranslate = c.country !== "KR" && c.chunk_id !== null;

  const translate = async () => {
    if (!c.chunk_id) return;
    setLoading(true);
    setErr("");
    try {
      setKo((await api.translate(c.chunk_id)).text_ko);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const where = [c.doc_code || c.document_title, c.version, c.section, c.page ? `p.${c.page}` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <details className={`citation ${c.cited ? "cited" : ""}`} open={open} id={`ref-${c.chunk_id}-${c.ref_no}`}>
      <summary>
        <span className="ref-no">[{c.ref_no}]</span>
        <span className="tag">{countryLabel(c.country)}</span>
        <span className="where">{where}</span>
        <span className="score" title="질문과 근거의 유사도">{c.score.toFixed(2)}</span>
      </summary>
      <p className="snippet">{c.snippet}…</p>
      {canTranslate && !ko && (
        <button className="translate" onClick={translate} disabled={loading}>
          {loading ? "번역 중…" : "한국어 번역 보기"}
        </button>
      )}
      {ko && (
        <div className="translation">
          <span className="sub">기계 번역 — 판단 근거는 원문을 기준으로 하세요</span>
          <p>{ko}</p>
        </div>
      )}
      {err && <p className="sub">{err}</p>}
      {c.source_url && (
        <a href={c.source_url} target="_blank" rel="noreferrer">
          원문 출처 열기
        </a>
      )}
    </details>
  );
}

export function AnswerCard({ answer, title }: { answer: Answer; title?: string }) {
  const [openRef, setOpenRef] = useState<number | null>(null);
  const [voted, setVoted] = useState<"up" | "down" | null>(null);

  const vote = async (rating: "up" | "down") => {
    if (!answer.message_id) return;
    try {
      await api.feedback(answer.message_id, rating);
      setVoted(rating);
    } catch {
      /* 평가 실패는 화면 흐름을 막지 않는다 */
    }
  };

  return (
    <article className={`answer ${answer.country === "DIFF" ? "diff" : ""} ${answer.review_required ? "needs-review" : ""}`}>
      <header>
        <h3>{title ?? countryLabel(answer.country)}</h3>
        {answer.review_required ? (
          <span className="badge warn" title={answer.review_messages.join("\n")}>
            검토 필요
          </span>
        ) : (
          <span className="badge ok">근거 확인됨</span>
        )}
      </header>

      {answer.review_required && (
        <ul className="reasons">
          {answer.review_reasons.map((r, i) => (
            <li key={r}>
              <strong>{REASON_LABEL[r] ?? r}</strong> — {answer.review_messages[i]}
            </li>
          ))}
        </ul>
      )}

      <div className="answer-text">{renderWithRefs(answer.answer, setOpenRef)}</div>

      {answer.citations.length > 0 && (
        <section className="citations">
          <h4>근거 문서</h4>
          {answer.citations.map((c) => (
            <CitationItem key={c.ref_no} c={c} open={openRef === c.ref_no} />
          ))}
        </section>
      )}

      <footer>
        <span className="meta">
          최고 유사도 {answer.top_score.toFixed(2)}
          {answer.consistency !== null && ` · 일관성 ${answer.consistency.toFixed(2)}`}
        </span>
        {answer.message_id && (
          <span className="vote">
            <button className={voted === "up" ? "on" : ""} onClick={() => vote("up")} aria-label="도움이 됐어요">
              👍
            </button>
            <button className={voted === "down" ? "on" : ""} onClick={() => vote("down")} aria-label="도움이 안 됐어요">
              👎
            </button>
          </span>
        )}
      </footer>
    </article>
  );
}
