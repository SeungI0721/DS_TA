# Data Structures GitHub Lab Grader

Data Structures 실습 과목의 GitHub 제출 증거를 수집하고 주차별 채점 결과를 보존하기 위한 Windows용 Python CLI 프로젝트이다.

현재 저장소는 **Phase 6 gradebook reconstruction과 Excel reporting**까지 구현되어 있다. 검증된 canonical JSON만으로 주차별 통합 workbook과 전체 분반 최종 workbook을 재생성한다. 보고 과정은 GitHub 인증·API·network를 사용하지 않으며 C 실행은 아직 구현하지 않았다.

## 프로젝트 목적

학생이 매주 다른 공용 PC를 사용하더라도 GitHub에 실제로 push한 시점을 기준으로 제출을 확인하고, 분반별 마감과 예외 연장을 일관되게 적용하는 것이 목적이다.

Version 1의 최종 범위는 다음 항목이다.

- rubric에 따른 `PushEvent.created_at` 우선·commit history fallback 제출 증거 확인
- 교수자와 조교의 현재 collaborator 상태 확인
- 선택된 제출 SHA 시점의 rubric 기반 필수 경로 그룹 확인
- rubric이 요구하는 경우 README의 정확한 학번·이름 확인
- 주차별 점수 계산과 불변 JSON 증거 보존
- 분반별 주차 결과와 누적 Excel 성적표 생성
- private manual adjustment 기반의 effective grade 보고

C 소스 검사와 학생 프로그램 실행은 Version 1 범위가 아니다.

## 현재 구현 상태

| 구분 | 현재 상태 |
| --- | --- |
| argparse CLI 명령 및 옵션 | 구현 |
| 학생·마감·PushEvent·채점 결과 데이터 모델 | 구현 |
| timezone-aware 모델 검증 | 구현 |
| 안전한 예시 설정과 개인정보 제외 규칙 | 구현 |
| 인증 provider와 GitHub REST 읽기 client | 구현, mock unit test 검증 |
| repository metadata와 events pagination | 구현, mock unit test 검증 |
| PushEvent 정규화와 event coverage metadata | 구현, mock unit test 검증 |
| collaborator 및 README-at-SHA API method | 구현, mock unit test 검증 |
| 선택적 read-only live smoke test | 구현, 실제 실행은 opt-in |
| typed 설정 loading과 private config 추적 방지 | 구현, unit test 검증 |
| 학생별·section/week 채점 orchestration | 구현, mock integration test 검증 |
| 제출 선택·README identity·순수 점수 결정 | 구현, unit test 검증 |
| 기술적 불확실성의 null/manual-review 보존 | 구현, unit test 검증 |
| 불변 JSON 기록과 regrade archive | 구현, local unit/integration test 검증 |
| Excel 보고서와 누적 성적표 | 구현, fictional XLSX reopen test 검증 |
| Week 1 최종 rubric 구현 | offline 검증 완료, 운영 확인 대기 |

`grade`는 GitHub evidence를 canonical record로 저장한다. `week-report`, `rebuild-gradebook`, `final-report`는 canonical/local 입력만 읽어 Excel을 만들며 GitHub를 다시 호출하지 않는다. Human-approved 예외 점수는 ignored `data/manual_grade_adjustments.csv`에서만 관리하며 canonical JSON을 수정하지 않는다.

## 전체 프로젝트 구조

```text
DS-TA/
├─ README.md
├─ main.py
├─ config.example.json
├─ config.json                 # local only, Git에서 제외
├─ requirements.txt
├─ pytest.ini
├─ .env.example
├─ .gitignore
├─ data/
│  └─ students.example.csv
├─ rubrics/
│  └─ week01.json
├─ github_lab_grader/
│  ├─ __init__.py
│  ├─ auth.py
│  ├─ models.py
│  ├─ config_loader.py
│  ├─ github_client.py
│  ├─ submission_checker.py
│  ├─ collaborator_checker.py
│  ├─ readme_checker.py
│  ├─ grader.py
│  ├─ orchestrator.py
│  ├─ grading_workflow.py
│  ├─ record_store.py
│  ├─ excel_report.py
│  ├─ gradebook.py
│  └─ c_checker.py
└─ tests/
   ├─ conftest.py
   ├─ test_auth.py
   ├─ test_cli.py
   ├─ test_models.py
   ├─ test_example_configuration.py
   ├─ test_config_loader.py
   ├─ test_github_client.py
   ├─ test_live_github.py
   ├─ test_submission_checker.py
   ├─ test_readme_checker.py
   ├─ test_grader.py
   ├─ test_orchestrator.py
   ├─ test_record_store.py
   ├─ phase6_helpers.py
   ├─ test_gradebook.py
   ├─ test_excel_report.py
   └─ test_record_and_gradebook_scaffold.py
```

