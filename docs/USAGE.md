# DS-TA 사용 가이드

## 1. 시스템 개요

DS-TA는 GitHub의 제출 증거를 확인해 학생별 점수를 판정하고, 결과를 canonical JSON으로 보존한 뒤 Excel 보고서를 생성하는 로컬 CLI 도구다.

```text
GitHub evidence → grading → canonical JSON → Excel
```

canonical JSON이 성적의 원본이며 Excel은 언제든 다시 만들 수 있는 파생 보고서다.

## 2. 최초 환경 준비

Windows에 Python과 GitHub CLI(`gh`)를 설치하고 저장소 루트에서 가상환경과 의존성을 준비한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
gh auth login
gh auth status
```

VS Code 확장은 필수가 아니다. Python 확장을 설치하면 편집과 테스트 실행이 편리하지만, 제공된 Task는 `.venv`의 Python을 직접 사용한다.

## 3. 로컬 전용 설정 파일

공개 예시를 복사한 뒤 실제 값은 복사본에만 입력한다.

```powershell
Copy-Item config.example.json config.json
Copy-Item data/students.example.csv data/students.csv
```

`config.json`과 `data/students.csv`는 `.gitignore`로 보호되는 로컬 전용 파일이다. 공개 예시 파일에는 가상 값만 유지한다.

## 4. config.json 설정

주요 필드는 다음과 같다.

- `semester`, `course`: 학기와 과목 식별자
- `professor_github`, `assistant_github`: collaborator 확인 대상 GitHub ID
- `timezone`: 마감 시각의 기준 시간대(예: `Asia/Seoul`)
- `sections`: 운영 분반 목록(예: `["01", "02"]`)
- `total_weeks`: 전체 실습 주차 수
- `final_practice_weight`: 최종 실습 환산 배점
- `github_api_version`: 사용할 GitHub REST API version
- `github_event_settle_delay_hours`: Events 반영을 기다리는 보수적 지연 시간
- `github_event_history_max_age_days`: Events 증거 범위 판단 한도
- `github_request`: timeout, retry, rate-limit 대기 상한

GitHub 계정 예시는 `example-professor`, `example-assistant`처럼 명백한 가상 값을 사용한다.

## 5. students.csv 형식

필수 열은 다음과 같다.

```csv
section,student_id,name,github_id,repository
01,EXAMPLE001,Example Student,example-student,example-student/data-structures-lab
```

`repository`는 `owner/repository` 또는 `https://github.com/owner/repository` 형식을 사용할 수 있다. URL은 내부에서 API용 식별자로 정규화되며, 등록된 경우 owner와 `github_id`가 일치해야 한다. spreadsheet 내보내기로 생긴 별도 index 열은 무시된다. 아직 GitHub 정보를 제출하지 않은 학생은 `github_id`와 `repository`를 비워 둘 수 있다. 이 학생은 목록에서 빠지거나 0점 처리되지 않고 `MISSING_REPOSITORY_INFO`, `MANUAL_REVIEW`, `score = null`로 보존된다.

## 6. 주차별 rubric 및 마감 설정

`rubrics/weekXX.json`은 주차별 배점과 분반별 제출 시각을 정의한다.

- `submission_window_start`: 이번 주차 증거로 인정할 시작 시각
- `scheduled_deadline`: 정규 마감
- `effective_deadline`: 연장 적용 후 실질 마감
- `late_window_end`: 지각 증거 인정 종료 시각
- `deadline_note`: 연장 또는 운영 사유

주차별 채점 조건은 rubric이 결정한다. `scoring_mode`, 필수 collaborator 역할, README identity 필요 여부, `enforce_submission_window_start`, `enforce_submission_branch`, `use_late_window`를 주차마다 다르게 지정할 수 있다. `enforce_submission_branch: false`이면 이름과 관계없이 정상 브랜치 PushEvent(`refs/heads/...`)를 인정하며 tag ref는 인정하지 않는다. true이면 `submission_branch`가 `default`일 때 저장소 기본 브랜치만, 명시적 이름일 때 해당 브랜치만 인정한다. 시작 경계를 사용하는 과제는 `submission_window_start <= PushEvent.created_at`을 적용하고, deadline-only 과제는 `enforce_submission_window_start: false`로 설정해 deadline 이전 제출에 하한을 적용하지 않는다. `use_late_window`가 true이고 `late_window_end`가 null이면 같은 분반 다음 주차의 `submission_window_start` 1초 전으로 계산한다. 다음 주차가 없으면 명시적 값이 필요하다. `use_late_window`가 false이면 effective deadline과 Events settle delay만으로 제출 여부를 확정한다.

