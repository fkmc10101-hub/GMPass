import { useEffect, useState } from "react";
import { api } from "../api";
import { countryLabel } from "../countryLabel";
import type { ChunkItem, Country, DocumentItem } from "../types";

const STATUS: Record<DocumentItem["status"], string> = { pending: "색인 중", indexed: "완료", failed: "실패" };

export function DocumentsPage({ countries, onChanged }: { countries: Country[]; onChanged: () => void }) {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [filter, setFilter] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ doc: DocumentItem; chunks: ChunkItem[] } | null>(null);
  const [token, setToken] = useState(() => {
    try {
      return localStorage.getItem("gmpass.adminToken") ?? "";
    } catch {
      return "";
    }
  });

  const load = () => api.documents(filter || undefined).then(setDocs).catch((e) => setMsg(String(e.message ?? e)));
  useEffect(() => {
    load();
  }, [filter]);
  // 색인 중인 문서가 있으면 3초마다 상태를 다시 확인
  useEffect(() => {
    if (!docs.some((d) => d.status === "pending")) return;
    const t = setTimeout(() => {
      load();
      onChanged();
    }, 3000);
    return () => clearTimeout(t);
  }, [docs]);

  const saveToken = (v: string) => {
    setToken(v);
    try {
      localStorage.setItem("gmpass.adminToken", v);
    } catch {
      /* 저장 못 해도 이번 화면에서는 사용 */
    }
  };

  const onUpload = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    setBusy(true);
    setMsg("");
    try {
      const doc = await api.upload(new FormData(form));
      setMsg(`「${doc.title}」을 등록했습니다. 색인이 끝나면 상태가 「완료」로 바뀝니다.`);
      form.reset();
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      setMsg(done);
      load();
      onChanged();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : String(err));
    }
  };

  const showChunks = async (doc: DocumentItem) =>
    setPreview({ doc, chunks: await api.chunks(doc.id).catch(() => []) });

  return (
    <div className="docs">
      <section className="panel">
        <h2>가이던스 문서 등록</h2>
        <p className="hint">
          PDF·TXT·MD·HTML 또는 조항 단위 JSONL(prepare_sources 결과)을 올리면 조항 단위로 나눠 검색할 수 있게 색인합니다. 같은 파일은 한 번만 등록됩니다.
          스캔 PDF는 글자를 읽을 수 없어 실패할 수 있습니다.
        </p>
        <form className="upload" onSubmit={onUpload}>
          <label>
            국가·기구
            <select name="country" required defaultValue="">
              <option value="" disabled>선택</option>
              {countries.map((c) => (
                <option key={c.code} value={c.code}>{countryLabel(c.code)}</option>
              ))}
            </select>
          </label>
          <label className="wide">
            문서명 <input name="title" required maxLength={300} placeholder="예: EudraLex Volume 4 Annex 11" />
          </label>
          <label>
            문서 코드 <input name="doc_code" placeholder="예: Annex 11, 21 CFR 211" />
          </label>
          <label>
            버전 <input name="version" placeholder="예: 2011, Rev.1" />
          </label>
          <label>
            시행일 <input name="effective_date" type="date" />
          </label>
          <label className="wide">
            원문 URL <input name="source_url" type="url" placeholder="https://" />
          </label>
          <label className="wide">
            파일 <input name="file" type="file" required accept=".pdf,.txt,.md,.html,.htm,.jsonl" />
          </label>
          <button className="primary" disabled={busy}>{busy ? "업로드 중…" : "등록"}</button>
        </form>
        <details className="token">
          <summary>관리자 토큰 (서버에 ADMIN_TOKEN을 설정했을 때만)</summary>
          <input type="password" value={token} onChange={(e) => saveToken(e.target.value)} autoComplete="off" />
        </details>
        {msg && <div className="notice">{msg}</div>}
      </section>

      <section className="panel">
        <div className="row">
          <h2>등록된 문서 {docs.length}건</h2>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="국가 필터">
            <option value="">전체 국가</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>{countryLabel(c.code)}</option>
            ))}
          </select>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>국가</th><th>문서</th><th>버전·시행일</th><th>청크</th><th>상태</th><th></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{countryLabel(d.country)}</td>
                  <td>
                    <strong>{d.title}</strong>
                    {d.doc_code && <div className="sub">{d.doc_code}</div>}
                  </td>
                  <td>{[d.version, d.effective_date].filter(Boolean).join(" · ") || "-"}</td>
                  <td>{d.chunk_count}</td>
                  <td>
                    <span className={`status ${d.status}`} title={d.error_message}>{STATUS[d.status]}</span>
                  </td>
                  <td className="actions">
                    <button onClick={() => showChunks(d)} disabled={d.status !== "indexed"}>청크 보기</button>
                    <button onClick={() => act(() => api.reindex(d.id), "재색인을 시작했습니다.")}>재색인</button>
                    <button
                      className="danger"
                      onClick={() => {
                        if (window.confirm(`「${d.title}」을 삭제할까요? 원문 파일과 검색 데이터가 함께 지워집니다.`))
                          act(() => api.deleteDocument(d.id), "삭제했습니다.");
                      }}
                    >
                      삭제
                    </button>
                  </td>
                </tr>
              ))}
              {docs.length === 0 && (
                <tr><td colSpan={6} className="empty-row">등록된 문서가 없습니다.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {preview && (
        <section className="panel">
          <div className="row">
            <h2>청크 미리보기 — {preview.doc.title}</h2>
            <button onClick={() => setPreview(null)}>닫기</button>
          </div>
          <p className="hint">조항 제목(section)이 제대로 붙었는지 확인하세요. 처음 50개까지 보여 줍니다.</p>
          {preview.chunks.map((c) => (
            <div key={c.id} className="chunk">
              <div className="sub">#{c.chunk_index} · {c.section || "(조항 미인식)"}{c.page ? ` · p.${c.page}` : ""} · {c.char_count}자</div>
              <pre>{c.text}</pre>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
