const LABELS: Record<string, string> = {
  ALL: "통합 답변",
  DIFF: "🔍 나라별 차이 분석",
  KR: "🇰🇷 한국 (식약처)",
  US: "🇺🇸 미국 (FDA)",
  EU: "🇪🇺 EU (EudraLex)",
  PICS: "PIC/S",
  JP: "🇯🇵 일본 (PMDA)",
  ICH: "ICH",
};

export const countryLabel = (code: string) => LABELS[code] ?? code;
