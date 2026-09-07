# -*- coding: utf-8 -*-
"""
build_changwon_master.py
창원국가산업단지 KICOX 산업동향 마스터데이터 구축·검증 파이프라인

데이터 우선순위
    1순위  KICOX 연간보정본        data/annual_revision/{구간}/YYYY[M|Q]n.xlsx
    2순위  KICOX 수정·재공시본      같은 폴더 규칙으로 추가하면 자동 인식
    3순위  공공데이터포털 과거 원자료  data/raw/{datasetId}_{YYYYMMDD}.csv

산출물
    data/processed/changwon_industry_master.csv   분기 x 10개 업종
    data/processed/changwon_total_master.csv      분기 x 창원국가산단 전체
    logs/raw_inventory.csv        원자료 구조 점검
    logs/revision_inventory.csv   보정 전후 값 비교
    logs/master_diff.csv          기존 마스터와의 차이
    logs/latest_points.json       지표별 최신 시점

실행
    pip install -r requirements.txt
    python src/build_changwon_master.py            # 포털 원자료 자동 다운로드 포함
    python src/build_changwon_master.py --offline  # data/raw 만 사용
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

import pandas as pd

try:
    import openpyxl
except ImportError:
    openpyxl = None

# Windows 콘솔의 기본 cp949에서도 한글과 특수문자 로그가 깨지거나
# UnicodeEncodeError로 중단되지 않도록 출력 인코딩을 고정한다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ----------------------------------------------------------------------------
# 설정
# ----------------------------------------------------------------------------

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_RAW = os.path.join(BASE, "data", "raw")
DIR_REV = os.path.join(BASE, "data", "annual_revision")
DIR_PROC = os.path.join(BASE, "data", "processed")
DIR_EXIST = os.path.join(BASE, "data", "existing")
DIR_LOG = os.path.join(BASE, "logs")

PORTAL = "https://www.data.go.kr"

DATASETS = {                       # 업종별 (분기 x 업종)
    "production": "15085898",
    "employment": "15085897",
    "op_rate":    "15085895",
    "firms_in":   "15085901",
    "firms_op":   "15085896",
}
DATASETS_TOTAL = {                 # 단지 전체 (분기)
    "production_total": "15085891",
    "employment_total": "15085890",
    "firms_in_total":   "15085894",
    "op_rate_total":    "15085889",
}

REV_SHEET_IND = {"production": "표5", "employment": "표9", "op_rate": "표12",
                 "firms_in": "표2", "firms_op": "표3"}
REV_SHEET_TOT = {"production_total": "표4", "employment_total": "표8",
                 "firms_in_total": "표1", "op_rate_total": "표10"}

INDUSTRIES = ["음식료", "섬유의복", "목재종이", "석유화학",
              "비금속", "철강", "기계", "전기전자", "운송장비", "기타"]
COMPLEX = "창원"

# 지표 성격  flow=기간합계 / stock=시점값 / ratio=비율
KIND = {"production": "flow", "employment": "stock", "firms_in": "stock",
        "firms_op": "stock", "op_rate": "ratio",
        "production_total": "flow", "employment_total": "stock",
        "firms_in_total": "stock", "op_rate_total": "ratio"}

QUARTERLY_FROM = "2024Q2"                     # 공표주기 월별 -> 분기별 전환
CLASSIFICATION_BREAKS = ["2018Q4", "2020Q3"]  # 조사개요 명시 표본교체·업종재분류
XCHECK_REVIEW, XCHECK_INVALID = 0.001, 0.01
SENS_CANDIDATE_ENDS = 5   # 유형 분류 민감도 검증에 쓰는 기준분기 후보 개수(최근 N개, 완전성 검사 전)

UA = {"User-Agent": "Mozilla/5.0"}
LOG_LINES: list[str] = []


def log(msg: str = "") -> None:
    print(msg)
    LOG_LINES.append(str(msg))


def ensure_dirs() -> None:
    for d in (DIR_RAW, DIR_REV, DIR_PROC, DIR_EXIST, DIR_LOG):
        os.makedirs(d, exist_ok=True)


# ----------------------------------------------------------------------------
# 공통 유틸
# ----------------------------------------------------------------------------

def _q_of(key: str) -> str:
    if "Q" in key:
        return key
    if "M" in key:
        y, m = key.split("M")
        return f"{y}Q{(int(m) - 1) // 3 + 1}"
    return f"{key[:4]}Q{(int(key[4:6]) - 1) // 3 + 1}"


def _is_quarter_end(key: str) -> bool:
    if "Q" in key:
        return True
    if "M" in key:
        return int(key.split("M")[1]) in (3, 6, 9, 12)
    return key[4:6] in ("03", "06", "09", "12")


def _month_of(key: str) -> int | None:
    if "M" in key:
        return int(key.split("M")[1])
    if "Q" in key:
        return None
    return int(key[4:6])


def _clean_col(h) -> str:
    return str(h).split("(")[0].strip() if h is not None else ""


def _to_num(v) -> tuple[float | None, int]:
    """(값, masked). 조사개요: 조사 대상 업체 5개 이하 단지는 X 표시(비공개).
    X는 masked=1로 남기고 값은 None. 0으로 바꾸지 않는다."""
    s = str(v).strip().replace(",", "") if v is not None else ""
    if s.upper() in ("X", "×"):
        return None, 1
    if s in ("", "-", "N/A", "None"):
        return None, 0
    try:
        return float(s), 0
    except ValueError:
        return None, 0


def _read_rows(path: str) -> tuple[list[list[str]], str]:
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            return list(csv.reader(io.StringIO(raw.decode(enc)))), enc
        except UnicodeDecodeError:
            continue
    return list(csv.reader(io.StringIO(raw.decode("cp949", "replace")))), "cp949(replace)"


# ----------------------------------------------------------------------------
# 1. 원자료 확보 / 로딩
# ----------------------------------------------------------------------------

def _post(url: str, data: dict, referer: str) -> bytes:
    h = dict(UA)
    h["X-Requested-With"] = "XMLHttpRequest"
    h["Referer"] = referer
    return urllib.request.urlopen(
        urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=h),
        timeout=90).read()


def _get(url: str, referer: str) -> bytes:
    h = dict(UA)
    h["Referer"] = referer
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=90).read()


def list_versions(pk: str) -> dict:
    ref = f"{PORTAL}/data/{pk}/fileData.do"
    page = _get(ref, ref).decode("utf-8", "replace")
    dpk = re.search(r'id="publicDataDetailPk"[^>]*value="(uddi:[0-9a-f\-]+)"', page).group(1)
    cur = re.search(r"파일데이터명[\s\S]{0,400}?_(\d{8})", page)
    hist = _post(f"{PORTAL}/tcs/dss/selectHistAndCsvData.do",
                 {"publicDataPk": pk, "publicDataDetailPk": dpk}, ref).decode("utf-8", "replace")
    out = {d: u for u, _n, d in
           re.findall(r'data-public-pk="(uddi:[0-9a-f\-]+)"[^>]*>\s*([^<]*?)(\d{8})\s*</a>', hist)}
    if cur:
        out[cur.group(1)] = dpk
    return out


def download_one(pk: str, date: str, detail_pk: str) -> str | None:
    fp = os.path.join(DIR_RAW, f"{pk}_{date}.csv")
    if os.path.exists(fp):
        return fp                       # 원본은 덮어쓰지 않는다
    ref = f"{PORTAL}/data/{pk}/fileData.do"
    for attempt in range(3):
        try:
            meta = json.loads(_post(f"{PORTAL}/tcs/dss/selectFileDataDownload.do",
                                    {"publicDataPk": pk, "publicDataDetailPk": detail_pk,
                                     "publicDataTyCode": "PR0051"}, ref).decode("utf-8"))
            if not meta.get("status"):
                raise RuntimeError(meta.get("error", "status=false"))
            body = _get(f"{PORTAL}/cmm/cmm/fileDownload.do?atchFileId={meta['atchFileId']}"
                        f"&fileDetailSn={meta['fileDetailSn']}&dataNm=x", ref)
            with open(fp, "wb") as f:
                f.write(body)
            return fp
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                log(f"  [다운로드 실패] pk={pk} date={date} :: {exc}")
                return None
            time.sleep(2)
    return None


def download_or_load_raw(offline: bool = False) -> dict:
    ensure_dirs()
    files: dict[str, dict[str, str]] = {}
    for name, pk in list(DATASETS.items()) + list(DATASETS_TOTAL.items()):
        if not offline:
            try:
                vers = list_versions(pk)
                log(f"[download] {name}({pk}) 포털 {len(vers)}건")
                for d, u in sorted(vers.items()):
                    download_one(pk, d, u)
            except Exception as exc:  # noqa: BLE001
                log(f"[경고] {name}({pk}) 목록 조회 실패 :: {exc}")
        got = {fn.split("_")[1][:8]: os.path.join(DIR_RAW, fn)
               for fn in sorted(os.listdir(DIR_RAW))
               if fn.startswith(pk + "_") and fn.endswith(".csv")}
        files[name] = got
        log(f"[load] {name:<17}: {len(got)}건")
    return files


# ----------------------------------------------------------------------------
# 2. 연간보정본 로딩 (1순위)
# ----------------------------------------------------------------------------

def load_revision() -> dict:
    out: dict[str, dict[str, dict]] = {k: {} for k in list(REV_SHEET_IND) + list(REV_SHEET_TOT)}
    if openpyxl is None:
        log("[경고] openpyxl 미설치 -> 보정본 건너뜀")
        return out
    paths = []
    for root, _d, fs in os.walk(DIR_REV):
        for f in fs:
            if f.endswith(".xlsx") and re.match(r"^\d{4}[MQ]\d{1,2}\.xlsx$", f):
                paths.append(os.path.join(root, f))
    if not paths:
        log("[정보] 보정본 없음 (data/annual_revision/{구간}/YYYY[M|Q]n.xlsx)")
        return out
    log(f"\n[revision] 보정본 {len(paths)}건 로딩")

    for p in sorted(paths):
        period = os.path.splitext(os.path.basename(p))[0]
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        for name, prefix in list(REV_SHEET_IND.items()) + list(REV_SHEET_TOT.items()):
            sheet = next((s for s in wb.sheetnames if s.startswith(prefix + " ")), None)
            if sheet is None:
                continue
            ws = wb[sheet]
            hdr = sub = cw = None
            for row in ws.iter_rows(values_only=True):
                first = str(row[0]).strip() if row and row[0] is not None else ""
                if first == "산업단지":
                    hdr = [_clean_col(c) for c in row]
                elif hdr is not None and sub is None and first == "":
                    sub = [_clean_col(c) for c in row]      # 병합 헤더 2행
                if first == COMPLEX:
                    cw = row
                    break
            if hdr is None or cw is None:
                continue
            vals = {}
            if name in REV_SHEET_IND:
                for i, h in enumerate(hdr):
                    if h in INDUSTRIES and i < len(cw):
                        vals[h] = _to_num(cw[i])
            else:
                idx = None
                for i, h in enumerate(hdr):
                    if h in ("당분기", "당월"):
                        idx = i
                        break
                if idx is None and sub:
                    for i, h in enumerate(sub):
                        if h in ("당분기", "당월"):
                            idx = i
                            break
                if idx is None:
                    for i, h in enumerate(hdr):
                        if "가동률" in str(h):
                            idx = i
                            break
                if idx is not None and idx < len(cw):
                    vals["_total"] = _to_num(cw[idx])
            if vals:
                out[name][period] = vals
        wb.close()
    for k, v in out.items():
        if v:
            log(f"  {k:<17}: {len(v)}시점 ({min(v)} ~ {max(v)})")
    return out


# ----------------------------------------------------------------------------
# 3. 원자료 구조 점검
# ----------------------------------------------------------------------------

def inspect_raw_files(files: dict) -> pd.DataFrame:
    recs = []
    for name, byd in files.items():
        for d, fp in sorted(byd.items()):
            rows, enc = _read_rows(fp)
            hdr = [_clean_col(h) for h in rows[0]] if rows else []
            cw = next((r for r in rows[1:] if r and r[0].strip() == COMPLEX), None)
            nvals = nmask = 0
            if cw:
                for i, h in enumerate(hdr):
                    if h in INDUSTRIES and i < len(cw):
                        v, m = _to_num(cw[i])
                        nvals += (v is not None)
                        nmask += m
            with open(fp, "rb") as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            recs.append(dict(indicator=name, date=d, file=os.path.basename(fp), enc=enc,
                             n_rows=max(len(rows) - 1, 0), n_cols=len(hdr),
                             has_changwon=cw is not None, has_nonmfg_col=("비제조" in hdr),
                             n_values=nvals, n_masked=nmask, md5=md5))
    df = pd.DataFrame(recs)
    log("\n=== 원자료 구조 요약 ===")
    for name in files:
        sub = df[df.indicator == name]
        if sub.empty:
            continue
        log(f"  {name:<17}: {len(sub)}건 {sub.date.min()}~{sub.date.max()} "
            f"| 열수 {sorted(sub.n_cols.unique())}")
    df.to_csv(os.path.join(DIR_LOG, "raw_inventory.csv"), index=False, encoding="utf-8-sig")
    return df


# ----------------------------------------------------------------------------
# 4. 포털 파싱
# ----------------------------------------------------------------------------

TOTAL_KEYS = ["당분기", "당월", "당분기_계", "당월_계", "입주_당분기", "입주_당월"]


def _parse_indicator(files: dict, name: str) -> dict:
    out: dict[str, dict] = {}
    for d, fp in sorted(files.get(name, {}).items()):
        rows, _ = _read_rows(fp)
        if not rows:
            continue
        hdr = [_clean_col(h) for h in rows[0]]
        cw = next((r for r in rows[1:] if r and r[0].strip() == COMPLEX), None)
        if cw is None:
            out[d] = {}
            continue
        vals = {}
        if name in DATASETS:
            for i, h in enumerate(hdr):
                if h in INDUSTRIES and i < len(cw):
                    vals[h] = _to_num(cw[i])
        else:
            idx = None
            for k in TOTAL_KEYS:
                if k in hdr:
                    idx = hdr.index(k)
                    break
            if idx is None and name == "op_rate_total":
                for i, raw_h in enumerate(rows[0]):
                    t = str(raw_h)
                    if "가동률" in t and ("당분기" in t or "당월" in t) and "전" not in t.split("_")[-1]:
                        idx = i
                        break
            if idx is not None and idx < len(cw):
                vals["_total"] = _to_num(cw[idx])
        out[d] = vals
    return out


def parse_production(files):      return _parse_indicator(files, "production")
def parse_employment(files):      return _parse_indicator(files, "employment")
def parse_operation_rate(files):  return _parse_indicator(files, "op_rate")
def parse_firms_in(files):        return _parse_indicator(files, "firms_in")
def parse_firms_operating(files): return _parse_indicator(files, "firms_op")


# ----------------------------------------------------------------------------
# 5. 무효 원자료 탐지 (일반 규칙, 날짜 하드코딩 없음)
# ----------------------------------------------------------------------------

def _total_from_file(path: str, keys, raw_contains=None) -> float | None:
    rows, _ = _read_rows(path)
    if not rows:
        return None
    hdr = [_clean_col(h) for h in rows[0]]
    cw = next((r for r in rows[1:] if r and r[0].strip() == COMPLEX), None)
    if cw is None:
        return None
    for k in keys:
        if k in hdr:
            v, _m = _to_num(cw[hdr.index(k)])
            if v is not None:
                return v
    for pat in (raw_contains or []):
        for i, raw_h in enumerate(rows[0]):
            if pat in str(raw_h) and i < len(cw):
                v, _m = _to_num(cw[i])
                if v is not None:
                    return v
    return None


def detect_invalid_sources(files: dict) -> tuple[dict, dict]:
    """규칙1  동일 지표의 두 시점 파일 내용이 완전 동일 -> 나중 시점 무효
       규칙2  업종별 '계' vs 단지 전체 값의 상대차이가 임계값 초과 -> 무효/확인필요"""
    invalid: dict[tuple[str, str], str] = {}
    review: dict[tuple[str, str], str] = {}

    for name in list(DATASETS) + list(DATASETS_TOTAL):
        seen: dict[str, str] = {}
        for d, fp in sorted(files.get(name, {}).items()):
            with open(fp, "rb") as f:
                h = hashlib.md5(f.read()).hexdigest()
            if h in seen:
                invalid[(name, d)] = f"원파일 내용이 {seen[h]}와 완전 동일(중복 등록)"
            else:
                seen[h] = d

    def val(name, d, keys, raw=None):
        fp = files.get(name, {}).get(d)
        return _total_from_file(fp, keys, raw) if fp else None

    dup = {k for k in invalid}          # MD5 중복으로 이미 무효인 (지표, 시점)

    dates = sorted(files.get("production", {}))
    for d in dates:
        a = val("production", d, ["계", "총계"])                    # 업종별 합계
        b = val("production_total", d, ["당분기", "당월"])           # 단지별 생산
        c = val("op_rate_total", d, [], ["당분기생산액", "당월생산액"])
        c = c / 100 if c is not None else None                     # 백만원 -> 억원
        cand = {"production": a, "production_total": b, "op_rate_total": c}
        have = {k: v for k, v in cand.items() if v is not None}
        if len(have) < 3:
            if a is not None and b is not None and b != 0:
                rel = abs(a - b) / abs(b)
                if rel > XCHECK_INVALID:
                    review[("production", d)] = f"업종별 {a:,.0f} vs 단지 {b:,.0f} ({rel:.2%}) 판정불가"
            continue
        # 3중 대조: 두 값이 일치하면 나머지 하나를 무효로 본다
        ref = None
        keys3 = list(have)
        for i in range(3):
            for j in range(i + 1, 3):
                x, y = have[keys3[i]], have[keys3[j]]
                if y != 0 and abs(x - y) / abs(y) <= XCHECK_REVIEW:
                    ref = (x + y) / 2
        if ref is None or ref == 0:
            review[("production", d)] = f"3개 출처가 모두 불일치: {have}"
            continue
        for k, v in have.items():
            if abs(v - ref) / abs(ref) > XCHECK_INVALID:
                invalid[(k, d)] = (f"3중 대조 불일치: {k}={v:,.0f}, 나머지 2개 합의값={ref:,.0f}")

    for d in sorted(files.get("employment", {})):
        a = val("employment", d, ["계", "총계"])
        b = val("employment_total", d, ["당분기_계", "당월_계", "계"])
        if a is None or b is None or b == 0:
            continue
        rel = abs(a - b) / abs(b)
        if rel <= XCHECK_REVIEW:
            continue
        # 어느 쪽이 틀렸는지 MD5 중복 여부로 가린다. 못 가리면 값을 지우지 않는다.
        if ("employment", d) in dup:
            invalid[("employment", d)] = (f"업종별 {a:,.0f} != 단지 전체 {b:,.0f} ({rel:.2%}) "
                                          f"+ 원파일 중복 -> 업종별 무효")
        elif ("employment_total", d) in dup:
            invalid[("employment_total", d)] = f"단지 전체 파일 중복 -> 무효"
        elif rel > XCHECK_INVALID:
            review[("employment", d)] = (f"업종별 {a:,.0f} vs 단지 {b:,.0f} ({rel:.2%}) "
                                         f"어느 쪽이 오류인지 판정 불가 -> 값 유지, 확인 필요")
        else:
            review[("employment", d)] = f"업종별과 단지 전체가 {a - b:,.0f} 차이({rel:.2%})"

    return invalid, review


# ----------------------------------------------------------------------------
# 6. 월 -> 분기 변환
# ----------------------------------------------------------------------------

def convert_monthly_to_quarterly(parsed: dict, kind: str, keys) -> tuple[dict, dict]:
    bucket: dict[str, list] = {}
    for d, vals in parsed.items():
        bucket.setdefault(_q_of(d), []).append((d, vals))

    values, notes = {}, {}
    for q, lst in bucket.items():
        lst.sort()
        if q >= QUARTERLY_FROM:                       # 공표주기 전환시점 명시 사용
            qe = next((v for d, v in lst if _is_quarter_end(d)), lst[-1][1])
            values[q] = {k: qe.get(k, (None, 0)) for k in keys}
            notes[q] = "분기공표" + (f" [경고]파일{len(lst)}건" if len(lst) > 1 else "")
            continue
        if kind == "stock":
            qe = next((v for d, v in lst if _is_quarter_end(d)), None)
            values[q] = {k: (qe.get(k, (None, 0)) if qe else (None, 0)) for k in keys}
            notes[q] = "월별: 분기말 값"
            continue
        got, incomplete, masked_any = {}, False, False
        for k in keys:
            series = [v.get(k, (None, 0)) for _d, v in lst]
            nums = [x[0] for x in series if x[0] is not None]
            masked = 1 if any(x[1] for x in series) else 0
            masked_any = masked_any or bool(masked)
            if kind == "flow":
                if len(lst) < 3 or len(nums) < len(lst):
                    got[k] = (None, masked)
                    incomplete = True
                else:
                    got[k] = (sum(nums), masked)
            else:
                got[k] = ((sum(nums) / len(nums)) if nums else None, masked)
        values[q] = got
        if kind == "flow":
            notes[q] = ("월별 3개월 합" if not incomplete else
                        ("월별 비공개(X) 포함 -> 분기 결측" if masked_any
                         else "월별 결측 포함 -> 분기 결측"))
        else:
            notes[q] = "월별 단순평균(근사)"
    return values, notes


# ----------------------------------------------------------------------------
# 7. 보정본 우선 선택
# ----------------------------------------------------------------------------

def _quarterize(portal_parsed: dict, rev_parsed: dict, kind: str, keys):
    """포털값과 보정본을 각각 분기화한 뒤, 같은 분기에 보정본이 있으면 보정본을 쓴다."""
    pv, pn = convert_monthly_to_quarterly(portal_parsed, kind, keys)
    rv, rn = (convert_monthly_to_quarterly(rev_parsed, kind, keys) if rev_parsed else ({}, {}))
    vals, notes, src = {}, {}, {}
    for q in sorted(set(pv) | set(rv)):
        if q in rv:
            vals[q] = rv[q]
            notes[q] = "보정본: " + rn.get(q, "")
            src[q] = "kicox_annual_revision"
        else:
            vals[q] = pv.get(q, {k: (None, 0) for k in keys})
            notes[q] = pn.get(q, "")
            src[q] = "data_portal_quarterly" if q >= QUARTERLY_FROM else "data_portal_monthly"
            if all(v[0] is None and v[1] == 0 for v in vals[q].values()):
                src[q] = "no_data"
    return vals, notes, src


# ----------------------------------------------------------------------------
# 8. 마스터 구축
# ----------------------------------------------------------------------------

QEND = {"1": "0331", "2": "0630", "3": "0930", "4": "1231"}


def build_master(files: dict, revision: dict, invalid: dict):
    parsed = {k: _parse_indicator(files, k) for k in DATASETS}
    for (name, d), _w in invalid.items():
        if name in parsed and d in parsed[name]:
            parsed[name][d] = {}
    conv = {k: _quarterize(parsed[k], revision.get(k, {}), KIND[k], INDUSTRIES) for k in DATASETS}

    invalid_q = {}
    for (name, d), why in invalid.items():
        invalid_q.setdefault((name, _q_of(d)), why)

    rows = []
    for q in sorted({q for k in conv for q in conv[k][0]}):
        qe = f"{q[:4]}-{QEND[q[-1]][:2]}-{QEND[q[-1]][2:]}"
        for ind in INDUSTRIES:
            rec = {"quarter": q, "quarter_end": qe, "complex_nm": COMPLEX,
                   "complex_type": "국가", "industry": ind,
                   "classification_break": 1 if q in CLASSIFICATION_BREAKS else 0}
            for k in DATASETS:
                vals, notes, src = conv[k]
                v, m = vals.get(q, {}).get(ind, (None, 0))
                note, source = notes.get(q, ""), src.get(q, "")
                bad = invalid_q.get((k, q))
                if bad and source == "kicox_annual_revision":
                    note = f"보정본으로 대체(이전 무효: {bad})"
                    bad = None
                if bad:
                    v, m, note = None, 0, f"무효원자료: {bad}"
                if k == "op_rate":
                    official = q >= QUARTERLY_FROM
                    rec["op_rate_official"] = v if official else None
                    rec["op_rate_approx"] = None if official else v
                    rec["op_rate_note"] = note
                    rec["op_rate_source"] = source
                    rec["op_rate_masked"] = m
                else:
                    rec[k] = v
                    rec[f"{k}_masked"] = m
                    rec[f"{k}_note"] = note
                    rec[f"{k}_source"] = source
                rec[f"{k}_is_revised"] = 1 if source == "kicox_annual_revision" else 0
                rec[f"{k}_invalid_source"] = 1 if bad else 0
            rows.append(rec)
    ind_df = pd.DataFrame(rows)

    parsed_t = {k: _parse_indicator(files, k) for k in DATASETS_TOTAL}
    for (name, d), _w in invalid.items():
        if name in parsed_t and d in parsed_t[name]:
            parsed_t[name][d] = {}          # 무효 원자료는 비운다
    # 단지별 파일이 없는 시점은 업종별 '계'로 보완한다(출처를 별도 표기)
    filled_from_ind = set()
    for d in sorted(files.get("production", {})):
        cur = parsed_t["production_total"].get(d, {}).get("_total", (None, 0))[0]
        if cur is not None:
            continue
        tot_v = _total_from_file(files["production"][d], ["계", "총계"])
        if tot_v is not None:
            parsed_t["production_total"][d] = {"_total": (tot_v, 0)}
            filled_from_ind.add(d)
    conv_t = {k: _quarterize(parsed_t[k], revision.get(k, {}), KIND[k], ["_total"])
              for k in DATASETS_TOTAL}
    trows = []
    for q in sorted({q for k in conv_t for q in conv_t[k][0]}):
        qe = f"{q[:4]}-{QEND[q[-1]][:2]}-{QEND[q[-1]][2:]}"
        rec = {"quarter": q, "quarter_end": qe, "complex_nm": COMPLEX, "complex_type": "국가",
               "classification_break": 1 if q in CLASSIFICATION_BREAKS else 0}
        for k in DATASETS_TOTAL:
            vals, notes, src = conv_t[k]
            v, m = vals.get(q, {}).get("_total", (None, 0))
            rec[k] = v
            rec[f"{k}_masked"] = m
            rec[f"{k}_note"] = notes.get(q, "")
            rec[f"{k}_source"] = src.get(q, "")
            rec[f"{k}_is_revised"] = 1 if src.get(q) == "kicox_annual_revision" else 0
        trows.append(rec)
    return ind_df, pd.DataFrame(trows)


# ----------------------------------------------------------------------------
# 9. 보정 전후 비교
# ----------------------------------------------------------------------------

def build_revision_inventory(files: dict, revision: dict) -> pd.DataFrame:
    recs = []
    for name in DATASETS:
        rev = revision.get(name, {})
        portal = _parse_indicator(files, name)
        for period, rvals in sorted(rev.items()):
            mm = _month_of(period)
            if mm is not None:
                cand = [d for d in portal if d[:4] == period[:4] and int(d[4:6]) == mm]
            else:
                cand = [d for d in portal if _q_of(d) == period and _is_quarter_end(d)]
            src_d = cand[0] if cand else None
            for ind in INDUSTRIES:
                rv, rm = rvals.get(ind, (None, 0))
                ov, om = (portal.get(src_d, {}).get(ind, (None, 0)) if src_d else (None, 0))
                comparable = src_d is not None
                same = ((ov is None and rv is None) or
                        (ov is not None and rv is not None and abs(ov - rv) < 1e-6))
                recs.append(dict(period=period, quarter=_q_of(period), industry=ind,
                                 indicator=name, original_value=ov, revised_value=rv,
                                 original_masked=om, revised_masked=rm,
                                 comparable=comparable,
                                 changed=(not same) if comparable else None,
                                 portal_file=src_d, source="kicox_annual_revision"))
    df = pd.DataFrame(recs)
    if not df.empty:
        df.to_csv(os.path.join(DIR_LOG, "revision_inventory.csv"),
                  index=False, encoding="utf-8-sig")
    return df


# ----------------------------------------------------------------------------
# 10. 검증
# ----------------------------------------------------------------------------

def validate_master(ind: pd.DataFrame, tot: pd.DataFrame) -> pd.DataFrame:
    log("\n" + "=" * 70)
    log("품질 검증")
    log("=" * 70)

    qs = sorted(ind.quarter.unique())
    ys = sorted({int(q[:4]) for q in qs})
    exp = [f"{y}Q{k}" for y in range(ys[0], ys[-1] + 1) for k in (1, 2, 3, 4)]
    exp = [q for q in exp if qs[0] <= q <= qs[-1]]
    log(f"\n[분기] {len(qs)}개 {qs[0]} ~ {qs[-1]} / 누락 {[q for q in exp if q not in qs] or '없음'}")
    bad = ind.groupby("quarter").industry.nunique()
    bad = bad[bad != len(INDUSTRIES)]
    log(f"[업종] 누락 {'없음' if bad.empty else bad.to_dict()}")

    log("\n[업종별 마스터 결측] (자동삭제 없음)")
    for c in ("production", "employment", "op_rate_official", "op_rate_approx",
              "firms_in", "firms_op"):
        mq = sorted(ind[ind[c].isna()].quarter.unique())
        log(f"  {c:<17}: {int(ind[c].isna().sum()):>3}행 / 분기 {len(mq)}개 "
            f"{mq if len(mq) <= 10 else str(mq[:10]) + '...'}")
    log("\n[전체 마스터 결측]")
    for c in DATASETS_TOTAL:
        mq = sorted(tot[tot[c].isna()].quarter.unique())
        log(f"  {c:<17}: 분기 {len(mq)}개 {mq if len(mq) <= 10 else str(mq[:10]) + '...'}")

    log("\n[비공개(X)] 조사대상 5개사 이하 보호 규칙")
    for c in DATASETS:
        mq = sorted(ind[ind[f"{c}_masked"] == 1].quarter.unique())
        if mq:
            log(f"  {c}: {mq}")

    log("\n[출처 구성]")
    for c in DATASETS:
        log(f"  {c:<11}: " + str(ind.groupby(f"{c}_source").quarter.nunique().to_dict()))

    log("\n[최신 시점]")
    latest = {}
    for c, lab in [("production", "latest_production"), ("employment", "latest_employment"),
                   ("op_rate_official", "latest_op_rate"), ("firms_in", "latest_firms")]:
        s = ind[ind[c].notna()].quarter
        latest[lab] = s.max() if len(s) else None
        log(f"  {lab:<22} = {latest[lab]}")
    latest["latest_common_quarter"] = min(v for v in latest.values() if v)
    log(f"  {'latest_common_quarter':<22} = {latest['latest_common_quarter']}")

    ind = ind.sort_values(["industry", "quarter"]).copy()
    for c in ("production", "employment"):
        # fill_method=None 명시: pandas 2.x 기본값(pad)은 결측을 앞 값으로 채워
        # 2023Q4·2024Q4 같은 전업종 결측 기준분기에서도 YoY를 만들어낸다.
        # 3.0.2에서는 기본값이 None이라 우연히 정상이었을 뿐이므로 명시 고정한다.
        ind[f"{c}_yoy"] = ind.groupby("industry")[c].pct_change(4, fill_method=None) * 100
        ind[f"{c}_yoy"] = ind[f"{c}_yoy"].replace([float("inf"), float("-inf")], pd.NA)
        # 방어 로직: 당분기 또는 기준(4분기 전) 값이 결측이면 무조건 YoY도 결측 처리
        yoy_base = ind.groupby("industry")[c].shift(4)
        ind.loc[ind[c].isna() | yoy_base.isna(), f"{c}_yoy"] = pd.NA
        ind[f"{c}_yoy_valid"] = ind[f"{c}_yoy"].notna()
    ind["quadrant_yoy_valid"] = ind.production_yoy_valid & ind.employment_yoy_valid
    vq = ind.groupby("quarter").quadrant_yoy_valid.all()
    latest["yoy_valid_quarters"] = sorted(vq[vq].index)
    log(f"\n[YoY] 10개 업종 모두 4분면 산출 가능 분기 {int(vq.sum())}개")
    log(f"  가능: {latest['yoy_valid_quarters']}")
    log(f"  불가: {sorted(vq[~vq].index)}")

    # 4분기 평균 비교구간 자동 설정
    common = latest["latest_common_quarter"]
    allq = sorted(ind.quarter.unique())
    i = allq.index(common)
    recent, prev = allq[i - 3:i + 1], allq[i - 7:i - 3]
    latest["window_recent"], latest["window_previous"] = recent, prev
    log(f"\n[4분기 평균 비교구간] 최근 {recent} vs 직전 {prev}")
    usable = ind[ind.quarter.isin(recent + prev)]
    for c in ("production", "employment"):
        miss = sorted(usable[usable[c].isna()].quarter.unique())
        log(f"  {c} 결측 분기: {miss or '없음'}")
    json.dump(latest, open(os.path.join(DIR_LOG, "latest_points.json"), "w"), ensure_ascii=False)

    ind["review_required"] = ((ind.production_yoy.abs() > 40) |
                              (ind.employment_yoy.abs() > 15)).fillna(False)
    log(f"\n[review_required] {int(ind.review_required.sum())}행 (삭제하지 않음)")
    log(f"[classification_break] 플래그 분기 {CLASSIFICATION_BREAKS} "
        f"(조사개요: '18.10월분, '20.9월분 표본교체·업종재분류)")
    return ind


def compare_existing_master(new: pd.DataFrame, path: str) -> None:
    log("\n" + "=" * 70)
    log("기존 마스터 vs 재구축 마스터")
    log("=" * 70)
    if not os.path.exists(path):
        log(f"  기존 파일 없음: {path}")
        return
    old = pd.read_csv(path)
    log(f"  행수 {len(old)} -> {len(new)} / 분기 {old.quarter.nunique()} -> {new.quarter.nunique()}")
    m = old.merge(new, on=["quarter", "industry"], suffixes=("_old", "_new"), how="outer")
    diffs = []
    for c in ["production", "employment", "firms_in", "firms_op"]:
        a, b = m.get(f"{c}_old"), m.get(f"{c}_new")
        if a is None or b is None:
            continue
        neq = ~((a.isna() & b.isna()) | ((a - b).abs() < 1e-6))
        for _, r in m[neq].iterrows():
            diffs.append(dict(quarter=r.quarter, industry=r.industry, var=c,
                              old=r[f"{c}_old"], new=r[f"{c}_new"],
                              source=r.get(f"{c}_source")))
    d = pd.DataFrame(diffs)
    if d.empty:
        log("  값 차이 없음")
    else:
        log(f"  값이 다른 셀 {len(d)}개")
        log("  변수별 분기수: " + str(d.groupby('var').quarter.nunique().to_dict()))
        log(f"  차이 분기: {sorted(d.quarter.unique())}")
        d.to_csv(os.path.join(DIR_LOG, "master_diff.csv"), index=False, encoding="utf-8-sig")


# ----------------------------------------------------------------------------
# 11. 유형 분류 민감도 검증 (임의 가중치 없음)
# ----------------------------------------------------------------------------

def sensitivity_check(ind: pd.DataFrame, latest: dict) -> pd.DataFrame:
    """기준분기와 집계방식을 바꿔가며 생산·고용 변화 방향을 재계산한다.
    모든 조합에서 방향이 같을 때만 '확정', 아니면 '유보'로 본다.
    임계값이나 가중치를 만들지 않고, 방향 일치 여부만 센다."""
    allq = sorted(ind.quarter.unique())
    cands = [q for q in allq if allq.index(q) >= 7][-SENS_CANDIDATE_ENDS:]

    # 집계 전에 완전성부터 검사한다: rec_w(최근 4분기) + prev_w(직전 4분기) = 8개 분기 전체에서
    # 10개 업종 모두 production·employment가 결측이 아니어야 그 기준분기를 유효로 채택한다.
    # groupby().agg('mean'/'median')는 NaN을 자동 제외하므로 집계 이후 값만 보면
    # 결측이 섞인 비교창도 정상 4분기 비교처럼 보인다 -> 반드시 집계 전에 걸러야 한다.
    valid_ends = []
    excluded = []
    windows = {}
    for end in cands:
        i = allq.index(end)
        rec_w, prev_w = allq[i - 3:i + 1], allq[i - 7:i - 3]
        windows[end] = (rec_w, prev_w)
        reasons = []
        for w_name, w in (("rec_w", rec_w), ("prev_w", prev_w)):
            for q in w:
                sub = ind[ind.quarter == q]
                for col in ("production", "employment"):
                    n_missing = int(sub[col].isna().sum())
                    if n_missing > 0:
                        reasons.append(f"{w_name}:{q}:{col} 결측 {n_missing}개 업종")
        if reasons:
            excluded.append((end, reasons))
            log(f"[민감도 제외] 기준분기 {end}: " + "; ".join(reasons))
        else:
            valid_ends.append(end)

    recs = []
    for end in valid_ends:
        rec_w, prev_w = windows[end]
        for agg in ("mean", "median"):
            a = ind[ind.quarter.isin(rec_w)].groupby("industry")[["production", "employment"]].agg(agg)
            b = ind[ind.quarter.isin(prev_w)].groupby("industry")[["production", "employment"]].agg(agg)
            for t in a.index:
                if pd.isna(a.production[t]) or pd.isna(b.production[t]) \
                        or pd.isna(a.employment[t]) or pd.isna(b.employment[t]):
                    log(f"[경고] 사전 완전성 검사를 통과했으나 집계 후 결측 발견: "
                        f"end={end} agg={agg} industry={t} -> 이중 안전장치로 제외")
                    continue
                dp = (a.production[t] / b.production[t] - 1) * 100
                de = (a.employment[t] / b.employment[t] - 1) * 100
                recs.append(dict(end_quarter=end, agg=agg, industry=t,
                                 production_change_pct=round(dp, 2),
                                 employment_change_pct=round(de, 2),
                                 production_dir="up" if dp > 0 else "down",
                                 employment_dir="up" if de > 0 else "down"))
    df = pd.DataFrame(recs)

    log("\n" + "=" * 70)
    log(f"유형 분류 민감도 (후보 기준분기 {len(cands)}개 → 유효 {len(valid_ends)}개 "
        f"x 집계 2종 = {len(valid_ends) * 2}조합)")
    log("=" * 70)
    log(f"  후보 기준분기: {cands}")
    log(f"  유효 기준분기: {valid_ends}")
    if excluded:
        log(f"  제외 기준분기: {[e for e, _ in excluded]}")

    if df.empty:
        log("  유효 조합 없음 -> quadrant_sensitivity.csv 미생성")
        return df
    df.to_csv(os.path.join(DIR_LOG, "quadrant_sensitivity.csv"),
              index=False, encoding="utf-8-sig")

    # 생산비중: 전체기간 평균 vs 최근 4분기(window_recent) 평균, 둘 다 산출해 병기한다.
    full_period_mean = ind.groupby("industry").production.mean()
    full_period_share = full_period_mean / full_period_mean.sum() * 100

    window_recent = latest.get("window_recent") or []
    rec_df = ind[ind.quarter.isin(window_recent)]
    recent_4q_mean = rec_df.groupby("industry").production.mean()
    recent_4q_share = recent_4q_mean / recent_4q_mean.sum() * 100

    share_df = pd.DataFrame({
        "industry": full_period_mean.index,
        "recent_4q_mean_production": recent_4q_mean.reindex(full_period_mean.index),
        "recent_4q_production_share": recent_4q_share.reindex(full_period_mean.index),
        "full_period_mean_production": full_period_mean,
        "full_period_production_share": full_period_share,
    }).sort_values("recent_4q_production_share", ascending=False)
    share_df.to_csv(os.path.join(DIR_LOG, "production_share.csv"),
                     index=False, encoding="utf-8-sig")

    order = share_df.industry.tolist()
    log(f"{'업종':<8}{'최근4Q비중':>10}{'전체기간비중':>12}{'생산방향':>16}{'고용방향':>16}  판정")
    for t in order:
        g = df[df.industry == t]
        if g.empty:
            continue
        pu, eu = (g.production_dir == "up").mean(), (g.employment_dir == "up").mean()
        r_share = share_df.loc[share_df.industry == t, "recent_4q_production_share"].iloc[0]
        f_share = share_df.loc[share_df.industry == t, "full_period_production_share"].iloc[0]
        pl = "증가" if pu == 1 else "감소" if pu == 0 else f"혼재({pu:.0%} 증가)"
        el = "증가" if eu == 1 else "감소" if eu == 0 else f"혼재({eu:.0%} 증가)"
        verdict = "확정" if pu in (0, 1) and eu in (0, 1) else \
                  "부분확정" if pu in (0, 1) or eu in (0, 1) else "유보"
        log(f"{t:<8}{r_share:>9.1f}%{f_share:>11.1f}%{pl:>16}{el:>16}  {verdict}")

    combo_share = share_df[share_df.industry.isin(["운송장비", "전기전자"])] \
        .recent_4q_production_share.sum()
    log(f"  운송장비+전기전자 최근4분기 생산비중 합계: {combo_share:.1f}%")
    log("  -> logs/quadrant_sensitivity.csv")
    log("  -> logs/production_share.csv")
    log("  주의: '유보'인 업종을 특정 유형으로 단정하면 안 된다.")
    return df


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-compare", action="store_true")
    args = ap.parse_args()

    ensure_dirs()
    log(f"실행 {datetime.now():%Y-%m-%d %H:%M:%S} | base={os.path.basename(BASE)}")

    files = download_or_load_raw(offline=args.offline)
    inspect_raw_files(files)
    revision = load_revision()

    invalid, review = detect_invalid_sources(files)
    log("\n=== 무효 원자료 판정 (일반 규칙) ===")
    if not invalid and not review:
        log("  없음")
    for (n, d), w in sorted(invalid.items()):
        log(f"  [사용불가] {n} {d}: {w}")
    for (n, d), w in sorted(review.items()):
        log(f"  [확인필요] {n} {d}: {w}")

    rev_inv = build_revision_inventory(files, revision)
    if not rev_inv.empty:
        comp = rev_inv[rev_inv.comparable == True]
        ch = comp[comp.changed == True]
        log(f"\n=== 보정 전후 비교 === 전체 {len(rev_inv)}셀 / 비교가능 {len(comp)}셀 / 변경 {len(ch)}셀")
        log("  비교불가 사유: 해당 월의 포털 원자료 미보유(stock 지표는 분기말만 수집)")
        log("  지표별 변경: " + str(ch.groupby("indicator").size().to_dict()))
        both = ch.dropna(subset=["original_value", "revised_value"]).copy()
        if len(both):
            both["d"] = (both.revised_value - both.original_value).abs()
            log("  지표별 평균 절대변화: "
                + str(both.groupby("indicator").d.mean().round(1).to_dict()))

    ind, tot = build_master(files, revision, invalid)
    ind = validate_master(ind, tot)
    sensitivity_check(ind, json.load(open(os.path.join(DIR_LOG, "latest_points.json"))))

    cols = (["quarter", "quarter_end", "complex_nm", "complex_type", "industry",
             "production", "employment", "op_rate_official", "op_rate_approx",
             "firms_in", "firms_op", "production_yoy", "employment_yoy",
             "production_yoy_valid", "employment_yoy_valid", "quadrant_yoy_valid",
             "review_required", "classification_break"]
            + [f"{k}_source" for k in DATASETS] + [f"{k}_is_revised" for k in DATASETS]
            + [f"{k}_masked" for k in DATASETS] + [f"{k}_invalid_source" for k in DATASETS]
            + [f"{k}_note" for k in DATASETS])
    p1 = os.path.join(DIR_PROC, "changwon_industry_master.csv")
    ind[[c for c in cols if c in ind.columns]].sort_values(["quarter", "industry"]) \
        .to_csv(p1, index=False, encoding="utf-8-sig")
    p2 = os.path.join(DIR_PROC, "changwon_total_master.csv")
    tot.sort_values("quarter").to_csv(p2, index=False, encoding="utf-8-sig")
    log(f"\n저장 -> {os.path.relpath(p1, BASE)} ({len(ind)}행)")
    log(f"저장 -> {os.path.relpath(p2, BASE)} ({len(tot)}행)")

    if not args.no_compare:
        compare_existing_master(ind, os.path.join(DIR_EXIST, "changwon_master_2018Q1_2026Q2.csv"))

    with open(os.path.join(DIR_LOG, f"build_{datetime.now():%Y%m%d_%H%M%S}.log"),
              "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))


if __name__ == "__main__":
    sys.exit(main())
