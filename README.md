# Data Structures GitHub Lab Grader

Data Structures 실습 과목의 GitHub 제출 증거를 수집하고 주차별 채점 결과를 보존하기 위한 Windows용 Python CLI 프로젝트이다.

현재 저장소는 **Phase 2 기반 구조**까지 구현되어 있다. CLI 명령 구조, 데이터 모델, 안전한 예시 설정, 테스트 명세가 포함되어 있으며, 실제 GitHub API 호출·채점·JSON 기록·Excel 생성은 아직 연결되지 않았다.

## 프로젝트 목적

학생이 매주 다른 공용 PC를 사용하더라도 GitHub에 실제로 push한 시점을 기준으로 제출을 확인하고, 분반별 마감과 예외 연장을 일관되게 적용하는 것이 목적이다.

Version 1의 최종 범위는 다음 항목이다.

- GitHub `PushEvent.created_at` 기반 제출 시각 확인
- 교수자와 조교의 현재 collaborator 상태 확인
- 선택된 제출 SHA 시점의 루트 `README.md` 확인
- README의 정확한 학번·이름 확인
- 주차별 점수 계산과 불변 JSON 증거 보존
- 분반별 주차 결과와 누적 Excel 성적표 생성

C 소스 검사와 학생 프로그램 실행은 Version 1 범위가 아니다.

## 현재 구현 상태

| 구분 | 현재 상태 |
| --- | --- |
| argparse CLI 명령 및 옵션 | 구현 |
| 학생·마감·PushEvent·채점 결과 데이터 모델 | 구현 |
| timezone-aware 모델 검증 | 구현 |
| 안전한 예시 설정과 개인정보 제외 규칙 | 구현 |
| Phase 3 이후 동작의 pytest 명세 | scaffolded, 현재 skip |
| 설정 파일 로딩과 실제 채점 로직 | 미구현 |
| GitHub REST API 연동 | 미구현 |
| 불변 JSON 기록과 regrade archive | 미구현 |
| Excel 보고서와 누적 성적표 | 미구현 |
| 실제 학생 저장소 검증 | 미수행 |

현재 `grade`, `rebuild-gradebook`, `final-report`, `validate-config` 명령은 인자 구조만 정의한다. 실행하면 Phase 2 미구현 오류로 종료하는 것이 정상이다.

## 전체 프로젝트 구조

```text
DS-TA/
├─ README.md
├─ main.py
├─ config.json
├─ requirements.txt
├─ .env.example
├─ .gitignore
├─ data/
│  └─ students.example.csv
├─ rubrics/
│  └─ week01.json
├─ github_lab_grader/
│  ├─ __init__.py
│  ├─ models.py
│  ├─ config_loader.py
│  ├─ github_client.py
│  ├─ submission_checker.py
│  ├─ collaborator_checker.py
│  ├─ readme_checker.py
│  ├─ grader.py
│  ├─ record_store.py
│  ├─ excel_report.py
│  ├─ gradebook.py
│  └─ c_checker.py
└─ tests/
   ├─ conftest.py
   ├─ test_cli.py
   ├─ test_models.py
   ├─ test_example_configuration.py
   ├─ test_submission_checker.py
   ├─ test_readme_checker.py
   ├─ test_grader.py
   └─ test_record_and_gradebook_scaffold.py
```

| 경로 | 설명 |
| --- | --- |
| `main.py` | CLI entry point와 명령 인자 구조 |
| `github_lab_grader/models.py` | 상태 enum과 typed evidence model |
| `github_lab_grader/github_client.py` | Phase 4 GitHub REST 경계 placeholder |
| `github_lab_grader/c_checker.py` | 실행 기능이 없는 향후 C 채점 placeholder |
| `data/students.example.csv` | 공개 가능한 가상 학생 데이터 형식 |
| `rubrics/week01.json` | 실제 사용 전에 교체해야 하는 문서용 주차 설정 |
| `tests/` | 현재 기반 검증과 이후 Phase 동작 명세 |

