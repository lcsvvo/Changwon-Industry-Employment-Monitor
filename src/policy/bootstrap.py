"""검증된 정책 원장의 배포 seed.

DB가 단일 조회 원장이다. 이 모듈은 새 DB에 안정적인 ID를 최초 적재할 뿐 기존 행을
덮어쓰지 않는다. 동적 접수상태는 후속 검증 migration/관리 절차로 갱신한다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from sqlalchemy import select

from workflow import models as M

ROOT = Path(__file__).resolve().parents[2]
VERIFIED = "2026-09-22"

URLS = {
    "D01": "https://m.work24.go.kr/cm/c/f/1100/selecSystInfo.do?systId=SI00000357",
    "D02": "https://m.work24.go.kr/hr/h/a/1100/selectIssuGudn.do",
    "D03": "https://gnhrd.or.kr/bbs/content.php?co_id=biz04",
    "D04": "https://m.work24.go.kr/wk/u/a/1000/seniorCenterSvcInfo.do",
    "D05": "https://www.moel.go.kr/faq/faqView.do?seqRepeat=3",
    "D06": "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000117943",
    "D07": "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000124702&target=PR",
    "D08": "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126553",
    "D09": "https://mss.go.kr/site/gyeongnam/ex/bbs/View.do?bcIdx=1066580&cbIdx=255",
    "D10": "https://gnhrd.or.kr/bbs/content.php?co_id=biz_trans",
    "D11": "https://www.moel.go.kr/news/notice/noticeView.do?bbs_seq=20260200837",
    "D12": "https://gnhrd.or.kr/bbs/board.php?bo_table=bus0403&wr_id=38",
    "D13": "https://www.gntp.or.kr/biz/applyInfo/3817",
}

PDF09 = "2026년_중소기업_밀집지역_위기대응_체계_구축사업_상반기_Stand-up_맞춤지원_공고.pdf"
PDF11 = "2026년 산업일자리전환 지원금 시행지침.pdf"


def _hash(path: str | None) -> str | None:
    if not path:
        return None
    p = ROOT / path
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


DOCS = [
    ("D01", "고용유지지원금", "고용24", "OFFICIAL_GUIDANCE", ["employment_retention"], "OPEN", "LIMITED", "RAG_READY_WITH_CAVEAT", "CANDIDATE", "유급·무급 유형별 요건과 금액을 신청 전 재확인", None, None, None),
    ("D02", "국민내일배움카드 발급안내", "고용24", "OFFICIAL_GUIDANCE", ["vocational_training"], "OPEN", "LIMITED", "RAG_READY_WITH_CAVEAT", "CANDIDATE", "카드 발급은 개별 과정 개설·접수를 보장하지 않음", None, None, None),
    ("D03", "산업구조변화대응 등 특화훈련", "경남지역인적자원개발위원회", "OFFICIAL_PROGRAM", ["vocational_training"], "NOT_APPLICABLE", "LIMITED", "RAG_READY_WITH_CAVEAT", "CANDIDATE", "위원회 공급기관 모집과 개인 과정 모집을 구분", None, None, None),
    ("D04", "중장년내일센터 서비스", "고용24", "OFFICIAL_GUIDANCE", ["reemployment"], "OPEN", "LIMITED", "RAG_READY_WITH_CAVEAT", "CANDIDATE", "40세 이상, 단계별 서비스 확인", None, None, None),
    ("D05", "인터넷 구인신청 방법", "고용노동부", "OFFICIAL_GUIDANCE", ["recruitment_matching"], "OPEN", "GENERAL", "RAG_READY", "NOT_APPLICABLE", "지원요건 카드가 아닌 신청절차 FAQ", None, None, None),
    ("D06", "2026 창원기업지원단 단기컨설팅", "창원산업진흥원", "OFFICIAL_PROGRAM", ["business_difficulty"], "CLOSED", "LIMITED", "RAG_READY_WITH_CAVEAT", "HISTORICAL_ONLY", "과거 회차, 현재 신청 유도 금지", "2026-01-28", None, None),
    ("D07", "2026 Quick Solution 5차", "경남테크노파크", "OFFICIAL_PROGRAM", ["business_difficulty"], "CLOSED", "LIMITED", "RAG_READY_WITH_CAVEAT", "HISTORICAL_ONLY", "과거 회차, 후속 회차 미확인", "2026-07-24", "2026-07-23", "2026-08-12"),
    ("D08", "2026 경남형 스마트공장 컨설팅 추가모집", "경남테크노파크", "OFFICIAL_PROGRAM", ["technology_transition"], "OPEN", "LIMITED", "RAG_READY_WITH_CAVEAT", "CANDIDATE", "스마트제조 한정, 대상 기업 심사 별도", "2026-09-17", "2026-09-15", "2026-10-08"),
    ("D09", "2026 상반기 Stand-up 맞춤지원", "경남테크노파크", "OFFICIAL_PROGRAM", ["crisis_response"], "CLOSED", "LIMITED", "RAG_READY_WITH_CAVEAT", "HISTORICAL_ONLY", "상반기 창원 대상은 마산진북농공단지·상복일반산업단지·진해죽곡일반산업단지이며 창원국가산업단지는 명단에 없음", "2026-03-23", "2026-03-23", None),
    ("D10", "2026 경남 산업·일자리 전환 컨설팅", "경남지역인적자원개발위원회", "OFFICIAL_PROGRAM", ["vocational_training", "employment_retention"], "OPEN", "LIMITED", "RAG_READY_WITH_CAVEAT", "CANDIDATE", "수시 신청이나 사업비 마감 시 종료; 잔여예산·잔여 모집기업 수 재확인", "2026-04-10", "2026-04-01", "2026-11-30"),
    ("D11", "2026 산업·일자리전환 지원금 시행지침", "고용노동부", "OFFICIAL_POLICY", ["recruitment_matching", "vocational_training", "employment_retention"], "UNKNOWN", "LIMITED", "RAG_READY_WITH_CAVEAT", "CANDIDATE", "현재 예산·접수 지속 여부 재확인; D10 참여만으로 자동 적격·승인·지급 아님", "2026-02-19", "2026-01-01", None),
    ("D12", "2026년 7~9월 산대특 훈련과정 개설 일정", "경남지역인적자원개발위원회", "OFFICIAL_GUIDANCE", ["vocational_training"], "UNKNOWN", "LIMITED", "RAG_READY_WITH_CAVEAT", "NOT_APPLICABLE", "과정별 잔여석·접수마감 재확인; 정적 카드 금지", "2026-06-29", None, None),
    ("D13", "2026 하반기 Stand-up 맞춤지원", "경남테크노파크", "OFFICIAL_PROGRAM", ["crisis_response"], "CLOSED", "LIMITED", "RAG_READY_WITH_CAVEAT", "HISTORICAL_ONLY", "하반기 별첨 대상지역 전문 미대조; 지역별 자동 자격판정 금지", "2026-07-31", "2026-07-31", "2026-08-14"),
]


def _document_rows():
    rows = []
    for did, title, inst, cls, tags, intake, scope, rag, card, caveat, eff, start, end in DOCS:
        if did == "D09":
            local, dtype, extraction = PDF09, "PDF", "ATTACHMENT_VERIFIED"
        elif did == "D11":
            local, dtype, extraction = PDF11, "PDF", "ATTACHMENT_VERIFIED"
        else:
            local, dtype, extraction = f"LLM/sources/official/{did}.html", "HTML", "HTML_BODY"
        rows.append(dict(document_id=did, title=title, institution=inst, source_class=cls,
                         function_tag=tags, source_url=URLS[did], document_type=dtype,
                         original_filename=Path(local).name, local_path=local, file_hash=_hash(local),
                         effective_date=eff, valid_from=start, valid_to=end, verified_at=VERIFIED,
                         evidence_level="OFFICIAL_VERIFIED", content_extraction_scope=extraction,
                         current_intake_status=intake, scope_status=scope, rag_status=rag,
                         requirement_card_status=card, intake_url=(
                             "https://docs.google.com/forms/d/1d26uAG7lym3DqVtWRWeb7BGOQN9LY2-WN4Yqw1UCc_w/viewform?edit_requested=true"
                             if did == "D10" else None),
                         contact=("055-263-0282 / jyjoung@gnrsc.or.kr" if did == "D10" else None),
                         contact_role=("사업 전용 문의" if did == "D10" else None), caveat=caveat,
                         rag_scope="OFFICIAL", official=True,
                         reverification_required=did in {"D08", "D10", "D11", "D12"}))
    team_path = "LLM/LLM_AI_v3.html"
    rows.append(dict(document_id="TEAM01", title="창원국가산단 산업·고용 전환진단 정책 제안 최종안",
                     institution="프로젝트 팀", source_class="TEAM_PROPOSAL", function_tag=["policy_idea"],
                     source_url=team_path, document_type="HTML", original_filename=Path(team_path).name,
                     local_path=team_path, file_hash=_hash(team_path), effective_date=None, valid_from=None,
                     valid_to=None, verified_at=VERIFIED, evidence_level="TEAM_AUTHORED",
                     content_extraction_scope="HTML_BODY", current_intake_status="NOT_APPLICABLE",
                     scope_status="LIMITED", rag_status="RAG_READY", requirement_card_status="NOT_APPLICABLE",
                     intake_url=None, contact=None, contact_role=None,
                     caveat="팀 제안이며 공식 지원사업이 아님", rag_scope="POLICY_IDEA_ONLY",
                     official=False, reverification_required=False))
    return rows


CARDS = [
    ("R01", "D01", "employment_retention", "고용유지지원금", "고용조정이 불가피한 사업주", "유급·무급별 별도 기준", "휴업·휴직 등에 따른 일부 지원", "사전 계획 신고·기한 내 신청", "상시 안내", "OPEN", "고용24/관할 고용센터", None, None, "유형별 금액·매출요건 재확인, 개별 자격 미판정", "CANDIDATE"),
    ("R02", "D02", "vocational_training", "국민내일배움카드", "직업훈련이 필요한 사람", "카드 제외대상 확인", "카드 발급·훈련 지원", "과정별 자부담·일정 상이", "카드 상시 안내", "OPEN", "고용24/센터", None, "140시간 이상 과정은 상담 필요", "과정 모집 보장 아님", "CANDIDATE"),
    ("R03", "D03", "vocational_training", "산업구조변화대응 등 특화훈련", "내일배움카드 발급 가능 훈련생", "과정별 대상 확인", "지역 맞춤 산대특 과정", "개인 수강은 훈련기관/고용24", "과정별 확인", "NOT_APPLICABLE", "훈련기관/고용24", None, None, "공급기관 공고와 개인 모집 구분", "CANDIDATE"),
    ("R04", "D04", "reemployment", "중장년내일센터 서비스", "40세 이상 재직·퇴직 근로자", "단계별 프로그램 확인", "생애경력설계·전직스쿨·재도약/상담", None, "상시 서비스", "OPEN", "고용24 구직신청 후 서비스", None, "40세 이상", "국민취업지원제도와 동일 서비스로 취급 금지", "CANDIDATE"),
    ("R06", "D06", "business_difficulty", "창원기업지원단 단기컨설팅", "창원 본사/공장 제조 중소기업", None, "현장애로 단기컨설팅 최대 3회·기업당 최대 90만원(당시)", None, "예산 소진시까지였으나 종료", "CLOSED", "과거 진흥원 온라인 접수", None, "창원 제조 중소기업", "과거 회차, 현재 신청 유도 금지", "HISTORICAL_ONLY"),
    ("R07", "D07", "business_difficulty", "Quick Solution 5차", "경남 사업장 중소기업", "공고상 주력산업 연관", "기술닥터/이노카페 심층상담", None, "2026-07-23~2026-08-12", "CLOSED", "당시 경남TP 온라인", None, "공고상 범위", "과거 회차, 새 회차 미확인", "HISTORICAL_ONLY"),
    ("R08", "D08", "technology_transition", "경남형 스마트공장 컨설팅", "공고의 경남 중소·중견기업 유형", None, "공정분석·전문가 매칭·로드맵", "대상 기업 심사", "2026-09-15~2026-10-08", "OPEN", "스마트공장 사업관리시스템", "https://www.smart-factory.kr/", "스마트제조 한정", "적격심사 별도", "CANDIDATE"),
    ("R09", "D09", "crisis_response", "상반기 Stand-up 맞춤지원", "상반기 지정 30개 밀집지역 소재 중소기업", "기업별 실제 소재지 확인", "Tech-UP/Biz-UP, 기업당 최대 1,000만원·최대 3개월", "현장실사", "2026-03-23~상반기 예산 소진", "CLOSED", "당시 경남TP 온라인", None, "창원 3개 대상지역", "창원국가산단은 명단에 없음; 과거 회차", "HISTORICAL_ONLY"),
    ("R10", "D10", "vocational_training", "경남 산업·일자리 전환 컨설팅", "산업전환으로 직무전환·역량강화 등이 필요한 기업", "총 60개사 모집 범위", "무료 30시간 기본진단·심화·사후관리", "D11 검토 연계 가능", "2026년 4~11월 수시", "OPEN", "Google Form", "https://docs.google.com/forms/d/1d26uAG7lym3DqVtWRWeb7BGOQN9LY2-WN4Yqw1UCc_w/viewform?edit_requested=true", "기업 대상", "사업비 마감 시 종료; 잔여예산·잔여기업 수 재확인", "CANDIDATE"),
    ("R11-A", "D11", "recruitment_matching", "산업·일자리전환 채용장려금", "유형Ⅰ·Ⅱ 대상 사업주", "지역·업종·컨설팅·탄소중립·기업규모 등 세부요건", "1인당 월 최대 60만원, 연 최대 720만원", "신규채용·재고용 후 6개월 이상 유지", "참여신청 연중 수시; 지급기한 별도", "UNKNOWN", "관할 고용센터 기업지원부서", None, "사업주별 지원인원 한도", "D10 참여만으로 자동 적격·승인·지급 아님; 예산 재확인", "CANDIDATE"),
    ("R11-B", "D11", "vocational_training", "산업·일자리전환 훈련지원금", "지침상 대상 사업주", "최근 3년 컨설팅 등 복수 경로와 제외요건", "훈련비 1인 최대 300만원; 장려금 1일 10만원·월 200만원·총 300만원", "계획 승인 후 실시; 우선지원기업 근로자별 20시간 이상 등", "훈련 종료 후 6개월 이내 신청", "UNKNOWN", "관할 고용센터 기업지원부서", None, "직무 관련성·시간·대상 심사", "현재 예산·접수 지속 여부 재확인", "CANDIDATE"),
]

PROPOSALS = [
    ("P01", 1, "산업·고용 조기경보 정례협의체", "운영체계 개선", "분기 신호·현장확인·기관연계 정례화", "위험업종 후보", "정례회의·임시회의·업무 프로토콜", "점검 횟수·현장확인 비율·연계 소요기간·공동 대응 건수", "상설조직 신설·자동 지원대상 선정 아님"),
    ("P02", 2, "경남형 버팀이음 다음 회차 재설계", "기존사업 고도화 제안", "숙련 유지", "기존 대상과 실제 위기 신호 비교", "대상·지급·접수 개선", "신청률·소진율·6/12개월 유지·미신청 사유", "현 회차 공식 요건 아님"),
    ("P03", 3, "산업전환 직무전환·재취업 패키지", "기존 제도 고도화 제안", "지역 내 전직", "고용감소 업종 재직·이직·퇴직자", "훈련·자격·상담·채용매칭", "수료율·취업률·6개월 유지율·지역 내 재취업", "개인 자격·사업 재원 별도 확인"),
    ("P04", 4, "산업전환 기업 조기진단 프로그램", "신규 제안", "산업 신호에서 기업별 현장진단", "우선점검 업종 내 확인 필요 기업", "간이·심층진단과 유형별 처방", "진단기업 수·지원연계율·고용·매출·수주 변화", "모델 점수로 기업 선정·탈락 금지"),
    ("P05", 5, "원청-협력사 공동 산업전환 프로그램", "신규 제안", "기술·직무 수요와 협력사 전환 연결", "원청·협력사", "공동 교육·프로젝트·공정개선", "원청/협력사 수·이수자·공정개선·후속 수주/채용", "공식 열린 사업으로 표기 금지"),
    ("P06", 6, "위기기업 고용유지·근로환경 개선 패키지", "기존사업 연계·확장 제안", "고용유지·채용과 환경개선 연결", "위기 신호와 계획이 있는 영세·중소 협력사", "안전·휴게·교육·작업환경", "유지·채용 인원·개선기업·이직률·6개월 유지", "사업비·선정기준·시행 여부 미확정"),
    ("P07", 7, "방산·항공 협력사 패키지 단계적 확대", "기존사업 확장 제안", "기존 범위 확인 후 확대 검토", "비방산 기계·소재 협력사", "숙련유지·교육·공정개선", "확대 기업 수·고용유지율·사업전환·공정개선", "현재 공식 확대 결정 아님"),
    ("P08", None, "산업전환 직무전환 바우처", "조건부 보조 제안", "추가 예산 시 직무 이동", "기존 제조인력", "교육비·자격증·훈련비", None, "P03 세부 수단 시범; 독립 현금지원 확정 아님"),
]


def seed_policy_master(Session) -> None:
    with Session.begin() as s:
        for row in _document_rows():
            if s.get(M.DocumentMaster, row["document_id"]) is None:
                s.add(M.DocumentMaster(**row))
        route_url = "https://www.moel.go.kr/minwon/rigion/rigion_C3.do"
        for district, inst in (("의창구", "창원고용센터"), ("성산구", "창원고용센터"),
                               ("진해구", "창원고용센터"), ("마산회원구", "마산고용센터"),
                               ("마산합포구", "마산고용센터")):
            if s.get(M.JurisdictionRule, district) is None:
                s.add(M.JurisdictionRule(district=district, institution=inst, source_url=route_url,
                                         verified_at="2026-09-21", status="MATCHED"))
        for req_id, doc_id, tag, title, target, eligibility, support, requirements, period, status, method, intake_url, scope, caveat, card_status in CARDS:
            if s.scalar(select(M.RequirementCard).where(M.RequirementCard.requirement_id == req_id)) is None:
                s.add(M.RequirementCard(requirement_id=req_id, document_id=doc_id, function_tag=tag,
                    institution=next(d[2] for d in DOCS if d[0] == doc_id), program_name=title, title=title,
                    target=target, eligibility=eligibility, support_content=support, requirements=requirements,
                    application_period=period, current_intake_status=status, application_method=method,
                    intake_url=intake_url, contact=("055-263-0282 / jyjoung@gnrsc.or.kr" if req_id == "R10" else None),
                    effective_date=next(d[10] for d in DOCS if d[0] == doc_id), official_source_url=URLS[doc_id],
                    source_document=doc_id, scope_note=scope, caveat=caveat, card_status=card_status,
                    evidence_url=URLS[doc_id], valid_from=next(d[11] for d in DOCS if d[0] == doc_id),
                    valid_to=next(d[12] for d in DOCS if d[0] == doc_id), verified_at=VERIFIED,
                    registered_by="policy-contract/2026-09-22", auto_eligibility=False,
                    reverification_required=status in {"OPEN", "UNKNOWN"}, last_verified_at=VERIFIED))
        for pid, priority, title, ptype, purpose, target, support, kpi, caveat in PROPOSALS:
            if s.get(M.TeamProposal, pid) is None:
                s.add(M.TeamProposal(proposal_id=pid, document_id="TEAM01", priority=priority,
                    priority_type="TEAM_PROPOSAL_PRIORITY", title=title, proposal_type=ptype,
                    purpose=purpose, target=target, support_content=support, kpi=kpi, caveat=caveat,
                    source_class="TEAM_PROPOSAL", official=False, rag_scope="POLICY_IDEA_ONLY"))
        if s.scalar(select(M.RelatedDocument).where(M.RelatedDocument.from_document_id == "D10",
                                                    M.RelatedDocument.to_document_id == "D11")) is None:
            s.add(M.RelatedDocument(from_document_id="D10", to_document_id="D11",
                relation="검토 가능 경로", equivalent_program=False, auto_eligibility=False,
                caveat="D10 참여는 D11 검토 경로 중 하나일 뿐 자동 적격·신청·승인·지급이 아니다."))
        institution_rows = [
            dict(institution_id="GNHRD-D10", institution="경남지역인적자원개발위원회", unit=None,
                 function_tag="vocational_training", function_verified=True, intake_path_verified=True,
                 current_intake_status="OPEN", scope_status="LIMITED", jurisdiction_status="NOT_APPLICABLE",
                 source_status="OFFICIAL_VERIFIED", intake_type="Google Form",
                 intake_url="https://docs.google.com/forms/d/1d26uAG7lym3DqVtWRWeb7BGOQN9LY2-WN4Yqw1UCc_w/viewform?edit_requested=true",
                 phone="055-263-0282", email="jyjoung@gnrsc.or.kr", contact_role="사업 전용 문의",
                 source_url=URLS["D10"], verified_at=VERIFIED,
                 caveat="사업비 마감 시 종료; 잔여예산·잔여 모집기업 수 재확인"),
            dict(institution_id="CW-EMPLOYMENT", institution="창원고용센터", unit="기업지원부서",
                 function_tag="employment_retention", function_verified=True, intake_path_verified=False,
                 current_intake_status="UNKNOWN", scope_status="GENERAL", jurisdiction_status="MATCHED",
                 source_status="OFFICIAL_VERIFIED", intake_type="문의 후 확인", intake_url=None,
                 phone="1350", email=None, contact_role="고용노동 상담",
                 source_url="https://www.moel.go.kr/minwon/rigion/rigion_C3.do", verified_at="2026-09-21",
                 caveat="사업장 주소와 사업별 접수창구를 담당자가 재확인"),
            dict(institution_id="MASAN-EMPLOYMENT", institution="마산고용센터", unit=None,
                 function_tag="employment_retention", function_verified=True, intake_path_verified=False,
                 current_intake_status="UNKNOWN", scope_status="GENERAL", jurisdiction_status="MATCHED",
                 source_status="OFFICIAL_VERIFIED", intake_type="대표 문의", intake_url=None,
                 phone="055-259-1500 / 1350", email=None, contact_role="대표·고용노동 상담",
                 source_url="https://www.moel.go.kr/minwon/rigion/rigion_C3.do", verified_at="2026-09-21",
                 caveat="고용유지 전용 담당부서·직통번호는 공식 확인되지 않음"),
        ]
        for row in institution_rows:
            if s.get(M.InstitutionMaster, row["institution_id"]) is None:
                s.add(M.InstitutionMaster(**row))