| 경로 | 설명 |
| --- | --- |
| `main.py` | CLI entry point와 명령 인자 구조 |
| `github_lab_grader/models.py` | 상태 enum과 typed evidence model |
| `github_lab_grader/auth.py` | GitHub CLI, 환경변수, `.env` 순서의 인증 provider |
| `github_lab_grader/github_client.py` | 읽기 전용 GitHub REST client와 오류·재시도 처리 |
| `github_lab_grader/orchestrator.py` | 학생별 evidence acquisition과 section/week 격리 실행 |
| `config.example.json` | 실제 계정이 없는 공개 설정 template |
| `config.json` | 실제 수업 계정을 둘 수 있는 ignored local runtime 설정 |
| `github_lab_grader/c_checker.py` | 실행 기능이 없는 향후 C 채점 placeholder |
| `data/students.example.csv` | 공개 가능한 가상 학생 데이터 형식 |
| `rubrics/week01.json` | 검증 대상 Week 1 채점 정책 |
| `tests/` | 현재 기반 검증과 이후 Phase 동작 명세 |

`config.json`, `records/`, `output/`, `archive/`, `data/students.csv`, `data/manual_grade_adjustments.csv`는 실제 계정·개인정보·성적 자료를 포함할 수 있으므로 저장소에 추적하지 않는다.

## 사용 기술

| 항목 | 현재 코드 기준 |
| --- | --- |
| 운영 환경 | Windows, VS Code |
| Python | 3.11 이상 |
| CLI | Python 표준 라이브러리 `argparse` |
| 데이터 모델 | `dataclasses`, `enum.StrEnum` |
| HTTP | requests |
| 로컬 환경변수 파일 | python-dotenv |
| 테스트 | pytest |

현재 의존성은 `requests`, `python-dotenv`, `openpyxl`, `pytest`이다. `openpyxl`은 local XLSX 생성과 reopen 검증에 사용한다.

## 설치 및 실행 방법

### 실제 사용 Quick Start

일반 운영 절차는 [DS-TA 사용 가이드](docs/USAGE.md), Week 1의 구체적인 채점·증거 절차는 [Week 1 사용 가이드](docs/WEEK1_USAGE.md)를 따른다. VS Code의 `Terminal` → `Run Task`에서 로컬 전용 `DS-TA: Preflight`, `DS-TA: Dry Run`, `DS-TA: REAL Grade Section/Week`, 보고서 및 테스트 Task를 실행할 수 있다.

```text
Preflight → Dry Run → 실제 채점 → canonical JSON → 주간/최종 Excel
```

실제 채점 전에는 반드시 `preflight` 결과의 `BLOCKER`가 없는지 확인한다. `.vscode/` 설정과 실제 수업 데이터는 Git에 포함하지 않는다.

`grade --dry-run`은 점수별 집계, null 원인, 제출 상태와 마감 settle 상태를 출력한다. 필요한 경우에만 `--details`를 추가해 미해결 학생의 최소 식별자와 상태를 확인한다.

채점 방식, 제출 시작 경계, 필수 collaborator, historical SHA의 필수 경로 그룹, README identity 요구, late-window 사용 여부는 주차별 rubric에서 결정한다. Deadline-only rubric은 시작 경계를 적용하지 않고, bounded-window rubric은 설정된 시작 시각 이후의 제출만 사용한다. Week 1의 구체적인 정책은 [Week 1 사용 가이드](docs/WEEK1_USAGE.md)에만 유지하며 이후 주차의 보편 규칙으로 간주하지 않는다.

