# ============================================================
# 2021.01~2022.12 신규 수집분 + 기존 2023.01~2026.06 수집분을 합쳐서
# KICOX 업종에 매칭한 최종 확장본(2021.01~2026.06) 생성
# ============================================================

import csv

# KICOX 업종명 : PPI(C1_NM) 대분류명 매칭표 (기존과 동일)
INDUSTRY_MAP = {
    "기계":        ["기계및장비"],
    "운송장비":     ["운송장비"],
    "전기·전자":    ["전기장비"],
    "철강":        ["1차금속제품"],
    "음식료":       ["음식료품"],
    "석유·화학":    ["석탄및석유제품", "화학제품"],
}

c1nm_to_kicox = {}
for kicox_name, ppi_names in INDUSTRY_MAP.items():
    for ppi_name in ppi_names:
        c1nm_to_kicox[ppi_name] = kicox_name

def extract_matched(path):
    rows_out = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            c1_nm = row["C1_NM"]
            if c1_nm in c1nm_to_kicox:
                rows_out.append({
                    "KICOX_업종": c1nm_to_kicox[c1_nm],
                    "PPI_분류명": c1_nm,
                    "시점(YYYYMM)": row["PRD_DE"],
                    "PPI_지수값": row["DT"],
                    "단위": row["UNIT_NM"],
                })
    return rows_out

# 기존(2023.01~2026.06) + 신규(2021.01~2022.12)
# 현재 프로젝트 루트에서 실행하는 것을 기준으로 경로 지정
old_rows = extract_matched("ppi_raw.csv")
new_rows = extract_matched("ppi_raw_2021_2022.csv")

all_rows = old_rows + new_rows

# 중복 시점 제거 (혹시 겹치는 구간 있으면 최신 것 우선)
seen = {}
for r in all_rows:
    key = (r["KICOX_업종"], r["PPI_분류명"], r["시점(YYYYMM)"])
    seen[key] = r  # 뒤에 오는 값(신규 수집분 포함)으로 덮어씀

merged_rows = list(seen.values())
merged_rows.sort(key=lambda r: (r["KICOX_업종"], r["시점(YYYYMM)"]))

with open("notebooks/ppi_kicox_matched_2021_2026.csv", "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["KICOX_업종", "PPI_분류명", "시점(YYYYMM)", "PPI_지수값", "단위"])
    writer.writeheader()
    writer.writerows(merged_rows)

print(f"저장 완료: notebooks/ppi_kicox_matched_2021_2026.csv ({len(merged_rows)}행)")

from collections import Counter
counts = Counter(r["KICOX_업종"] for r in merged_rows)
print("\n업종별 행 수:")
for k, v in counts.items():
    print(f"  {k}: {v}행")

# 기간 확인
periods = sorted(set(r["시점(YYYYMM)"] for r in merged_rows))
print(f"\n수집 기간: {periods[0]} ~ {periods[-1]} (총 {len(periods)}개월)")