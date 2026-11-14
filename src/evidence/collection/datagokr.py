# -*- coding: utf-8 -*-
"""공공데이터포털(data.go.kr) 파일데이터 검색·조회·내려받기.

파일데이터 상세페이지가 schema.org DataDownload 로 공개하는 contentUrl 만 사용한다.
포털이 호출제한(자동등록방지)을 요구하면 그대로 기록하고 중단한다 — 우회하지 않는다.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass

from .http_client import Response, fetch

BASE = "https://www.data.go.kr"
_TAG = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return html.unescape(_TAG.sub(" ", s)).replace("\xa0", " ").strip()


@dataclass
class FileDataset:
    pk: str
    title: str
    page_url: str
    download_url: str | None
    updated: str | None = None
    institution: str | None = None


def search(keyword: str, *, per_page: int = 10) -> list[tuple[str, str]]:
    """파일데이터 검색 결과 (dataset_pk, title) 목록."""
    url = (f"{BASE}/tcs/dss/selectDataSetList.do?dType=FILE"
           f"&keyword={urllib.parse.quote(keyword)}&perPage={per_page}")
    r = fetch(url)
    if not r.ok:
        return []
    t = r.body.decode("utf-8", "replace")
    out, seen = [], set()
    for pk, title in re.findall(r'href="/data/(\d+)/fileData\.do"[^>]*>(.*?)</a>', t, re.S):
        if pk in seen:
            continue
        seen.add(pk)
        out.append((pk, _text(title)))
    return out


def describe(pk: str) -> tuple[FileDataset | None, Response]:
    """상세페이지에서 제목·제공기관·수정일·다운로드 URL 을 읽는다."""
    page = f"{BASE}/data/{pk}/fileData.do"
    r = fetch(page)
    if not r.ok:
        return None, r
    t = r.body.decode("utf-8", "replace")
    m = re.search(r"<title>(.*?)</title>", t, re.S)
    title = _text(m.group(1)) if m else pk
    dl = re.search(r'"contentUrl":\s*"([^"]+fileDownload\.do[^"]*)"', t)
    inst = re.search(r'"publisher":\s*\{[^}]*"name":\s*"([^"]*)"', t)
    upd = re.search(r'"(?:dateModified|modifiedDate)":\s*"([^"]*)"', t)
    return FileDataset(pk, title, page,
                       html.unescape(dl.group(1)) if dl else None,
                       upd.group(1) if upd else None,
                       inst.group(1) if inst else None), r


def resolve_registered_file(pk: str, detail_pk: str, file_detail_sn: str = "1") -> tuple[str | None, str | None]:
    """'원문파일등록' 형 파일데이터의 실제 첨부파일 id 를 얻는다.

    이런 데이터셋은 상세페이지에 contentUrl 이 없고, 다운로드 버튼이
    `fn_fileDataDown(publicDataPk, publicDataDetailPk, '', sn, hist)` 를 호출한다.
    그 함수는 /tcs/dss/selectFileDataDownload.do 에 물어 최상위 atchFileId 를 받아
    일반 파일 다운로드 경로로 넘긴다(포털 js/biz/datset/script_fileDetail.js 확인).
    """
    q = urllib.parse.urlencode(dict(publicDataDetailPk=detail_pk, publicDataPk=pk,
                                    atchFileId="", fileDetailSn=file_detail_sn,
                                    publicDataTyCode="PR0051"))
    r = fetch(f"{BASE}/tcs/dss/selectFileDataDownload.do?{q}",
              headers={"Referer": f"{BASE}/data/{pk}/fileData.do",
                       "X-Requested-With": "XMLHttpRequest"}, timeout=90)
    if not r.ok:
        return None, None
    try:
        j = json.loads(r.body.decode("utf-8"))
    except Exception:                                   # noqa: BLE001
        return None, None
    if not j.get("status"):
        return None, None
    return j.get("atchFileId"), str(j.get("fileDetailSn") or file_detail_sn)


def download_by_file_id(pk: str, atch_file_id: str, file_detail_sn: str = "1") -> Response:
    return fetch(f"{BASE}/cmm/cmm/fileDownload.do?atchFileId={atch_file_id}"
                 f"&fileDetailSn={file_detail_sn}&insertDataPrcus=N",
                 headers={"Referer": f"{BASE}/data/{pk}/fileData.do"}, timeout=300)


def download(ds: FileDataset) -> Response:
    if not ds.download_url:
        return Response(ds.page_url, 0, b"", {}, "no download url on page")
    return fetch(ds.download_url, headers={"Referer": ds.page_url}, timeout=180)


def decode_table(body: bytes) -> tuple[str, str]:
    """(텍스트, 사용한 인코딩). 원본 바이트는 별도로 그대로 저장한다."""
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return body.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return body.decode("cp949", "replace"), "cp949(replace)"