명령은 저장소 루트에서 Windows PowerShell로 실행한다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
```

PowerShell 실행 정책 때문에 activate script를 사용할 수 없다면 가상환경의 Python을 직접 실행할 수 있다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
```

CLI 인자 구조 확인 예시는 다음과 같다. 실제 채점은 아직 동작하지 않는다.

```powershell
python main.py --help
python main.py grade --week 1 --section 01
python main.py grade --week 1 --all-sections
```

## 설정 파일

새 clone에서는 공개 template을 local runtime 설정으로 복사한다.

```powershell
Copy-Item .\config.example.json .\config.json
```

### `config.example.json`과 `config.json`

두 파일은 학기, 과목, collaborator 계정, timezone, 분반 목록, 전체 주차 수, event settle/retention 정책, 환산 배점, GitHub API version을 같은 schema로 정의한다.

- `sections`는 문자열 목록이며 `01`, `02`처럼 앞자리 0을 보존한다.
- 분반 수를 Python 코드에 고정하지 않는다.
- 추적되는 `config.example.json`에는 fictional account만 둔다.
- 실제 `professor_github`와 `assistant_github`는 ignored local `config.json`에만 입력한다.
- runtime은 `config.json`이 Git index에 추적된 상태면 account 값을 출력하지 않고 `ConfigurationSecurityError`로 처리를 거부한다.
- 모든 수업 시각은 `Asia/Seoul` 기준이다.

`.gitignore`는 이미 추적 중인 파일을 자동으로 제거하지 않는다. `config.json`이 `git ls-files`에 나타나면 실제 계정을 입력하거나 commit하기 전에 index에서 제거해야 한다. 이 규칙은 `config.json`만 대상으로 하며 `rubrics/*.json`은 계속 추적한다.

### `data/students.csv`

실제 운영 파일의 schema는 다음과 같다.

```csv
section,student_id,name,github_id,repository
```

`repository`는 `owner/repository` 형식을 사용한다. 저장소에는 가상 데이터만 포함한 `data/students.example.csv`만 추적하며, 실제 `data/students.csv`는 `.gitignore`로 제외한다.

### `rubrics/weekNN.json`

주차별 제목, 최대 점수, 제출 branch 정책, PushEvent actor 조건, 분반별 마감, 채점 조건을 정의한다. `enforce_submission_branch`가 false이면 모든 정상 브랜치 ref(`refs/heads/...`)를 인정하되 tag ref는 제외하며, true이면 `submission_branch`로 지정한 브랜치만 인정한다.

Tracked rubric은 검증된 주차 정책이며 임의로 교체하지 않는다. 시각은 다음과 같이 UTC offset을 포함한 ISO-8601 형식을 사용한다. 실제 공지가 분 단위라면 rubric의 정확한 cutoff가 어떤 운영 정규화를 사용했는지 `deadline_note`에 남긴다.

```json
"scheduled_deadline": "2026-09-03T23:59:59+09:00"
```

naive timestamp는 허용하지 않는다.

### 인증

인증 provider는 다음 순서로 credential을 탐색한다.

1. 인증된 GitHub CLI session의 `gh auth token`
2. process environment의 `GITHUB_TOKEN`
3. repository root `.env`의 `GITHUB_TOKEN`

GitHub CLI가 없거나 인증되지 않았으면 다음 provider로 안전하게 이동한다. 토큰은 CLI argument로 받지 않으며 repr, 예외 메시지, 로그, JSON 기록에 포함하지 않는다. 로컬 `.env`는 추적하지 않는다.

GitHub REST 요청은 `config.json`의 `github_api_version`과 `github_request` 설정을 사용한다. 현재 version header는 `2026-03-10`이며 connect/read timeout, retry 횟수, backoff, 허용할 최대 `Retry-After`, rate-limit 경고 기준을 한 위치에서 관리한다.

## GitHub REST API 연동

현재 client가 제공하는 읽기 기능은 다음과 같다.

