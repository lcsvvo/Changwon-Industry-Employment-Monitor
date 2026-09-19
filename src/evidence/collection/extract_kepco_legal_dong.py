# -*- coding: utf-8 -*-
"""KEPCO 『산업분류-법정동별 전력사용량』 XLSX → 창원 발췌 + metadata.

출처
    전력데이터 개방포털 > 데이터 공유 > 맞춤데이터 공유 (pcode=000502)
    시리즈 「산업분류-법정동별 전력사용량」 (2013~2026, 총 25건)
    로그인한 사용자 본인 브라우저로 내려받았다. 로그인 우회 없음.

왜 전용 파서인가
    파일마다 포장이 다르다. 연도 1개 파일에 12개 시트인 것도 있고, 분기 1개
    파일에 시트 1개인 것도 있다. 헤더 문구도 판(版)마다 조금씩 다르다.
    그래서 시트 개수·열 순서를 가정하지 않고 **헤더 행을 읽어 열을 찾는다.**
    중앙디렉터리가 없는 잘린 파일도 local header 를 걸어가 복원 가능한 시트만 쓴다.

하지 않는 것
    - 비식별('5호미만제거') 값을 0 이나 추정치로 바꾸지 않는다. NaN + 플래그다.
    - 없는 월을 0 행으로 만들지 않는다. missing 은 metadata 에만 적는다.
    - 원자료 파일을 수정하지 않는다.

실행:  python src/evidence/collection/extract_kepco_legal_dong.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data/raw/kepco/api/legal_dong"
META = RAW / "_metadata"
OUT = ROOT / "data/processed/kepco"

CHANGWON_GU = ("창원시 의창구", "창원시 성산구", "창원시 마산합포구",
               "창원시 마산회원구", "창원시 진해구")
MASK_TOKEN = "5호미만제거"

ROW_RE = re.compile(rb"<row\b.*?</row>", re.S)
CELL_RE = re.compile(rb"<c\b[^>]*>.*?</c>|<c\b[^>]*/>", re.S)
TYPE_RE = re.compile(rb' t="([^"]+)"')
VAL_RE = re.compile(rb"<v>(.*?)</v>", re.S)
REF_RE = re.compile(rb' r="([A-Z]+)\d+"')

# 헤더 문구 → 표준 열 이름. 판마다 표기가 조금씩 달라 부분일치로 찾는다.
HEADER_MAP = [
    ("year",             ("년도", "연도")),
    ("month",            ("월",)),
    ("sido",             ("시도",)),
    ("sigungu",          ("시군구",)),
    ("legal_dong",       ("읍면동", "법정동")),
    ("ksic_major_name",  ("산업분류명(대)", "산업분류(대)", "대분류명")),
    ("ksic_major_code",  ("산업분류코드(대)", "대분류코드", "대분류 코드")),
    ("ksic_mid_name",    ("산업분류명(중)", "산업분류(중)", "중분류명")),
    ("ksic_mid_code",    ("산업분류코드(중)", "중분류코드", "중분류 코드")),
    ("customer_count",   ("고객호수", "호수")),
    ("power_usage",      ("판매량", "전력사용량")),
    ("charge_won",       ("판매요금", "전기요금")),
]


# ------------------------------------------------------------------ ZIP
def walk_members(path: Path):
    size = path.stat().st_size
    members, truncated = {}, []
    with path.open("rb") as f:
        f.seek(max(0, size - 65536))
        has_eocd = b"PK\x05\x06" in f.read()
        off = 0
        while True:
            f.seek(off)
            if f.read(4) != b"PK\x03\x04":
                break
            head = f.read(26)
            if len(head) < 26:
                break
            (_v, _fl, method, _mt, _md, _crc,
             csize, usize, nlen, elen) = struct.unpack("<HHHHHIIIHH", head)
            name = f.read(nlen).decode("utf-8", "replace")
            f.read(elen)
            start = f.tell()
            if start + csize > size:
                truncated.append(name)
                break
            members[name] = (method, csize, usize, start)
            off = start + csize
    return members, truncated, has_eocd


def member_bytes(path: Path, members, name: str) -> bytes:
    method, csize, _u, start = members[name]
    with path.open("rb") as f:
        f.seek(start)
        raw = f.read(csize)
    return zlib.decompress(raw, -15) if method == 8 else raw


def member_stream(path: Path, members, name: str, chunk: int = 1 << 20):
    method, csize, _u, start = members[name]
    dec = zlib.decompressobj(-15)
    with path.open("rb") as f:
        f.seek(start)
        left = csize
        while left > 0:
            buf = f.read(min(chunk, left))
            if not buf:
                break
            left -= len(buf)
            out = dec.decompress(buf) if method == 8 else buf
            if out:
                yield out


# ------------------------------------------------------------------ 시트
def shared_strings(path: Path, members) -> list[str]:
    if "xl/sharedStrings.xml" not in members:
        return []
    xml = member_bytes(path, members, "xl/sharedStrings.xml").decode("utf-8")
    return ["".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
            for si in re.findall(r"<si>(.*?)</si>", xml, re.S)]


def sheet_map(path: Path, members) -> dict[str, str]:
    wb = member_bytes(path, members, "xl/workbook.xml").decode("utf-8")
    rels = member_bytes(path, members, "xl/_rels/workbook.xml.rels").decode("utf-8")
    rid = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="(worksheets/[^"]+)"', rels))
    out = {}
    for name, r in re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb):
        if r in rid:
            out[name] = "xl/" + rid[r]
    return out


def row_cells(raw: bytes, sst: list[str]) -> dict[str, str]:
    out = {}
    for cx in CELL_RE.findall(raw):
        ref = REF_RE.search(cx)
        if not ref:
            continue
        col = ref.group(1).decode()
        t, v = TYPE_RE.search(cx), VAL_RE.search(cx)
        if v is None:
            out[col] = ""
        elif t and t.group(1) == b"s":
            i = int(v.group(1))
            out[col] = sst[i] if i < len(sst) else ""
        else:
            out[col] = v.group(1).decode("utf-8", "replace")
    return out


def resolve_header(header: dict[str, str]) -> dict[str, str]:
    """{열문자: 헤더문구} → {표준이름: 열문자}. 못 찾은 항목은 넣지 않는다."""
    found: dict[str, str] = {}
    norm = {c: re.sub(r"\s+", "", str(v)) for c, v in header.items()}
    for std, needles in HEADER_MAP:
        for col, text in norm.items():
            if col in found.values():
                continue
            if any(re.sub(r"\s+", "", n) == text for n in needles):
                found[std] = col
                break
        if std in found:
            continue
        for col, text in norm.items():
            if col in found.values():
                continue
            if any(re.sub(r"\s+", "", n) in text for n in needles):
                found[std] = col
                break
    return found


def scan_sheet(path: Path, members, sheet_file: str, sst, targets: set[str]):
    pre = [f"<v>{i}</v>".encode() for i, s in enumerate(sst) if s in targets]
    header_raw, cols, kept, n_rows = {}, {}, [], 0
    buf = b""
    for chunk in member_stream(path, members, sheet_file):
        buf += chunk
        last = 0
        for m in ROW_RE.finditer(buf):
            last = m.end()
            n_rows += 1
            raw = m.group(0)
            if n_rows == 1:
                header_raw = row_cells(raw, sst)
                cols = resolve_header(header_raw)
                continue
            if pre and not any(p in raw for p in pre):
                continue
            c = row_cells(raw, sst)
            if cols.get("sigungu") and c.get(cols["sigungu"]) in targets:
                kept.append({std: c.get(col, "") for std, col in cols.items()})
        buf = buf[last:]
    return header_raw, cols, kept, n_rows


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default="*.xlsx")
    args = ap.parse_args(argv)

    files = sorted(RAW.glob(args.pattern))
    if not files:
        print(f"[skip] {RAW} 에 xlsx 가 없다")
        return 1

    all_rows, file_meta = [], []
    for path in files:
        members, truncated, eocd = walk_members(path)
        if "xl/workbook.xml" not in members:
            print(f"[skip] {path.name}: workbook 을 읽을 수 없다")
            continue
        sst = shared_strings(path, members)
        sheets = sheet_map(path, members)
        readable = {m: fn for m, fn in sheets.items() if fn in members}
        missing_sheets = sorted(set(sheets) - set(readable))

        rows_this, per_sheet, header_seen, cols_seen = [], {}, {}, {}
        for sname in sorted(readable):
            header_raw, cols, kept, n = scan_sheet(
                path, members, readable[sname], sst, set(CHANGWON_GU))
            header_seen = header_seen or header_raw
            cols_seen = cols_seen or cols
            for r in kept:
                r["_source_file"] = path.name
                r["_source_sheet"] = sname
            rows_this.extend(kept)
            per_sheet[sname] = dict(sheet_rows=n, changwon_rows=len(kept))
        all_rows.extend(rows_this)

        ym = sorted({f'{r.get("year","")}-{str(r.get("month","")).zfill(2)}'
                     for r in rows_this if r.get("year")})
        masked = sum(1 for r in rows_this if r.get("customer_count") == MASK_TOKEN)
        file_meta.append(dict(
            file=path.name,
            source_url=("https://bigdata.kepco.co.kr/cmsmain.do?scode=S01&pcode=000502"
                        " (데이터 공유 > 맞춤데이터 공유 > 산업분류-법정동별 전력사용량)"),
            retrieved_via="사용자 본인 로그인 브라우저 다운로드 (로그인 우회 없음)",
            bytes=path.stat().st_size,
            sha256=sha256_file(path),
            zip_integrity="COMPLETE" if (eocd and not truncated and not missing_sheets)
                          else "TRUNCATED",
            truncated_member=truncated,
            sheets_declared=sorted(sheets),
            sheets_readable=sorted(readable),
            sheets_unreadable=missing_sheets,
            header_actual=[header_seen[c] for c in sorted(header_seen)] if header_seen else [],
            column_resolution=cols_seen,
            per_sheet=per_sheet,
            reference_months=ym,
            changwon_rows=len(rows_this),
            masked_rows=masked,
            masked_pct=round(100 * masked / len(rows_this), 2) if rows_this else None,
            unit={"power_usage": "kWh", "charge_won": "원",
                  "customer_count": "호 (5호 미만 비식별)"},
            suppression_rule=("개인정보보호법 제28조에 따라 5호 미만은 고객호수 칸에 "
                              f"'{MASK_TOKEN}' 문자열, 전력사용량·요금은 공백"),
        ))
        print(f"  {path.name}: 시트 {len(readable)}/{len(sheets)} · "
              f"창원 {len(rows_this):,}행 · 월 {ym[:1]}~{ym[-1:]} · 비식별 "
              f"{file_meta[-1]['masked_pct']}%")

    # ------------------------------------------------ 저장
    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["year", "month", "sido", "sigungu", "legal_dong",
            "ksic_major_code", "ksic_major_name", "ksic_mid_code", "ksic_mid_name",
            "customer_count", "power_usage", "charge_won",
            "_source_file", "_source_sheet"]
    out_csv = OUT / "kepco_legal_dong_changwon_raw.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols + ["suppressed"])
        for r in all_rows:
            w.writerow([r.get(c, "") for c in cols]
                       + [r.get("customer_count") == MASK_TOKEN])

    months = sorted({f'{r.get("year","")}-{str(r.get("month","")).zfill(2)}'
                     for r in all_rows if r.get("year")})
    META.mkdir(parents=True, exist_ok=True)
    (META / "legal_dong_collection.json").write_text(json.dumps(dict(
        series="KEPCO 산업분류-법정동별 전력사용량",
        portal="전력데이터 개방포털 > 데이터 공유 > 맞춤데이터 공유 (pcode=000502)",
        files=file_meta,
        months_covered=months,
        n_months=len(months),
        changwon_rows_total=len(all_rows),
        note=("자료가 없는 월은 행을 만들지 않는다. 0 으로 채우지 않는다. "
              "누락 여부는 패널 단계에서 coverage_flag 로 표시한다"),
    ), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] {out_csv.relative_to(ROOT)} rows={len(all_rows):,} months={len(months)}")
    if months:
        print(f"[ok] 월 범위 {months[0]} ~ {months[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
