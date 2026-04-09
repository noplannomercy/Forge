# Forge HWPX Extractor — Design Spec

> 2026-04-09 | Forge HWPX 지원

## 배경

한국 공공/기업 문서의 상당수가 HWPX 포맷. TODO에 "HWPX 지원" 항목 있었음. 실제 파일(1.5MB, 103K자, 표 211개)로 구조 검증 완료.

## 목표

HWPX 문서에서 텍스트 + 표를 추출하여 마크다운으로 변환. DOCX extractor와 동일 수준.

## 설계 결정사항

| 결정 | 선택 | 이유 |
|------|------|------|
| 추출 범위 | 텍스트 + 표 | 표가 문서의 15%+ 차지 |
| VLM fallback | 없음 (extract만) | 텍스트 위주 문서, 103K자 추출 확인 |
| 의존성 | 표준 라이브러리만 (zipfile + xml.etree.ElementTree) | 추가 설치 불필요 |
| 경로 | extract 고정 | PPTX와 달리 텍스트 위주 |

## HWPX 구조

```
.hwpx = ZIP
  ├── Contents/
  │     └── section0.xml (본문)
  ├── BinData/ (이미지)
  └── ...
```

### XML 네임스페이스 (실제 파일에서 확인)

```python
ns = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}
```

### 텍스트: `hp:p → hp:run → hp:t`

```python
texts = [t.text.strip() for t in root.findall(".//hp:t", ns) if t.text and t.text.strip()]
```

### 표: `hp:tbl → hp:tr → hp:tc → hp:t`

```python
for tbl in root.findall(".//hp:tbl", ns):
    for tr in tbl.findall(".//hp:tr", ns):
        for tc in tr.findall(".//hp:tc", ns):
            cell_texts = [t.text for t in tc.findall(".//hp:t", ns)]
```

## 파일 변경

| 파일 | 변경 |
|------|------|
| `extractors/hwpx.py` | 신규 — HWPX 텍스트+표 → 마크다운 |
| `extractors/__init__.py` | `EXTRACTORS["hwpx"]` 등록 |
| `router.py` | `.hwpx` → `EXTRACT_FORMATS`에 추가 |
| `tests/test_extractor_hwpx.py` | 신규 — 더미 HWPX로 테스트 |

## 시그니처 (S4 준수)

```python
async def extract(file_bytes: bytes, file_name: str) -> ConvertResult
```

## 스코프 외

- VLM fallback (extract로 충분)
- 이미지 추출 (BinData/ 무시)
- 스타일/서식 (heading 구분 등)