- authenticated user login 확인
- repository ID, full name, 공개 범위, default branch, caller permissions 조회
- `GET /repos/{owner}/{repo}/events`와 `Link` 기반 pagination
- 최대 300개 event, page별 rate-limit, 조회 시각, oldest/newest 시각 보존
- PushEvent의 event ID, actor, `created_at`, ref, head/before SHA, push ID 정규화
- 현재 collaborator 상태 조회
- 명시적 ref의 repository root entry 조회
- 같은 selected SHA를 사용한 root README 탐색과 UTF-8 content 조회
- 같은 selected SHA의 정확한 repository path 여러 개를 한 번에 확인

모든 HTTP 호출은 timeout을 사용한다. 502, 503, 504와 network/timeout 오류는 설정된 횟수 안에서 exponential backoff로 재시도한다. 401, 권한 오류로 확인된 403, 404, 409, 422는 재시도하지 않는다. 403/429 rate limit은 `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`, GitHub 오류 message를 함께 판별한다. 공식 header에서 계산한 대기가 설정된 최대 시간 이내일 때만 제한적으로 재시도하며, 그 밖에는 `RATE_LIMITED` 오류와 metadata를 caller에 반환한다.

오류 분류는 `AUTH_ERROR`, `PERMISSION_ERROR`, `NOT_FOUND`, `RATE_LIMITED`, `NETWORK_ERROR`, `TIMEOUT`, `API_ERROR`, `INVALID_RESPONSE`, `UNRESOLVABLE_REF`를 사용한다. 응답 본문은 예외 문자열에 복사하지 않는다.

## 채점 기준

점수 조건은 rubric-driven이다. 아래 표는 특정 주차의 고정 조건이 아니라 공통 결과 의미를 설명한다.

| 결과 | 조건 | 점수 |
| --- | --- | ---: |
| PASS | 해당 rubric의 필수 조건을 모두 신뢰성 있게 충족 | rubric의 만점 |
| PARTIAL | 해당 rubric이 partial scoring을 명시하고 그 조건을 충족 | rubric의 partial 점수 |
| FAIL | rubric의 필수 학생 측 조건이 신뢰성 있게 거짓 | 0.0 |
| MANUAL_REVIEW | API·권한·이력·증거 불확실성 | blank/null |

기술적 불확실성을 0점으로 자동 변환하지 않는다. Identity나 partial score는 이를 활성화한 rubric에만 적용한다.

## Phase 4 orchestration

`GradingOrchestrator.grade_student()`는 다음 순서를 사용한다.

1. section/week timing과 `late_window_end`를 해석한다.
2. settle delay가 지나지 않았으면 API를 호출하지 않고 `EVIDENCE_NOT_SETTLED`로 반환한다.
3. repository metadata와 Events API evidence를 읽는다.
4. 학생 actor와 rubric의 branch 정책이 일치하는 최신 accepted PushEvent를 선택한다.
5. accepted submission이 없을 때만 late 또는 신뢰 가능한 `NOT_SUBMITTED`를 판정한다.
6. rubric이 요구하는 collaborator 역할을 독립적으로 확인한다.
7. 필수 collaborator가 `ACTIVE`일 때 selected SHA의 필수 경로 그룹 또는 legacy root README를 조회한다.
8. rubric이 요구하는 경우에만 README identity를 검사하고 순수 score decision을 수행한다.

`grade_section_week()`는 section 학생을 순회하며 각 결과를 독립적으로 보존한다. 한 repository의 API 또는 parsing 오류가 나머지 학생 처리를 중단하지 않는다. `GradeResult`는 timing, selected PushEvent와 head SHA, collaborator 상태, README 경로·identity 결과, score, manual-review 이유와 coverage를 포함하지만 token이나 README 본문은 저장하지 않는다.

불필요한 API 호출을 줄이기 위해 `LATE`, 신뢰 가능한 `NOT_SUBMITTED`, collaborator `MISSING`처럼 점수가 이미 확정된 경우 README를 조회하지 않는다.

## 제출 시각 판정

제출 증거원은 주차별 rubric이 결정하며 `PushEvent.created_at`을 우선 사용한다.

다음 시각은 제출 시각으로 사용하지 않는다.

- commit author date
- 학생 PC 시각
- 파일 수정 시각
- 로컬 filesystem timestamp

