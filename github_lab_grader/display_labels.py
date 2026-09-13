"""기계 판정 코드를 운영자가 읽을 수 있는 한국어로 표현한다.

이 모듈은 표시 전용이다. enum, canonical record, 점수 판정에는 관여하지 않는다.
"""

from __future__ import annotations

from enum import Enum


LABELS: dict[str, str] = {
    # 공통 판정
    "PASS": "정상 수행", "FAIL": "채점 조건 미충족", "PARTIAL": "부분 충족",
    "MANUAL_REVIEW": "수동 확인 필요", "UNVERIFIABLE": "자동 판정 불가",
    "ERROR": "기술적 오류", "ACTIVE": "활성", "MISSING": "없음",
    "UNKNOWN": "확인 불가", "COMPLETE": "완료", "INCOMPLETE": "미완료",
    "NOT_CHECKED": "확인하지 않음", "SATISFIED": "충족",
    # 제출 상태와 근거
    "ON_TIME": "마감 내 제출", "EXTENDED_ON_TIME": "연장 마감 내 제출",
    "LATE": "지각 제출", "NOT_SUBMITTED": "인정 가능한 제출 이력 없음",
    "EVIDENCE_NOT_SETTLED": "제출 증거 확정 대기", "AMBIGUOUS_SUBMISSION": "제출 증거 상충",
    "CONFIGURATION_ERROR": "설정 오류", "MISSING_REPOSITORY_INFO": "GitHub 저장소 정보 미등록",
    "EMPTY_REPOSITORY": "GitHub 저장소가 비어 있음", "NO_TIMELY_SUBMISSION": "마감 내 제출 이력 없음",
    "LATE_SUBMISSION": "마감 이후 제출", "HISTORICAL_EVIDENCE_UNAVAILABLE": "마감 시점 제출 이력 확인 불가",
    "PUSH_EVENT_CONFIRMED": "Push 기록으로 제출 확인",
    "COMMIT_HISTORY_CONFIRMED": "Commit 이력으로 제출 확인",
    "INSUFFICIENT_EVIDENCE": "제출 근거 부족", "PUSH_EVENT": "PushEvent",
    "COMMIT_HISTORY": "Commit 이력", "PUSH_EVENT_CREATED_AT": "PushEvent 생성 시각",
    "COMMIT_COMMITTER_DATE": "Commit committer 시각",
    # README와 collaborator
    "README_MISSING": "README.md 누락", "ROOT_README_MISSING": "루트 README.md 누락",
    "PROJECT_README_MISSING": "실습 프로젝트 README.md 누락",
    "ASSISTANT_COLLABORATOR_MISSING": "조교 Collaborator 미등록",
    "PROFESSOR_COLLABORATOR_MISSING": "담당교수 Collaborator 미등록",
    # Week 02 component 사유
    "PROJECT_MISSING": "프로젝트 폴더를 찾을 수 없음",
    "NO_RELEVANT_SOURCE": "채점 가능한 C 소스 파일을 찾을 수 없음",
    "CORE_BEHAVIOR_INCORRECT": "실습의 핵심 기능이 올바르게 구현되지 않음",
    "MAX_VALUE_INCORRECT": "최댓값 계산이 올바르지 않음",
    "MIN_VALUE_INCORRECT": "최솟값 계산이 올바르지 않음",
    "NEGATIVE_COUNT_INCORRECT": "음수 개수 계산이 올바르지 않음",
    "POSITIVE_SUM_INCORRECT": "양수 합계 계산이 올바르지 않음",
    "POSITIVE_AVERAGE_INCORRECT": "양수 평균 계산이 올바르지 않음",
    "POSITIVE_SUM_AVERAGE_INCORRECT": "양수의 합계 또는 평균 계산이 올바르지 않음",
    "ZERO_POSITIVE_CASE_UNHANDLED": "양수가 없는 경우의 예외 처리가 없음",
    "MAX_INDEX_INCORRECT": "최댓값 인덱스 계산이 올바르지 않음",
    "MIN_INDEX_INCORRECT": "최솟값 인덱스 계산이 올바르지 않음",
    "FIRST_MATCH_RULE_INCORRECT": "동일한 극값 중 첫 번째 인덱스를 반환하지 않음",
    "ARRAY_AVERAGE_INCORRECT": "배열 평균 계산이 올바르지 않음",
    "AVERAGE_CALCULATION_INCORRECT": "배열 평균 계산이 올바르지 않음",
    "MAE_CALCULATION_INCORRECT": "평균 절대 오차(MAE) 계산이 올바르지 않음",
    "SOURCE_UNREADABLE": "소스 파일을 정상적으로 읽을 수 없음",
    "CHECKER_ERROR": "자동 채점기 내부 오류",
    "EXECUTION_UNAVAILABLE": "프로그램 실행 검증 불가",
    "GRADER_ENVIRONMENT_FAILURE": "채점 환경에서 실행 검증 불가",
    "STUDENT_SOURCE_COMPILE_FAILURE": "학생 제출 소스의 컴파일 실패 확인",
    "STUDENT_SOURCE_RUNTIME_FAILURE": "학생 프로그램 실행 중 오류 발생",
    "COMPUTATION_UNVERIFIABLE": "계산 로직을 자동으로 확정할 수 없음",
    "POINTER_USAGE_UNVERIFIABLE": "포인터 사용 조건을 자동으로 확정할 수 없음",
    "UNSUPPORTED_PLAUSIBLE_IMPLEMENTATION": "지원하지 않는 구현 형태로 수동 확인 필요",
    "HARDCODED_OUTPUT": "계산 없이 결과를 고정 출력함",
    "PDF_3_4_ERRATUM_RELATED": "실습 자료 정정 사항 관련 수동 확인 필요",
    "WEEK2_MANUAL_REVIEW_REQUIRED": "2주차 수동 확인 필요",
    # API 오류
    "AUTH_ERROR": "GitHub 인증 오류", "PERMISSION_ERROR": "GitHub 접근 권한 오류",
    "NOT_FOUND": "등록된 GitHub 저장소를 찾을 수 없음", "RATE_LIMITED": "GitHub API 요청 한도 초과",
    "NETWORK_ERROR": "네트워크 오류", "TIMEOUT": "GitHub 응답 시간 초과",
    "API_ERROR": "GitHub API 오류", "INVALID_RESPONSE": "GitHub 응답 형식 오류",
    "UNRESOLVABLE_REF": "Git 참조를 확인할 수 없음",
    # 출처와 운영 상태
    "AUTOMATIC": "자동채점", "MANUAL_ADJUSTMENT": "수동 점수 조정",
    "MANUAL_OVERRIDE": "수동 예외 적용", "PRESERVE_PREVIOUS_CANONICAL_RESULT": "이전 canonical 결과 유지",
    "RECORDED": "기록됨", "RECORD_MISSING": "canonical 기록 없음",
    "FUTURE_WEEK": "미채점 주차", "REVIEW_REQUIRED": "검토 필요",
    "BLOCKER": "차단", "WARNING": "경고", "INFO": "정보",
    # 설정 enum과 도구 식별자도 운영 화면에 노출될 수 있다.
    "ANY": "하나 이상", "BINARY": "이진 채점", "IDENTITY_PARTIAL": "신원 정보 부분점수",
    "COMPONENT_SUM": "실습별 점수 합산", "SECOND": "초 단위", "MINUTE": "분 단위",
    "EXPLICIT": "명시 설정", "NEXT_WEEK_DERIVED": "다음 주차에서 자동 계산", "UNAVAILABLE": "사용 불가",
    "MAX_VALUE": "최댓값", "MIN_VALUE": "최솟값", "NEGATIVE_COUNT": "음수 개수",
    "POSITIVE_SUM_AVERAGE": "양수 합계와 평균", "MAX_INDEX_FIRST": "첫 최댓값 인덱스",
    "MIN_INDEX_FIRST": "첫 최솟값 인덱스", "ARRAY_COMPARE_MAE": "배열 비교와 MAE",
    "MSVC": "Microsoft C 컴파일러", "CLANG": "Clang C 컴파일러", "GCC": "GCC C 컴파일러",
    "ENVIRONMENT": "환경 변수 인증", "DOTENV": ".env 인증", "GITHUB_CLI": "GitHub CLI 인증",
    # Preflight 항목
    "CONFIG_MISSING": "설정 파일 없음", "CONFIG_INVALID": "설정 파일 오류",
    "ROSTER_MISSING": "학생 명단 없음", "ROSTER_INVALID": "학생 명단 오류",
    "SECTION_UNKNOWN": "알 수 없는 분반", "RUBRIC_MISSING": "Rubric 없음",
    "RUBRIC_INVALID": "Rubric 오류", "RUBRIC_SECTION_MISSING": "Rubric 분반 설정 없음",
    "LATE_WINDOW_UNRESOLVED": "지각 제출 종료 시각 미확정", "TIMING_INVALID": "제출 시각 설정 오류",
    "AUTH_UNAVAILABLE": "GitHub 인증 사용 불가", "AUTH_AVAILABLE": "GitHub 인증 확인",
    "STUDENT_COUNT": "분반 학생 수", "REGISTERED_COUNT": "GitHub 저장소 등록 수",
    "EFFECTIVE_DEADLINE": "적용 마감", "DEADLINE_NOTE": "마감 안내",
    "SCORING_MODE": "채점 방식", "DEADLINE_RESOLUTION": "마감 비교 단위",
    "GRADING_COMPONENTS": "채점 실습 구성", "C_TOOLCHAIN_AVAILABLE": "C 도구 체인 사용 가능",
    "C_TOOLCHAIN_UNAVAILABLE": "C 도구 체인 사용 불가", "SETTLE_TIME": "증거 안정화 시각",
    "SUBMISSION_START_BOUNDARY": "제출 시작 경계", "SUBMISSION_BRANCH_POLICY": "제출 branch 정책",
    "SUBMISSION_EVIDENCE_SOURCES": "허용 제출 증거", "REQUIRED_COLLABORATORS": "필수 Collaborator",
    "REQUIRED_PATH_GROUPS": "필수 제출 경로", "OPERATOR_CONFIRMATION_REQUIRED": "운영자 확인 필요",
    "OPERATOR_CONFIRMATION_COMPLETE": "운영자 확인 완료", "LATE_WINDOW_NOT_REQUIRED": "지각 제출 구간 미사용",
    "MANUAL_OVERRIDES_TRACKED": "비공개 수동 예외 파일 추적됨",
    "MANUAL_ADJUSTMENTS_INVALID": "수동 점수 조정 파일 오류", "MANUAL_OVERRIDES_INVALID": "수동 예외 파일 오류",
    "MANUAL_OVERRIDE_STUDENT_MISSING": "수동 예외 학생 없음",
    "MANUAL_OVERRIDE_SOURCE_UNRESOLVED": "수동 예외 원본 결과 미확정",
    "MANUAL_OVERRIDE_SOURCE_STUDENT_MISSING": "이전 기록에 수동 예외 학생 없음",
    "MANUAL_OVERRIDE_SOURCE_MISSING": "수동 예외 원본 기록 없음",
    "MANUAL_OVERRIDE_SOURCE_INVALID": "수동 예외 원본 기록 오류",
    # 저장·보고 계층에서 CLI로 전달되는 오류 코드
    "ARCHIVE_COLLISION": "보관 기록 경로 충돌", "ARCHIVE_WRITE_FAILED": "보관 기록 저장 실패",
    "ATOMIC_WRITE_FAILED": "기록 원자적 저장 실패", "CORRUPTED_RECORD": "canonical 기록 손상",
    "DUPLICATE_RECORD": "canonical 기록 중복", "RECORD_ALREADY_EXISTS": "canonical 기록이 이미 존재함",
    "RECORD_NOT_FOUND": "canonical 기록을 찾을 수 없음", "RECORD_SECURITY_ERROR": "기록 경로 보안 검사 실패",
    "UNSAFE_RECORD_PATH": "안전하지 않은 기록 경로", "UNSUPPORTED_SCHEMA": "지원하지 않는 기록 schema",
    "CANONICAL_STUDENT_NOT_IN_ROSTER": "canonical 학생이 현재 명단에 없음",
    "IDENTITY_MISMATCH": "학생 식별 정보 불일치", "MAX_SCORE_MISMATCH": "최대 점수 불일치",
    "OUTPUT_FILE_LOCKED": "출력 파일이 사용 중", "OUTPUT_SECURITY_ERROR": "출력 경로 보안 검사 실패",
    "REPORT_INPUT_ERROR": "보고서 입력 오류", "REPORT_WRITE_ERROR": "보고서 저장 실패",
    "SHEET_NAME_COLLISION": "Excel sheet 이름 충돌", "UNSAFE_OUTPUT_PATH": "안전하지 않은 출력 경로",
    "COMPUTED": "계산 로직 확인", "NOT_ENFORCED": "적용하지 않음",
    # 수동 검토 workbook
    "CANONICAL_RECORD_REQUIRED": "수동 검토 보고서를 만들기 위한 채점 기록이 없음",
    "MALFORMED_REVIEW_WORKBOOK": "수동 검토 workbook 형식 오류",
    "INVALID_REVIEW_IDENTITY": "수동 검토 대상 식별 정보 오류",
    "INVALID_MANUAL_SCORE": "해당 주차에서 허용되지 않는 수동 점수",
    "MANUAL_ADJUSTMENT_REASON_REQUIRED": "수동조정 사유 필요",
    "DUPLICATE_REVIEW_DECISION": "같은 학생의 수동 결정 중복",
    "MANUAL_ADJUSTMENT_CONFLICT": "기존 수동 점수 조정과 충돌",
    "FORMULA_INPUT_REJECTED": "수식 입력은 수동 결정으로 사용할 수 없음",
}


def _code(value: object | None) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return "UNAVAILABLE" if value is None or value == "" else str(value)


def format_display_label(value: object | None, *, unknown_label: str = "알 수 없는 판정 사유") -> str:
    """원본 코드를 보존하면서 안전한 한국어 표시 문자열을 반환한다."""
    code = _code(value)
    return f"{LABELS.get(code, unknown_label)} ({code})"


def format_component_status(value: object | None) -> str:
    code = _code(value)
    labels = {"PASS": "정상", "FAIL": "미충족", "UNVERIFIABLE": "수동 확인 필요"}
    return f"{labels.get(code, LABELS.get(code, '알 수 없는 판정'))} ({code})"


def korean_label(value: object | None, *, unknown_label: str = "알 수 없는 판정 사유") -> str:
    """Excel의 설명 열처럼 코드가 별도 보존되는 곳에 한국어만 반환한다."""
    return LABELS.get(_code(value), unknown_label)
