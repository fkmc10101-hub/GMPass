import { useEffect, useState } from "react";
import { api, IS_DEMO } from "./api";
import { ChatPage } from "./pages/ChatPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import type { Country, Health } from "./types";

type Tab = "chat" | "docs";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [countries, setCountries] = useState<Country[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);

  const refresh = () => {
    api.countries().then(setCountries).catch(() => setOffline(true));
    api.health().then((h) => { setHealth(h); setOffline(false); }).catch(() => setOffline(true));
  };
  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">GMP<b>ass</b></span>
          <span className="tagline">나라별 GMP 가이던스 근거 검색</span>
        </div>
        <nav>
          <button className={tab === "chat" ? "on" : ""} onClick={() => setTab("chat")}>질문하기</button>
          <button className={tab === "docs" ? "on" : ""} onClick={() => setTab("docs")}>문서 관리</button>
        </nav>
        <div className="status-line">
          {IS_DEMO && (
            <a className="badge demo" href="https://github.com/fkmc10101-hub/GMPass" target="_blank" rel="noreferrer"
               title="미리 받아 둔 실제 답변으로 동작하는 체험판입니다">
              체험용 데모 · 코드 보기 ↗
            </a>
          )}
          {offline ? (
            <span className="badge warn">서버 연결 안 됨</span>
          ) : health ? (
            <>
              {health.dry_run && <span className="badge warn" title="OPENAI_API_KEY가 없어 검색 결과만 보여 줍니다">테스트 모드</span>}
              <span className="sub">{health.llm_model} · 청크 {health.indexed_chunks}개</span>
            </>
          ) : null}
        </div>
      </header>
      <main>
        {tab === "chat" ? (
          <ChatPage countries={countries} />
        ) : (
          <DocumentsPage countries={countries} onChanged={refresh} />
        )}
      </main>
    </div>
  );
}