`PushEvent.created_at`은 GitHub 측 push 시각이라는 점에서 더 강한 REST 증거다. `commit.committer.date`는 Git commit metadata이므로 보편적으로 push 시각과 동등하지 않다. Rubric이 `COMMIT_HISTORY`를 허용할 때만 deadline 이하 commit을 탐색하며, 설정된 필수 path group 전체를 같은 SHA에서 만족하는 최신 commit을 fallback 증거로 선택한다. Legacy rubric은 기존 root README 규칙을 유지한다. 현재 상태의 파일만으로 과거 제출을 추정하지 않는다.

학생 계정, rubric의 제출 branch 정책, 해당 주차 범위가 일치하는 이벤트 중 `effective_deadline` 이하의 가장 늦은 PushEvent를 `selected_submission_push`로 선택한다. Week 1처럼 branch 이름을 평가하지 않는 rubric은 모든 `refs/heads/...` PushEvent를 허용하지만 tag push는 제외한다. 같은 초에 서로 다른 head SHA가 충돌하면 순서를 추측하지 않고 manual review 대상으로 처리한다.

README는 현재 branch가 아니라 반드시 다음 ref에서 조회한다.

```text
selected_submission_push.head_sha
```

따라서 마감 후 README 변경이 과거 점수를 소급 변경하지 않는다.

## 분반 및 마감 관리

각 분반과 주차는 다음 네 시각을 독립적으로 가진다.

| 구간 | 판정 |
| --- | --- |
| `submission_window_start <= push_time <= scheduled_deadline` | `ON_TIME` |
| `scheduled_deadline < push_time <= effective_deadline` | `EXTENDED_ON_TIME` |
| `effective_deadline < push_time <= late_window_end` | `LATE` |

범위 밖 이벤트는 해당 주차에 사용하지 않는다.

`late_window_end`를 명시하지 않거나 `null`로 두면 같은 분반의 다음 주 `submission_window_start`보다 정확히 1초 전으로 계산한다. 다음 주가 없으면 고정 7일 등을 추측하지 않는다. 명시적 값이 없고 안전하게 유도할 수 없는 post-deadline 증거는 보수적으로 manual review 또는 `UNVERIFIABLE` 처리한다.

마감 연장은 Python 코드를 수정하지 않고 해당 분반의 `effective_deadline`과 `deadline_note`를 변경해 표현한다.

## 결과 파일 및 성적 관리

canonical JSON과 archive는 구현되어 있으며 출력 구조는 다음과 같다.

```text
records/section01/week01.json
archive/section01/week01/revision_001_<timestamp>_<run-id>.json
output/excel/week01_results.xlsx
output/excel/week02_results.xlsx
output/excel/...
output/excel/final_practical_grade.xlsx
```

JSON 기록이 canonical evidence이며 Excel은 JSON에서만 만드는 파생 보고서다. Excel을 삭제하거나 수정해도 canonical grade는 바뀌지 않으며 같은 records에서 다시 생성할 수 있다. 첫 record 저장은 revision 1이며 기존 기록은 기본적으로 `RECORD_ALREADY_EXISTS`로 거부한다. 명시적 `--regrade`에서만 이전 record를 archive한 뒤 새 revision을 설치한다.

record에는 과정·분반·주차·run UUID·revision·timezone-aware 시각, timing/grading policy, 학생별 정규화된 제출·collaborator·README·coverage 증거와 파생 summary가 들어간다. token, 전체 GitHub Events 응답, README 본문은 저장하지 않는다. `0.0`과 `null`은 서로 다른 값으로 보존하며 aggregate에서도 `null`을 0점으로 간주하지 않는다.

```powershell
python main.py grade --week 1 --section 01
python main.py grade --week 1 --section 01 --regrade --regrade-reason "재검토 사유"
python main.py grade --week 1 --section 01 --dry-run
```

`--dry-run`은 GitHub 채점을 수행해 간결한 summary만 표시하고 `records/`나 `archive/`에 쓰지 않는다. `RecordStore.list_records()`와 `load()`는 schema와 상태 일관성을 검증하여 Phase 6가 GitHub를 다시 호출하지 않고 최신 canonical records를 재구성하게 한다.

### Phase 6 보고서