Week 1의 실제 채점 기준과 증거 판정 절차는 [Week 1 사용 가이드](WEEK1_USAGE.md)를 참고한다.

## 7. VS Code에서 실행하기

VS Code에서 저장소를 열고 `Terminal` → `Run Task`를 선택한다. 다음 로컬 Task가 제공된다.

- `DS-TA: Preflight`
- `DS-TA: Dry Run`
- `DS-TA: REAL Grade Section/Week`
- `DS-TA: Regrade Section/Week`
- `DS-TA: Week Report`
- `DS-TA: Final Report`
- `DS-TA: Run Tests`

주차와 분반은 실행할 때 입력하며 실제 계정이나 학생 값은 Task 파일에 저장하지 않는다. `.vscode/`는 Git에 올리지 않는 로컬 설정이다.

## 8. 실제 채점 전 Preflight

다음은 Week 1/Section 01을 사용한 명령 형식 예시다.

```powershell
.\.venv\Scripts\python.exe main.py preflight --week 1 --section 01
```

Preflight는 private 파일의 존재·Git 비추적 상태, config와 roster 형식, 분반과 rubric, 네 개의 마감 시각, late window, settle 시간, GitHub 인증, 학생 수 및 GitHub 등록 누락 수를 확인한다. `BLOCKER`가 있으면 실제 채점을 진행하지 않는다. 등록 누락은 해당 학생을 null로 남기는 `WARNING`이다.

## 9. Dry Run

```powershell
.\.venv\Scripts\python.exe main.py grade --week 1 --section 01 --dry-run
```

Dry Run은 실제와 같은 읽기 전용 GitHub 증거 확인과 점수 판정을 수행하지만 `records/`, `archive/`, `output/`에 파일을 만들지 않는다. 출력의 null, manual-review, error 수를 확인한 뒤 실제 채점을 결정한다.

기본 출력은 `1.0`, `0.5`, `0.0`, `null`, null 원인, 제출 상태, evidence source와 active rubric의 timing 진단을 aggregate로 보여 준다. Deadline-only rubric은 late window를 요구하지 않을 수 있고 bounded-window rubric은 start/end 경계를 사용할 수 있다. 특정 학생을 확인해야 할 때만 `--details`를 추가한다.

```powershell
.\.venv\Scripts\python.exe main.py grade --week 1 --section 01 --dry-run --details
```

상세 모드는 확정 0점 학생의 학번과 판정 원인, 확인용 확정 1점 학번, 미해결 학생의 학번과 상태 코드를 서로 구분해 출력한다. 이름, repository URL, README나 GitHub 원문은 출력하지 않는다.

## 10. 실제 채점

```powershell
.\.venv\Scripts\python.exe main.py grade --week 1 --section 01
```

성공하면 `records/section01/week01.json`과 같은 canonical record가 생성된다. 같은 section/week에 기존 기록이 있으면 명시적 regrade 없이 덮어쓰지 않는다.

## 11. 점수 의미

- `1.0`: 해당 주차 rubric이 정의한 만점 조건을 신뢰성 있게 충족
- `0.5`: 해당 rubric이 partial score를 정의하고 그 조건을 만족
- `0.0`: 증거가 충분한 학생 측 필수 조건 실패
- blank/null: 등록 누락, API 불확실성, 불완전한 증거 또는 수동 검토 필요

`0.0`은 확정된 점수이고 null은 아직 점수를 확정할 수 없다는 뜻이다. 둘을 절대 서로 바꾸지 않는다.

Week 1의 구체적인 binary 점수 의미는 [Week 1 사용 가이드](WEEK1_USAGE.md)를 참고한다.

## 12. 확인 필요 상태

