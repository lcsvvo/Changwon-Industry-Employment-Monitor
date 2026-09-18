# ============================================================
# ppi_raw.csv 안에 어떤 업종/분류명(C1_NM)이 들어있는지
# 중복 없이 뽑아서 별도 CSV로 저장
# ============================================================

import csv

names = set()

with open("notebooks/ppi_raw.csv", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        names.add(row["C1_NM"])

sorted_names = sorted(names)

with open("notebooks/ppi_category_list.csv", "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["C1_NM (분류명)"])
    for n in sorted_names:
        writer.writerow([n])

print(f"저장 완료: notebooks/ppi_category_list.csv ({len(sorted_names)}개 분류)")