```powershell
python main.py week-report --week 1 --section 01
python main.py week-report --week 1 --all-sections
python main.py rebuild-gradebook
python main.py final-report
```

기본 `week-report`는 설정된 모든 분반을 하나의 `output/excel/weekXX_results.xlsx`에 담는다. `--section`은 필요한 경우 한 분반만 포함하는 선택 필터이며 별도 중복 파일을 만들지 않는다. 주간 workbook은 `채점기준`, 동적으로 생성되는 `SectionXX`, `요약` sheet로 구성되어 채점 기준·분반별 상세 결과·canonical 집계를 함께 보여 준다.

`final-report`는 `output/excel/final_practical_grade.xlsx`를 만든다. 설정된 각 `SectionXX`와 `전체`, `주차별현황` sheet를 동적으로 생성하며 상세 GitHub 증거를 중복하지 않는다. canonical JSON은 자동 채점 결과의 원본이고, 승인된 private `data/manual_grade_adjustments.csv`가 있으면 보고서는 이를 결합한 effective grade를 사용한다. Excel 파일은 언제든 재생성 가능한 파생 보고서다. `output/excel/`은 실제 성적 정보를 포함하므로 계속 Git에서 무시하며 추적하지 않는다.

canonical `1.0`, `0.5`, `0.0`은 Excel numeric cell로 유지한다. `null`, record가 없는 주차와 미래 주차는 blank score로 유지하고 `MANUAL_REVIEW`, `ERROR`, `RECORD_MISSING`, `FUTURE_WEEK` 등의 text status로 구분한다. 실제 `0.0`만 해결된 0점이다.

최종 환산점수는 모든 기대 주차가 numeric으로 해결되고 rubric/canonical identity와 배점이 일치할 때만 `earned / possible × final_practice_weight`로 계산한다. 주차별 실제 max score를 사용하며 null·누락·불일치가 있으면 최종 점수도 blank다.

학생 및 repository 유래 text는 formula-triggering prefix를 escape하고 illegal XML control character를 안전한 문자로 치환한다. 점수 합계와 최종 환산은 Python에서 계산하며 untrusted Excel formula를 만들지 않는다. XLSX는 같은 output directory의 임시 파일을 완성한 뒤 atomic replace하고, Windows에서 열려 잠긴 기존 파일은 보존한 채 오류로 반환한다.

누적 성적표에서 아직 채점하지 않은 주차는 blank로 두고 실제 0.0점과 구분한다. 최종 실습 환산은 canonical 주차별 최대 점수 합계를 사용해 gradebook reconstruction 단계에서 계산한다.

## 테스트 및 검증

2026-09-07 Phase 6 점검 기준:

- offline pytest 결과: 235 passed, 1 skipped, 0 failed
- 개발자 소유 공개 repository 대상 read-only live pytest 결과: 1 passed, 125 deselected, 0 failed
- pytest 기반 Phase 2/3 regression과 Phase 4 pure/orchestration test 실행
- 인증, HTTP status, timeout, retry, pagination, PushEvent, collaborator, README-at-SHA를 fake HTTP response로 검증
- 제출 경계, actor/ref filtering, same-second ambiguity, Events coverage, settle delay, score matrix, section 격리를 offline 검증
- fictional Student와 synthetic 과거 window를 사용한 read-only Phase 4 live orchestration에서 structured `GradeResult` 생성 확인
- live test에서 GitHub CLI 인증, repository metadata·permissions, Events API, rate-limit header, root contents, README UTF-8 decoding, 명시적 commit SHA 조회, 현재 owner collaborator 상태 검증
- 선택한 live repository에는 최근 PushEvent가 없어 live PushEvent normalization은 수행하지 않았으며 offline test로만 검증
- Python syntax/import validation 실행
- Phase 5 persistence와 regrade 실패 경계를 isolated temporary directory에서 검증
- canonical-only reconstruction, Excel typing/security, atomic output과 offline report 경계를 검증
- 실제 학생 저장소 검증은 수행하지 않음

skip된 테스트를 통과한 기능으로 해석해서는 안 된다.

일반 test suite는 network와 credential 없이 실행된다.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

