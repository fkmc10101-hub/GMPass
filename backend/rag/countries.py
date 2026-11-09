"""GMPass가 다루는 규제 관할(국가·기구) 정의."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Jurisdiction:
    code: str
    name_ko: str
    authority: str
    main_documents: tuple[str, ...]
    language: str


JURISDICTIONS: dict[str, Jurisdiction] = {
    "KR": Jurisdiction(
        "KR",
        "대한민국",
        "식품의약품안전처(MFDS)",
        ("의약품 등의 안전에 관한 규칙 별표", "의약품 제조 및 품질관리에 관한 규정"),
        "ko",
    ),
    "US": Jurisdiction(
        "US",
        "미국",
        "FDA",
        ("21 CFR Part 210/211", "21 CFR Part 11", "FDA Guidance for Industry"),
        "en",
    ),
    "EU": Jurisdiction(
        "EU",
        "유럽연합",
        "European Commission / EMA",
        ("EudraLex Volume 4 Part I·II·III", "Annex 1~22"),
        "en",
    ),
    "PICS": Jurisdiction(
        "PICS",
        "PIC/S",
        "Pharmaceutical Inspection Co-operation Scheme",
        ("PE 009 GMP Guide", "PI 041 Data Integrity"),
        "en",
    ),
    "JP": Jurisdiction(
        "JP",
        "일본",
        "후생노동성(MHLW) / PMDA",
        ("GMP 성령(医薬品及び医薬部外品の製造管理及び品質管理の基準に関する省令)", "GMP 사례집"),
        "ja",
    ),
    "ICH": Jurisdiction(
        "ICH",
        "ICH(국제공통)",
        "International Council for Harmonisation",
        ("Q7", "Q9(R1)", "Q10"),
        "en",
    ),
}

VALID_CODES = tuple(JURISDICTIONS.keys())


def normalize_codes(codes: list[str] | None) -> list[str]:
    """빈 값이면 전체, 알 수 없는 코드는 ValueError."""
    if not codes:
        return list(VALID_CODES)
    out: list[str] = []
    for c in codes:
        cc = c.strip().upper()
        if cc not in JURISDICTIONS:
            raise ValueError(f"지원하지 않는 국가 코드입니다: {c}")
        if cc not in out:
            out.append(cc)
    return out
