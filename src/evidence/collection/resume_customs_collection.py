# -*- coding: utf-8 -*-
"""관세청 수집 자동 이어받기 — 호출한도가 풀리면 남은 조합만 채운다.

왜 필요한가
    「관세청_시군구별 품목별 수출입실적」은 개발계정 기준 **일일 호출한도**가 있다.
    한도를 넘기면 HTTP 429 `LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR` 가
    돌아온다. 공식 안내는 "호출량이 초기화된 이후 다시 이용하거나 트래픽 증설을
    신청해 주세요" 이며, **초기화 시각을 명시하지 않고 Retry-After 헤더도 주지 않는다**
    (2026-09-19 실측). 그래서 낮은 빈도로 확인하다가 열리면 이어받는 방식이 필요하다.

동작
    1. 커버리지 매니페스트에서 미수집 조합을 센다. 0 이면 바로 끝낸다.
    2. **미수집 조합 1건만** 호출해 한도 상태를 본다(probe).
       이 호출은 버려지지 않는다 — 성공하면 그대로 저장된다.
    3. 200 이면 남은 조합을 이어서 수집한다. 수집 중 429 가 나면 즉시 멈추고
       체크포인트를 저장한 뒤 대기 상태로 돌아간다.
    4. 429 면 수집을 시작하지 않고 다음 probe 까지 기다린다.
    5. 결손이 0 이 되면 종료한다.

우회하지 않는 것
    키 교체, 다계정, 비공식 endpoint, 제한 우회는 하지 않는다.
    하는 일은 "열릴 때까지 낮은 빈도로 기다렸다가 이어받기" 뿐이다.

대기 간격
    Retry-After 헤더가 오면 **그 값을 최우선**으로 쓴다.
    없으면 기본 1시간. 공식 문서에 초기화 시각이 명시되면 그쪽을 우선해야 한다.

실행
    python src/evidence/collection/resume_customs_collection.py            # 끝날 때까지 상주
    python src/evidence/collection/resume_customs_collection.py --once     # 1회만 (작업 스케줄러용)
    python src/evidence/collection/resume_customs_collection.py --status   # 상태만 보고 종료
    python src/evidence/collection/resume_customs_collection.py --interval-minutes 60 --max-hours 48
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import collect_customs_exports as cc   # noqa: E402
from evidence.collection import secrets as S                     # noqa: E402
from evidence.collection.metadata import utcnow                  # noqa: E402

COVERAGE = ROOT / "data/raw/customs/trade/_metadata/coverage_manifest.json"
LOG = ROOT / "data/raw/customs/trade/_metadata/resume_log.json"
DEFAULT_INTERVAL_MIN = 60
DEFAULT_MAX_HOURS = 72


def missing_count() -> int | None:
    """아직 못 받은 HS6 × 연도창 조합 수. 매니페스트가 없으면 None."""
    if not COVERAGE.exists():
        return None
    cov = json.loads(COVERAGE.read_text(encoding="utf-8"))
    windows = [tuple(w) for w in cov["windows"]]
    done = {h: {tuple(w) for w in ws} for h, ws in cov["completed"].items()}
    return sum(1 for h in cov.get("hs6_partial", [])
               for w in windows if w not in done.get(h, set()))


def append_log(entry: dict) -> None:
    hist = []
    if LOG.exists():
        try:
            hist = json.loads(LOG.read_text(encoding="utf-8")).get("attempts", [])
        except Exception:                                    # noqa: BLE001
            hist = []
    hist.append(entry)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(dict(updated_at=utcnow(), attempts=hist[-200:]),
                              ensure_ascii=False, indent=2), encoding="utf-8")


def retry_after_seconds() -> int | None:
    """마지막 429 응답에 Retry-After 가 있었는지 확인한다.

    http_client 는 헤더를 Response 에 담아 주지만 collect() 안에서 소비되므로,
    여기서는 가장 최근 호출 기록을 다시 읽어 확인한다. 값이 없으면 None.
    """
    meta = ROOT / "data/raw/customs/trade/_metadata/changwon_hs6_trade_monthly.json"
    if not meta.exists():
        return None
    try:
        checks = json.loads(meta.read_text(encoding="utf-8"))["pagination"]["checks"]
    except Exception:                                        # noqa: BLE001
        return None
    for c in reversed(checks):
        if c.get("http_status") == 429:
            ra = c.get("retry_after")
            if ra:
                try:
                    return int(ra)
                except (TypeError, ValueError):
                    return None
            return None
    return None


def one_cycle(quiet: bool = False) -> dict:
    """probe 1건 → 열려 있으면 남은 조합 수집. 결과 요약을 돌려준다."""
    before = missing_count()
    if before == 0:
        return dict(state="DONE", missing_before=0, missing_after=0, new_calls=0)
    if before is None:
        return dict(state="NO_MANIFEST", missing_before=None)

    probe = cc.collect(limit=1, quiet=True)
    if probe["status"] == "NO_KEY":
        return dict(state="NO_KEY", missing_before=before)
    if probe["rate_limited"]:
        return dict(state="RATE_LIMITED", missing_before=before,
                    missing_after=before, new_calls=0)

    # probe 가 통과했다 — 한도가 열렸다. 남은 조합을 이어받는다.
    full = cc.collect(quiet=quiet)
    after = missing_count()
    return dict(state="DONE" if after == 0 else
                ("RATE_LIMITED" if full["rate_limited"] else "PARTIAL"),
                missing_before=before, missing_after=after,
                new_calls=probe["new_calls"] + full["new_calls"],
                rows=full.get("rows"), hs6_complete=full.get("hs6_complete"),
                hs6_partial=full.get("hs6_partial"))


def report(res: dict) -> None:
    msgs = {
        "DONE": "결손 없음 — 수집 완료",
        "RATE_LIMITED": "아직 호출한도 (HTTP 429)",
        "PARTIAL": "일부 수집 후 중단",
        "NO_KEY": "DATA_GO_KR_SERVICE_KEY 미설정",
        "NO_MANIFEST": "커버리지 매니페스트 없음",
    }
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msgs.get(res['state'], res['state'])}"
          f" · 미수집 {res.get('missing_before')} → {res.get('missing_after')}"
          f" · 이번 호출 {res.get('new_calls', 0)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="관세청 수집 자동 이어받기")
    ap.add_argument("--once", action="store_true", help="1회만 시도하고 종료")
    ap.add_argument("--status", action="store_true", help="상태만 출력(호출 없음)")
    ap.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MIN)
    ap.add_argument("--max-hours", type=float, default=DEFAULT_MAX_HOURS)
    a = ap.parse_args()

    S.load_env(ROOT)
    if a.status:
        n = missing_count()
        print(f"미수집 조합: {n}")
        if LOG.exists():
            hist = json.loads(LOG.read_text(encoding="utf-8"))["attempts"]
            for h in hist[-5:]:
                print(f"  {h.get('at')} {h.get('state')} "
                      f"missing {h.get('missing_before')}→{h.get('missing_after')}")
        return 0

    deadline = time.monotonic() + a.max_hours * 3600
    while True:
        res = one_cycle()
        res["at"] = utcnow()
        append_log(res)
        report(res)

        if res["state"] in ("DONE", "NO_KEY", "NO_MANIFEST"):
            return 0
        if a.once:
            return 0
        if time.monotonic() >= deadline:
            print(f"[중단] --max-hours {a.max_hours} 경과. "
                  f"미수집 {res.get('missing_after')}건 남음. 다시 실행하면 이어받는다.")
            return 0

        wait = retry_after_seconds() or a.interval_minutes * 60
        nxt = dt.datetime.now() + dt.timedelta(seconds=wait)
        src = "Retry-After 헤더" if retry_after_seconds() else "기본 간격"
        print(f"    다음 확인 {nxt:%H:%M:%S} ({wait // 60}분 후, {src})")
        time.sleep(wait)


if __name__ == "__main__":
    raise SystemExit(main())
