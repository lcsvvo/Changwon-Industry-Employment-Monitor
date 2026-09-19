# -*- coding: utf-8 -*-
"""KEPCO 공식 『2021년 산업분류-법정동별 전력사용량』 XLSX 검증기.

왜 전용 파서인가
    내려받은 파일은 **ZIP 중앙디렉터리가 없는 잘린 파일**이다. openpyxl·pandas 는
    열지 못한다. 그래서 local file header 를 앞에서부터 걸어가며 **온전히 수신된
    멤버만** 복원한다. 잘린 시트는 복원하지 않고 잘렸다고 기록한다.
    깨진 파일을 정상인 척 분석하지 않기 위한 장치다.

이 스크립트가 하는 일
    1. 파일 무결성 판정 (ZIP EOCD 유무, 멤버별 잘림 여부)
    2. 시트 목록 = 월, 복원 가능한 월 식별
    3. 실제 컬럼 스키마 보고 (공식 설명과 다르면 실제 파일을 따른다)
    4. 창원시 5개 구 행만 추출 → 법정동 × KSIC 중분류 패널
    5. 5호 미만 비식별 표현 방식 확인

이 자료로 하지 않는 것
    - `businessType.do` 36업종 자료의 2021년 결손을 **대체하지 않는다.**
      분류체계(KSIC vs 한전 자체업종)·변수정의(판매량 vs 전력사용량)가 다르다.
    - 법정동명만 있고 법정동 **코드가 없다.** 창원국가산단 경계와 자동 결합하지
      않는다. 성산구를 창원국가산단으로 취급하지 않는다.

실행:  python scripts/verify_kepco_legal_dong_2021.py
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "data/raw/external/kepco/legal_dong/kepco_2021_industry_legal_dong_power.xlsx"
META = ROOT / "data/raw/external/kepco/legal_dong/_metadata"
PROC = ROOT / "data/processed/kepco"

CHANGWON_GU = ("창원시 의창구", "창원시 성산구", "창원시 마산합포구",
               "창원시 마산회원구", "창원시 진해구")
MASK_TOKEN = "5호미만제거"

ROW_RE = re.compile(rb"<row\b.*?</row>", re.S)
CELL_RE = re.compile(rb"<c\b[^>]*>.*?</c>|<c\b[^>]*/>", re.S)
TYPE_RE = re.compile(rb' t="([^"]+)"')
VAL_RE = re.compile(rb"<v>(.*?)</v>", re.S)
REF_RE = re.compile(rb' r="([A-Z]+)\d+"')


# ------------------------------------------------------------------ ZIP 복원
def walk_members(path: Path) -> tuple[dict, list[str], bool]:
    """local file header 를 걸어가며 멤버를 찾는다. 잘린 멤버는 truncated 로 돌린다."""
    size = path.stat().st_size
    members: dict[str, tuple[int, int, int, int]] = {}
    truncated: list[str] = []
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


def member_bytes(path: Path, members: dict, name: str) -> bytes:
    method, csize, _u, start = members[name]
    with path.open("rb") as f:
        f.seek(start)
        raw = f.read(csize)
    return zlib.decompress(raw, -15) if method == 8 else raw


def member_stream(path: Path, members: dict, name: str, chunk: int = 1 << 20):
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


# ------------------------------------------------------------------ 시트 파싱
def shared_strings(path: Path, members: dict) -> list[str]:
    if "xl/sharedStrings.xml" not in members:
        return []
    xml = member_bytes(path, members, "xl/sharedStrings.xml").decode("utf-8")
    return ["".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
            for si in re.findall(r"<si>(.*?)</si>", xml, re.S)]


def sheet_map(path: Path, members: dict) -> dict[str, str]:
    """시트 표시이름(=월) → 내부 파일명."""
    wb = member_bytes(path, members, "xl/workbook.xml").decode("utf-8")
    rels = member_bytes(path, members, "xl/_rels/workbook.xml.rels").decode("utf-8")
    rid_to_target = dict(re.findall(
        r'Id="(rId\d+)"[^>]*Target="(worksheets/[^"]+)"', rels))
    out = {}
    for name, rid in re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb):
        t = rid_to_target.get(rid)
        if t:
            out[name] = "xl/" + t
    return out


def row_cells(raw: bytes, sst: list[str]) -> dict[str, str]:
    """열 문자(A,B,...)를 키로 돌린다. 빈 셀이 생략돼도 열이 밀리지 않는다."""
    out: dict[str, str] = {}
    for cx in CELL_RE.findall(raw):
        ref = REF_RE.search(cx)
        if not ref:
            continue
        col = ref.group(1).decode()
        t = TYPE_RE.search(cx)
        v = VAL_RE.search(cx)
        if v is None:
            out[col] = ""
        elif t and t.group(1) == b"s":
            out[col] = sst[int(v.group(1))]
        else:
            out[col] = v.group(1).decode("utf-8", "replace")
    return out


def scan_sheet(path: Path, members: dict, sheet_file: str, sst: list[str],
               targets: set[str]) -> tuple[list[str], list[dict], int]:
    """한 시트를 스트리밍하며 헤더와 대상 시군구 행만 뽑는다."""
    prefilter = [f"<v>{i}</v>".encode() for i, s in enumerate(sst) if s in targets]
    header: list[str] = []
    kept: list[dict] = []
    n_rows = 0
    buf = b""
    for chunk in member_stream(path, members, sheet_file):
        buf += chunk
        last = 0
        for m in ROW_RE.finditer(buf):
            last = m.end()
            n_rows += 1
            raw = m.group(0)
            if n_rows == 1:
                c = row_cells(raw, sst)
                header = [c.get(k, "") for k in sorted(c, key=lambda x: (len(x), x))]
                continue
            if not any(p in raw for p in prefilter):
                continue
            c = row_cells(raw, sst)
            if c.get("D") in targets:
                kept.append(c)
        buf = buf[last:]
    return header, kept, n_rows


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=str(XLSX))
    args = ap.parse_args(argv)
    path = Path(args.xlsx)
    if not path.exists():
        print(f"[skip] 파일이 없다: {path}")
        return 1

    members, truncated, has_eocd = walk_members(path)
    sst = shared_strings(path, members)
    sheets = sheet_map(path, members)
    readable = {m: fn for m, fn in sheets.items() if fn in members}
    missing = {m: fn for m, fn in sheets.items() if fn not in members}

    integrity = "COMPLETE" if (has_eocd and not truncated and not missing) else "TRUNCATED"
    print(f"[integrity] {integrity}  size={path.stat().st_size:,}  EOCD={has_eocd}")
    print(f"[sheets] 선언 {len(sheets)}개 {sorted(sheets)}")
    print(f"[sheets] 복원가능 {len(readable)}개 {sorted(readable)}")
    print(f"[sheets] 복원불가 {len(missing)}개 {sorted(missing)} (잘림: {truncated})")

    header: list[str] = []
    rows: list[dict] = []
    per_month = {}
    for month in sorted(readable):
        h, kept, n = scan_sheet(path, members, readable[month], sst, set(CHANGWON_GU))
        header = header or h
        for c in kept:
            c["_month"] = month
        rows.extend(kept)
        per_month[month] = dict(sheet_rows=n, changwon_rows=len(kept))
        print(f"  {month}: 전체 {n:,}행 / 창원 {len(kept):,}행")

    cols = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
    names = ["year", "month", "sido", "sigungu", "legal_dong",
             "ksic_major_name", "ksic_major_code", "ksic_mid_name",
             "ksic_mid_code", "cust_cnt", "sales_kwh", "sales_charge_won"]
    masked = [r for r in rows if r.get("J") == MASK_TOKEN]
    dongs = sorted({(r.get("D"), r.get("E")) for r in rows})
    majors = sorted({(r.get("G"), r.get("F")) for r in rows})
    mids_c = sorted({(r.get("I"), r.get("H")) for r in rows if r.get("G") == "C"})

    report = dict(
        file=str(path.relative_to(ROOT)),
        file_size_bytes=path.stat().st_size,
        integrity=integrity,
        zip_eocd_present=has_eocd,
        truncated_member=truncated,
        sheets_declared=sorted(sheets),
        sheets_recoverable=sorted(readable),
        sheets_unrecoverable=sorted(missing),
        months_recoverable=len(readable), months_declared=len(sheets),
        header_actual=header,
        column_mapping=dict(zip(cols, names)),
        per_month=per_month,
        changwon_rows_total=len(rows),
        changwon_sigungu=sorted({r.get("D") for r in rows}),
        changwon_legal_dong_count=len(dongs),
        changwon_legal_dong_sample=[f"{a} {b}" for a, b in dongs[:20]],
        ksic_major_count=len(majors),
        ksic_major=[f"{c}:{n}" for c, n in majors],
        ksic_mid_count_manufacturing=len(mids_c),
        ksic_mid_manufacturing=[f"{c}:{n}" for c, n in mids_c],
        masking_token=MASK_TOKEN,
        masking_column="고객호수(J). 판매량·판매요금은 공백",
        masked_rows=len(masked),
        masked_share_pct=round(100 * len(masked) / len(rows), 2) if rows else None,
        unit_note=("헤더는 '판매량'·'판매요금'이라 단위 표기가 없지만, 포털 맞춤데이터 "
                   "상세페이지(2026-09-19 확인)가 제공항목을 '전력사용량 kwh'·'전기요금 원'·"
                   "'호수(5호미만제거)' 로 명시한다. 단위는 확정이다"),
        unit_source=("데이터 공유 > 맞춤데이터 공유 > '2022년 4월 산업분류-법정동별 전력사용량' "
                     "상세페이지 주요항목표"),
        legal_dong_code_present=False,
        spatial_note=("시군구는 창원시 5개 구, 그 아래 법정동'명'만 제공된다. "
                      "법정동 코드가 없어 창원국가산단 경계와 자동 결합할 수 없다"),
        substitution_verdict="PARTIAL",
        substitution_reason=("분류체계(KSIC) · 공간단위(법정동명) 가 businessType.do 의 "
                             "한전 자체 36업종 자료와 달라 2021년 결손을 동일 정의로 "
                             "복구하지 못한다"),
        retry_download_possible=False,
        retry_download_reason=("포털 '맞춤데이터 공유' 의 「산업분류-법정동별 전력사용량」 "
                               "시리즈는 2022년 4월이 가장 오래된 항목이다(등록일 2022-06-08). "
                               "2021년 파일이 목록에 없어 잘린 5개월을 이 경로로 재수신할 수 "
                               "없다 (2026-09-19 로그인 상태에서 확인)"),
        series_covers_analysis_period=("같은 시리즈가 2022년 4월~2026년을 덮는다. 분석기간을 "
                                       "법정동 해상도로 볼 수 있는 공식 경로가 있으나, KSIC "
                                       "분류라 36업종 계열을 대체하지는 못한다"),
    )
    META.mkdir(parents=True, exist_ok=True)
    (META / "legal_dong_2021_verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if rows:
        import csv
        PROC.mkdir(parents=True, exist_ok=True)
        out = PROC / "kepco_2021_legal_dong_changwon.csv"
        with out.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(names + ["source_sheet_month", "masked"])
            for r in rows:
                w.writerow([r.get(c, "") for c in cols]
                           + [r.get("_month"), r.get("J") == MASK_TOKEN])
        print(f"[ok] {out.relative_to(ROOT)} rows={len(rows)}")
    print(f"[ok] {(META / 'legal_dong_2021_verification.json').relative_to(ROOT)}")
    print(f"[verdict] 2021 보완 가능성 = {report['substitution_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
