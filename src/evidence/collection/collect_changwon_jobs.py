# -*- coding: utf-8 -*-
"""
창원(진해구·의창구·성산구) 채용정보 크롤러 — 최종본
- 목록 HTML 구조 + 페이지네이션 파라미터 모두 실제 브라우저에서 확인 완료 (2026-09-17)

사용법:
    pip install requests beautifulsoup4 pandas
    python src/evidence/collection/collect_changwon_jobs.py
"""

import re
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import pandas as pd

BASE_URL = "https://www.work.go.kr/changwon/infoPlace/empInfo/empInfoList.do"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

PAGE_UNIT = 10  # 10개씩 보기 기준
ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "data/raw/employment_center/changwon_jobs/changwon_jobs_latest.csv"

# 브라우저 주소창에서 그대로 확인된 파라미터
BASE_PARAMS = {
    "sortField": "DATE",
    "sortOrderBy": "DESC",
    "url": "",
    "WANTED_AUTH_NO": "",
    "subNaviMenuCd": "10200",
    "s": "1",
    "m": "1",
    "mode": "search",
    "menuId": "M200800001",
    "region": "48129|48121|48123",  # 진해구|의창구|성산구
    "occupation": "",
    "career": "",
    "regionNm": "경남 창원시 진해구|경남 창원시 의창구|경남 창원시 성산구",
    "occupationMn": "",
    "q_rd_term": "",
    "query": "",
    "comm_daily_clcd": "1",  # 상용
    "pageUnit": str(PAGE_UNIT),
}


def fetch_page(page_no: int) -> BeautifulSoup:
    params = dict(BASE_PARAMS)
    params["pageIndex"] = page_no
    params["startCnt"] = (page_no - 1) * PAGE_UNIT

    res = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=10)
    res.raise_for_status()
    res.encoding = "utf-8"
    return BeautifulSoup(res.text, "html.parser")


def extract_wanted_no(href: str) -> str:
    m = re.search(r"wantedAuthNo=([A-Z0-9]+)", href or "")
    return m.group(1) if m else ""


def parse_job_list(soup: BeautifulSoup) -> list[dict]:
    """
    확인된 구조:
    <table class="tbl_list"><tbody><tr>
      <td><a href="...wantedAuthNo=...">회사명</a></td>
      <td class="pl20 al">
        <a href="...">채용제목</a><br>
        <span>급여정보</span><br>
        <span class="fs_13">근무지역</span>
      </td>
      <td>[인증] 여부</td>
      <td><p id="hakNN">학력</p>경력</td>
      <td>등록일</td>
      <td><strong>마감일</strong></td>
    </tr></tbody></table>
    """
    jobs = []
    rows = soup.select("table.tbl_list tbody tr")

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 6:
            continue

        company_td, title_td, cert_td, edu_career_td, reg_td, due_td = cols[:6]

        company = company_td.get_text(strip=True)

        title_a = title_td.find("a")
        title = title_a.get_text(strip=True) if title_a else ""
        href = title_a.get("href", "") if title_a else ""
        wanted_auth_no = extract_wanted_no(href)

        wage_text = ""
        for sp in title_td.find_all("span"):
            if sp.get("class") != ["fs_13"]:
                wage_text = re.sub(r"\s+", " ", sp.get_text(strip=True))
                break

        region_span = title_td.find("span", class_="fs_13")
        region = region_span.get_text(strip=True) if region_span else ""

        cert = cert_td.get_text(strip=True)

        edu_p = edu_career_td.find("p")
        education = edu_p.get_text(strip=True) if edu_p else ""
        career = edu_career_td.get_text(separator=" ", strip=True).replace(education, "").strip()

        jobs.append({
            "wanted_auth_no": wanted_auth_no,
            "company": company,
            "title": title,
            "wage": wage_text,
            "region": region,
            "cert": cert,
            "education": education,
            "career": career,
            "reg_date": reg_td.get_text(strip=True),
            "due_date": due_td.get_text(strip=True),
            "detail_url": href,
        })

    return jobs


def main(max_pages: int = 200, sleep_sec: float = 1.0):
    all_jobs = []
    seen_ids = set()

    for page in range(1, max_pages + 1):
        print(f"[{page}/{max_pages}] 페이지 수집 중...")
        soup = fetch_page(page)
        jobs = parse_job_list(soup)

        if not jobs:
            print("공고가 더 없어 중단합니다.")
            break

        new_jobs = [j for j in jobs if j["wanted_auth_no"] not in seen_ids]
        if not new_jobs:
            print("더 이상 새 공고 없음 -> 중단합니다.")
            break

        for j in new_jobs:
            seen_ids.add(j["wanted_auth_no"])
        all_jobs.extend(new_jobs)
        time.sleep(sleep_sec)

    df = pd.DataFrame(all_jobs)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(f"완료: 총 {len(df)}건 저장 -> {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