`records/`, `output/`, `archive/`, `data/students.csv`는 실행 중 로컬에서 만들어질 개인정보·성적 자료이므로 저장소 트리에 포함하지 않는다.

## 사용 기술

| 항목 | 현재 코드 기준 |
| --- | --- |
| 운영 환경 | Windows, VS Code |
| Python | 3.11 이상 |
| CLI | Python 표준 라이브러리 `argparse` |
| 데이터 모델 | `dataclasses`, `enum.StrEnum` |
| 테스트 | pytest |

현재 Phase 2에서 설치가 필요한 외부 패키지는 pytest뿐이다. `requests`, `python-dotenv`, `openpyxl`은 각각 GitHub 연동과 Excel 생성 단계에서 실제 사용 코드가 추가될 때 의존성에 포함한다.

## 설치 및 실행 방법

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

### `config.json`

학기, 과목, collaborator 계정, timezone, 분반 목록, 전체 주차 수, 환산 배점, GitHub API version을 정의한다.

- `sections`는 문자열 목록이며 `01`, `02`처럼 앞자리 0을 보존한다.
- 분반 수를 Python 코드에 고정하지 않는다.
- `professor_github`와 `assistant_github`의 placeholder는 실제 채점 전에 교체한다.
- 모든 수업 시각은 `Asia/Seoul` 기준이다.

### `data/students.csv`

실제 운영 파일의 schema는 다음과 같다.

```csv
section,student_id,name,github_id,repository
```

`repository`는 `owner/repository` 형식을 사용한다. 저장소에는 가상 데이터만 포함한 `data/students.example.csv`만 추적하며, 실제 `data/students.csv`는 `.gitignore`로 제외한다.

### `rubrics/weekNN.json`

주차별 제목, 최대 점수, 제출 branch, PushEvent actor 조건, 분반별 마감, 채점 조건을 정의한다.

현재 `week01.json`의 날짜는 schema를 보여주기 위한 **문서용 예시**이며 실제 수업 일정이 아니다. 실제 채점 전 반드시 교체해야 한다. 시각은 다음과 같이 UTC offset을 포함한 ISO-8601 형식을 사용한다.

```json
"scheduled_deadline": "2026-09-02T23:59:59+09:00"
```

naive timestamp는 허용하지 않는다.

### 인증

인증 연동은 아직 구현되지 않았다. Phase 4에서는 인증된 GitHub CLI session을 우선 사용하고 `GITHUB_TOKEN` 환경변수를 fallback으로 사용할 예정이다. 토큰은 코드·설정·로그·채점 기록에 저장하지 않는다.

로컬 `.env`가 필요해지면 `.env.example`을 복사해 사용한다. 실제 `.env`는 추적하지 않는다.

## 채점 기준

아래 정책은 확정된 설계이며 계산 함수는 Phase 3에서 구현한다.

| 결과 | 조건 | 점수 |
| --- | --- | ---: |
| PASS | 유효 제출, 두 collaborator ACTIVE, README 존재, 학번·이름 모두 정확 | 1.0 |
| PARTIAL | 유효 제출, 두 collaborator ACTIVE, README 존재, 학번·이름 중 하나 이상 누락 | 0.5 |
| FAIL | LATE, 신뢰 가능한 NOT_SUBMITTED, README 누락, collaborator 누락 | 0.0 |
| MANUAL_REVIEW | API·권한·이력·증거 불확실성 | blank/null |

학번과 이름이 모두 없더라도 나머지 필수 조건과 README가 충족되면 현재 정책상 0.5점이다. 기술적 불확실성을 0점으로 자동 변환하지 않는다.

## 제출 시각 판정

과목 정책상 공식 제출 증거는 GitHub repository event의 `PushEvent.created_at`이다.

다음 시각은 공식 제출 시각으로 사용하지 않는다.

- commit author date
- commit committer date
- 학생 PC 시각
- 파일 수정 시각
- 로컬 filesystem timestamp

