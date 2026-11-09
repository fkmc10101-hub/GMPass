export type Mode = "single" | "compare";

export interface Country {
  code: string;
  name_ko: string;
  authority: string;
  main_documents: string[];
  language: string;
  indexed_documents: number;
}

export interface Citation {
  ref_no: number;
  cited: boolean;
  chunk_id: number | null;
  document_id: number | null;
  country: string;
  document_title: string;
  doc_code: string;
  version: string;
  effective_date: string;
  section: string;
  page: number | null;
  source_url: string;
  score: number;
  snippet: string;
}

export interface Answer {
  message_id: number | null;
  country: string;
  answer: string;
  citations: Citation[];
  review_required: boolean;
  review_reasons: string[];
  review_messages: string[];
  top_score: number;
  consistency: number | null;
}

export interface AskResponse {
  session_id: number;
  question_message_id: number;
  mode: Mode;
  countries: string[];
  answers: Answer[];
  model: string;
  cached: boolean;
  latency_ms: number;
  timings_ms: Record<string, number>;
  trace_id: string;
}

export interface SessionSummary {
  id: number;
  title: string;
  created_at: string;
  message_count: number;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  country: string;
  content: string;
  countries: string[];
  mode: Mode;
  review_required: boolean;
  review_reasons: string[];
  citations: Citation[];
  created_at: string;
}

export interface SessionDetail {
  id: number;
  title: string;
  created_at: string;
  messages: Message[];
}

export interface DocumentItem {
  id: number;
  country: string;
  title: string;
  doc_code: string;
  version: string;
  effective_date: string;
  language: string;
  source_url: string;
  file_name: string;
  status: "pending" | "indexed" | "failed";
  chunk_count: number;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface ChunkItem {
  id: number;
  chunk_index: number;
  section: string;
  page: number | null;
  char_count: number;
  text: string;
}

export interface Health {
  status: string;
  dry_run: boolean;
  llm_model: string;
  embedding_model: string;
  indexed_chunks: number;
}

export interface Translation {
  chunk_id: number;
  source_language: string;
  original: string;
  text_ko: string;
  model: string;
  cached: boolean;
  notice: string;
}