- `MISSING_REPOSITORY_INFO`: GitHub ID 또는 repository 미등록
- `MANUAL_REVIEW`: 사람이 확인해야 하며 점수는 null
- `UNVERIFIABLE`: 증거 범위나 응답을 신뢰성 있게 확정하지 못함
- `ERROR`: API 또는 처리 오류로 점수를 확정하지 못함
- `EVIDENCE_NOT_SETTLED`: Events 반영 대기 시간이 지나지 않음
- `AMBIGUOUS_SUBMISSION`: 동일 시각의 충돌하는 제출 증거

이 상태들은 학생의 자동 0점 근거가 아니다.

## 13. 재채점

```powershell
.\.venv\Scripts\python.exe main.py grade --week 1 --section 01 --regrade --regrade-reason "검토 사유"
```

재채점은 별도 명령으로만 실행한다. 이전 canonical record는 `archive/` 아래에 먼저 보존되고 새 record revision이 증가한다. 사유를 남기면 변경 이력을 이해하기 쉽다.

## 14. 주차별 Excel 생성

```powershell
.\.venv\Scripts\python.exe main.py week-report --week 1
```

`output/excel/week01_results.xlsx`가 생성되며 `채점기준`, 설정된 각 `SectionXX`, `요약` sheet를 포함한다. canonical records만 읽고 GitHub를 다시 조회하지 않는다.

## 15. 최종 실습성적 Excel 생성

```powershell
.\.venv\Scripts\python.exe main.py final-report
```

`output/excel/final_practical_grade.xlsx`가 생성되며 설정된 각 `SectionXX`, `전체`, `주차별현황` sheet를 포함한다. 필수 주차가 null, 누락 또는 미완료이면 최종 성적도 blank다. 실제 `0.0`은 해결된 점수로 계산에 참여한다.

## 16. Canonical record와 Excel의 차이

Canonical JSON은 감사와 재현을 위한 source of truth다. Excel은 검토·배포 편의를 위한 derived report다. 수정된 Excel 값을 canonical record로 읽어 들이지 않으며 보고서 생성 중 재채점하지 않는다.

## 17. 자주 발생하는 문제

- GitHub CLI 미인증: `gh auth login` 후 `gh auth status`를 확인한다.
- Repository 접근 불가: repository 이름과 권한을 확인하고 자동 0점으로 처리하지 않는다.
- 학생 repository 미등록: roster의 빈 값을 유지하고 `MISSING_REPOSITORY_INFO` warning을 확인한다.
- Events 증거 불완전: settle 시간과 event history 범위를 확인한다.
- 기존 record 존재: 원인을 검토한 뒤 필요한 경우에만 명시적 regrade를 실행한다.
- Excel 파일 잠김: Excel에서 파일을 닫은 뒤 다시 생성한다. 기존 파일은 보존된다.
- Manual review 필요: canonical 사유와 주간 workbook 상세 상태를 확인한다.

## 18. Git / 개인정보 주의사항

다음 경로는 실제 계정, 학생 정보, 성적 또는 token을 포함할 수 있으므로 절대 commit하지 않는다.

- `.env`
- `config.json`
- `data/students.csv`
- `records/`
- `archive/`
- `output/`

실제 운영 중에는 `git add .`을 피하고 공개 가능한 파일만 명시적으로 선택한다. `git status --short`와 staged diff를 항상 확인한다.

## 19. 권장 실제 운영 순서

1. VS Code에서 저장소를 열고 GitHub CLI 인증을 확인한다.
2. 로컬 `config.json`, `data/students.csv`, 주차 rubric을 점검한다.
3. `DS-TA: Preflight`를 실행해 blocker와 warning을 확인한다.
4. `DS-TA: Dry Run`을 실행한다.
5. null, manual-review, error 수와 사유를 검토한다.
6. `DS-TA: REAL Grade Section/Week`를 실행한다.
7. canonical record가 생성되었는지 확인한다.
8. `DS-TA: Week Report`로 주간 Excel을 만든다.
9. 수정이 필요할 때만 사유를 입력해 regrade한다.
10. 모든 필수 주차가 해결된 뒤 `DS-TA: Final Report`를 실행한다.