선택적 live smoke test는 소유하거나 명시적으로 사용 허가를 받은 비학생 repository에서만 실행한다. 아래 변수는 process environment 또는 추적되지 않는 `.env`에 설정하며, repository 이름을 source나 README에 기록하지 않는다.

```powershell
$env:RUN_GITHUB_LIVE_TESTS='1'
$env:GITHUB_LIVE_REPOSITORY='owner/repository'
.\.venv\Scripts\python.exe -m pytest -m live -q -p no:cacheprovider
```

인증 또는 opt-in 변수가 없으면 live test는 안전하게 skip된다. 위 live 결과는 개발자 소유 repository에서 일회성 process environment를 사용해 확인한 smoke test이며 모든 환경이나 Phase 4 채점 orchestration의 동작을 보장하지 않는다.

## 개인정보 및 보안

다음 경로는 Git에 추가하지 않는다.

- `.env`, `.env.*` (`.env.example` 제외)
- `config.json` (`config.example.json`은 공개 template으로 추적)
- `data/students.csv`
- `records/`
- `output/`
- `archive/`
- `.venv/`
- `.vscode/`, `.idea/`

이 파일에는 실제 교수자·조교 계정, 학생 이름·학번·GitHub 계정·저장소·점수·PushEvent 시각·commit SHA·README snapshot·토큰이 포함될 수 있다.

`.gitignore`는 이미 추적된 파일이나 기존 Git history에서 파일을 제거하지 않는다. 민감정보가 commit된 경우 최신 파일만 삭제해서 해결된 것으로 간주하지 않으며, 추가 전파를 멈추고 history rewrite 필요성을 검토하고 노출된 credential을 회전해야 한다. Git history 변경은 명시적 승인 없이 수행하지 않는다.

## 주의사항 및 한계

- GitHub repository event timeline은 영구 archive가 아니다.
- 현재 공식 문서 기준 최대 약 300개 이벤트와 최근 약 30일 범위만 제공된다.
- repository event 반영은 약 30초에서 최대 6시간 지연될 수 있다.
- 일반 채점은 최소 `effective_deadline + github_event_settle_delay_hours` 이후 수행하며 accepted push가 없을 때에는 late window evidence도 settle될 때까지 기다린다.
- `--force-early-grading`은 불완전한 증거를 canonical record로 고정할 수 있어 현재 CLI가 GitHub 요청 전에 명시적으로 거부한다.
- 이벤트가 300개 한도에서 잘렸거나 필요한 기간을 덮지 못하면 `NOT_SUBMITTED`로 단정하지 않는다.
- collaborator API는 채점 시점의 접근 상태만 확인하며 초대·수락 시점을 역사적으로 증명하지 않는다.
- 권한 또는 인증 문제를 collaborator `MISSING`으로 해석하지 않는다.
- force-push 또는 ref 삭제로 선택 SHA를 조회할 수 없으면 현재 branch로 대체하지 않는다.
- 오래된 채점은 만료되는 GitHub Events가 아니라 로컬 불변 JSON 기록에 의존해야 한다.

관련 GitHub 문서:

- [REST API endpoints for events](https://docs.github.com/en/rest/activity/events)
- [REST API endpoints for repository contents](https://docs.github.com/en/rest/repos/contents)
- [REST API endpoints for collaborators](https://docs.github.com/en/rest/collaborators/collaborators)

## 향후 확장

향후에는 C source grading, 추가 rubric 유형과 운영 backup/export 절차를 별도 단계에서 다룬다. Excel을 canonical JSON으로 다시 가져오는 경로는 추가하지 않는다.

`c_checker.py`는 현재 항상 `NotImplementedError`를 발생시키는 안전한 placeholder이며 학생 코드를 실행하지 않는다.

향후 C 채점은 `.c`, `.h`, `.sln`, `.vcxproj` 파일 확인, GCC/MSBuild compile, stdin/stdout test, timeout과 partial score를 지원할 수 있다. 모든 확인 대상은 repository 최신 상태가 아니라 `submission_push_head_sha`에서 가져와야 한다.

학생 프로그램은 신뢰할 수 없는 코드이므로 향후 실행 기능에는 격리, timeout, 임시 작업 폴더, resource 제한, stdout/stderr capture, grader credential 차단이 필요하다.
