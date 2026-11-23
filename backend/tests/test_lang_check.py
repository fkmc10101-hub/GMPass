from rag.lang_check import find_untranslated


def test_korean_with_parenthesized_originals_passes():
    text = "품질관리부서(quality control unit)가 제5조(第五条)에 따라 § 211.22(a)의 책임을 집니다.[1] GMP와 SOP도 허용됩니다."
    assert find_untranslated(text) == []


def test_english_left_outside_parentheses_is_flagged():
    found = find_untranslated("specification과 기준을 충족해야 합니다.[2]")
    assert "specification" in found


def test_japanese_left_outside_parentheses_is_flagged():
    found = find_untranslated("医薬品品質システム이 적절히 운영되어야 합니다.")
    assert found and "医薬品品質システム" in found[0]


def test_citation_numbers_and_cfr_references_are_ignored():
    assert find_untranslated("21 CFR Part 211 § 211.165 기준을 따릅니다.[1][3]") == []