`PushEvent.created_at`은 이 과목이 채택한 최선의 REST 증거이지만 법적 또는 영구적인 수신 증명을 보장하는 값이라고 주장하지 않는다.

학생 계정, 제출 branch, 해당 주차 범위가 일치하는 이벤트 중 `effective_deadline` 이하의 가장 늦은 PushEvent를 `selected_submission_push`로 선택한다. 같은 초에 서로 다른 head SHA가 충돌하면 순서를 추측하지 않고 manual review 대상으로 처리한다.

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

이 기능은 아직 구현되지 않았다. Phase 5 이후 다음 구조를 사용할 예정이다.

```text
records/section01/week01.json
archive/section01/week01/<timestamp>_revision1.json
output/section01/week01_results.xlsx
output/section01/master_gradebook.xlsx
output/final_all_sections.xlsx
```

JSON 기록이 canonical evidence이며 Excel은 JSON에서 다시 생성하는 보고서다. 기존 기록은 기본적으로 덮어쓰지 않고, 명시적 `--regrade`에서만 이전 기록을 충돌 없는 archive 경로에 보존한 뒤 atomic write로 새 기록을 설치한다.

누적 성적표에서 아직 채점하지 않은 주차는 blank로 두고 실제 0.0점과 구분한다. 최종 실습 환산 점수는 포함된 주차의 실제 최대 점수 합계를 사용하며 별도 함수에서 계산할 예정이다.

## 테스트 및 검증

2026-09-04 Phase 2 최종 점검 기준:

- pytest 기반 모델·CLI·예시 설정 검증 실행
- Python syntax/import validation 실행
- Phase 3~6의 경계·README·점수·기록·성적표 요구사항은 test scaffold로 수집
- 실제 GitHub API, mock API response, 실제 학생 저장소 검증은 아직 수행하지 않음

skip된 테스트를 통과한 기능으로 해석해서는 안 된다.

## 개인정보 및 보안

다음 경로는 Git에 추가하지 않는다.

- `.env`, `.env.*` (`.env.example` 제외)
- `data/students.csv`
- `records/`
- `output/`
- `archive/`
- `.venv/`
- `.vscode/`, `.idea/`

이 파일에는 학생 이름·학번·GitHub 계정·저장소·점수·PushEvent 시각·commit SHA·README snapshot·토큰이 포함될 수 있다.

`.gitignore`는 이미 추적된 파일이나 기존 Git history에서 파일을 제거하지 않는다. 민감정보가 commit된 경우 최신 파일만 삭제해서 해결된 것으로 간주하지 않으며, 추가 전파를 멈추고 history rewrite 필요성을 검토하고 노출된 credential을 회전해야 한다. Git history 변경은 명시적 승인 없이 수행하지 않는다.

## 주의사항 및 한계

- GitHub repository event timeline은 영구 archive가 아니다.
- 현재 공식 문서 기준 최대 약 300개 이벤트와 최근 약 30일 범위만 제공된다.
- repository event 반영은 약 30초에서 최대 6시간 지연될 수 있다.
- 일반 채점은 `effective_deadline + 6시간` 이후 수행해야 한다.
- `--force-early-grading`은 불완전한 이벤트 증거를 만들 수 있으므로 경고와 manual-review 상태가 필요하다.
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

`c_checker.py`는 현재 항상 `NotImplementedError`를 발생시키는 안전한 placeholder이며 학생 코드를 실행하지 않는다.

향후 C 채점은 `.c`, `.h`, `.sln`, `.vcxproj` 파일 확인, GCC/MSBuild compile, stdin/stdout test, timeout과 partial score를 지원할 수 있다. 모든 확인 대상은 repository 최신 상태가 아니라 `submission_push_head_sha`에서 가져와야 한다.

학생 프로그램은 신뢰할 수 없는 코드이므로 향후 실행 기능에는 격리, timeout, 임시 작업 폴더, resource 제한, stdout/stderr capture, grader credential 차단이 필요하다.
