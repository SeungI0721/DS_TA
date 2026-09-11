# DS-TA Project Agent Instructions

이 문서는 `DS-TA` 저장소에서 작업하는 AI agent, Codex 및 자동화 도구가 따라야 하는 프로젝트 고유 규칙을 정의한다.

이 저장소는 단순한 GitHub 분석 도구가 아니다.

학생 GitHub 제출 증거를 바탕으로 실제 수업 성적을 산출하는 시스템이므로 다음이 최우선이다.

- 실제 수업 채점 규칙의 정확성
- 학생에게 불리한 추정 금지
- GitHub 증거의 신뢰성 구분
- `0.0`과 `null`의 엄격한 분리
- 개인정보와 실제 성적의 Git 유출 방지
- canonical grading record 보존
- 재현 가능한 보고서 생성

구현 편의보다 채점 신뢰성이 우선한다.

---

# 1. 프로젝트 목적

DS-TA의 기본 파이프라인은 다음과 같다.

```text
학생 GitHub repository
        ↓
GitHub evidence acquisition
        ↓
주차별 rubric 기반 판정
        ↓
GradeResult
        ↓
canonical JSON record
        ↓
Excel report
```

각 계층의 책임을 혼합하지 않는다.

```text
GitHub client
→ 증거 수집

submission/readme/collaborator logic
→ 증거 해석

grader/orchestrator
→ 점수 및 상태 결정

record_store
→ canonical 기록

gradebook
→ canonical 기록 재구성

excel_report
→ 파생 보고서 생성
```

Excel은 채점 원본이 아니다.

---

# 2. 정책 우선순위

채점 규칙이 충돌할 경우 다음 우선순위를 사용한다.

1. 사용자가 가장 최근에 명시적으로 확정한 실제 수업 규칙
2. 해당 주차의 validated rubric
3. 현재 validated local configuration
4. canonical grading record
5. 현재 코드와 테스트
6. README / docs
7. generic/default grading behavior

가장 중요한 규칙:

> generic architecture가 실제 주차별 수업 규칙보다 우선해서는 안 된다.

예를 들어 generic grader가 다음을 지원한다고 해서:

- `main` branch
- professor collaborator
- README 학번/이름
- late window
- 0.5 partial score

해당 조건을 모든 주차에 자동 적용해서는 안 된다.

주차별 rubric에서 활성화된 조건만 점수에 영향을 준다.

---

# 3. 숨겨진 채점 조건 추가 금지

Agent는 실제 rubric에 없는 조건을 임의로 채점 조건으로 추가하면 안 된다.

특히 다음을 자동 요구하지 않는다.

- 특정 branch 이름
- `main`
- `master`
- professor collaborator
- README 내부 학생 이름
- README 내부 학번
- repository naming convention
- 특정 commit message
- 특정 파일 구조
- submission start date
- late window
- PushEvent 존재 자체
- 특정 IDE 또는 Git 사용 방식

이러한 조건은 해당 주차 rubric이 명시적으로 요구하는 경우에만 적용한다.

---

# 4. Week 1 현재 확정 정책

현재 Week 1 정책은 실제 수업 규칙에 따라 다음과 같이 확정되어 있다.

두 분반 모두 동일하다.

```text
Section 01
Section 02
```

공식 공지 마감:

```text
2026-09-03 23:59 KST
```

기계 비교 cutoff는 해당 분의 끝인 `2026-09-03T23:59:59+09:00`로 정규화한다.

최대 점수:

```text
1.0
```

Scoring mode:

```text
BINARY
```

Week 1에는 `0.5`가 없다.

## 1.0 조건

다음이 모두 만족되어야 한다.

```text
마감일까지 repository root README.md 존재
+
(week01/README.md 또는 week01-01/README.md 존재)
+
professor collaborator 현재 ACTIVE
+
assistant/TA collaborator 현재 ACTIVE
```

## Week 1에서 점수 조건이 아닌 것

다음은 Week 1 점수에 영향을 주지 않는다.

```text
README 내부 학생 이름
README 내부 학번
특정 branch 이름
submission start boundary
late window
PushEvent 자체의 존재 여부
```

Week 1은:

```text
enforce_submission_window_start = false
enforce_submission_branch = false
use_late_window = false
```

여야 한다.

---

# 5. Week 1 submission evidence

Week 1에서 `PushEvent`는 제출 증거 중 하나이지 제출의 정의가 아니다.

절대 다음과 같이 구현하지 않는다.

```text
PushEvent 없음
→ NOT_SUBMITTED
→ 0.0
```

이 로직은 금지한다.

Week 1은 rubric이 허용하는 증거 소스를 순차적으로 평가해야 한다.

## 우선 증거

```text
PushEvent.created_at
```

가능한 경우 가장 강한 GitHub-side push timing evidence로 사용한다.

## fallback 증거

Week 1에서는 PushEvent가 없는 정상 학생 workflow를 허용하기 위해 commit history fallback을 사용할 수 있다.

Week 1에서 허용되는 fallback:

```text
GitHub REST API commit history
+
commit.committer.date <= deadline
+
해당 commit SHA에 repository-root README.md 존재
+
(week01/README.md 또는 week01-01/README.md 존재)
```

이 경우:

```text
COMMIT_HISTORY_CONFIRMED
```

등의 provenance로 기록한다.

주의:

```text
commit.author.date
```

는 Week 1 fallback cutoff 판단에 사용하지 않는다.

Week 1 fallback에서는:

```text
commit.committer.date
```

를 사용한다.

하지만 문서와 코드에서는 이 값이 `PushEvent.created_at`과 동일한 강도의 push timestamp라고 표현하지 않는다.

Week 1에서 fallback으로 인정하는 것은 명시적인 course-policy 결정이다.

---

# 6. Evidence provenance

가능하면 GradeResult와 canonical record에 제출 판정 근거를 남긴다.

예:

```text
PUSH_EVENT_CONFIRMED
COMMIT_HISTORY_CONFIRMED
INSUFFICIENT_EVIDENCE
```

필요하면 보조 증거를 구분할 수 있다.

예:

```text
CREATE_EVENT_CORROBORATED
```

최소한 다음은 추적 가능해야 한다.

```text
submission_evidence_source
selected_submission_sha
selected_submission_timestamp
selected_submission_timestamp_type
```

예:

```text
PUSH_EVENT_CREATED_AT
COMMIT_COMMITTER_DATE
```

---

# 7. 증거의 불확실성

학생에게 불리한 추정을 하지 않는다.

다음은:

```text
score = null
```

이어야 한다.

예:

- GitHub 등록정보 누락
- repository 접근 불가
- authentication/API failure
- collaborator UNKNOWN
- Events history 불충분
- selected SHA 확인 불가
- historical README 존재 여부 불명
- conflicting evidence
- malformed GitHub evidence
- GitHub history 제한으로 absence를 증명할 수 없음

불확실한 상태를:

```text
0.0
```

으로 변환하지 않는다.

---

# 8. 0.0과 null

이 프로젝트에서 가장 중요한 invariant 중 하나다.

```text
0.0 != null
```

## 0.0

학생 측 실패가 신뢰성 있게 확인된 실제 점수다.

예:

```text
README가 마감 기준으로 확실히 없음
필수 collaborator가 확실히 MISSING
rubric이 요구한 제출 조건을 확실히 충족하지 못함
```

## null

아직 점수를 확정할 수 없는 상태다.

예:

```text
MANUAL_REVIEW
UNVERIFIABLE
ERROR
MISSING_REPOSITORY_INFO
UNKNOWN collaborator
insufficient evidence
```

Excel에서도:

```text
0.0 → numeric 0.0
null → blank cell
```

로 유지한다.

---

# 9. 학생 GitHub 미등록

`data/students.csv`에는 아직 GitHub 등록정보가 없는 학생이 존재할 수 있다.

다음 상태는 허용한다.

```text
github_id = blank
repository = blank
```

이 경우:

```text
submission_status = MISSING_REPOSITORY_INFO
grading_status = MANUAL_REVIEW
score = null
```

이어야 한다.

절대:

```text
NOT_SUBMITTED
0.0
```

으로 변환하지 않는다.

해당 학생에 대한 GitHub API 호출도 하지 않는다.

한 학생의 등록정보 누락 때문에 전체 section grading을 중단하지 않는다.

---

# 10. 학생별 오류 격리

한 학생의 다음 문제가:

- repository 오류
- API 오류
- manual review
- missing registration
- collaborator ambiguity

다른 학생의 채점을 중단해서는 안 된다.

section grading은 student-level isolation을 유지한다.

---

# 11. GitHub API 기본 원칙

학생 repository에 대한 DS-TA 작업은 기본적으로 READ ONLY다.

허용:

```text
GET
```

금지:

```text
POST
PUT
PATCH
DELETE
```

특히 자동으로 다음을 하지 않는다.

- commit
- push
- branch 생성
- issue 생성
- collaborator 추가/삭제
- repository 수정
- release 생성
- tag 생성

---

# 12. GitHub Events API 한계

GitHub Repository Events는 영구적인 audit log가 아니다.

알려진 제약을 항상 고려한다.

- 최근 history만 제공될 수 있음
- 최대 약 300 events
- publication latency 존재
- historical PushEvent가 없어질 수 있음

따라서:

```text
Events API에서 PushEvent 없음
```

만으로 학생의 미제출을 확정하면 안 된다.

Rubric이 허용하는 다른 증거를 확인해야 한다.

---

# 13. Branch 처리

Branch requirement는 rubric-driven이다.

## branch enforcement가 false

다음과 같은 일반 branch ref를 인정할 수 있다.

```text
refs/heads/main
refs/heads/master
refs/heads/feature
```

Tag는 branch로 인정하지 않는다.

```text
refs/tags/...
```

## branch enforcement가 true

rubric이 명시한 branch 또는 정의된 default-branch 정책을 따른다.

Agent가 임의로 `main`을 요구해서는 안 된다.

---

# 14. Submission start boundary

`submission_window_start`가 configuration에 존재한다고 해서 항상 scoring condition인 것은 아니다.

Rubric의:

```text
enforce_submission_window_start
```

또는 동등한 설정을 확인한다.

false이면:

```text
PushEvent/commit <= effective_deadline
```

만 사용한다.

주차 번호를 Python에서 hardcode하지 않는다.

잘못된 예:

```python
if week == 1:
    ...
```

좋은 방식:

```python
if rubric.enforce_submission_window_start:
    ...
```

---

# 15. Collaborator 정책

Collaborator requirement 역시 rubric-driven이다.

Week 1:

```text
assistant collaborator required
professor collaborator required
```

두 collaborator는 deadline 당시 상태가 아니라 채점 시점의 현재 `ACTIVE` 상태를 확인한다.

Collaborator 상태:

```text
ACTIVE
MISSING
UNKNOWN
ERROR
```

의 의미를 유지한다.

UNKNOWN/ERROR는 자동 0점 처리하지 않는다.

---

# 16. README 정책

README 요구사항은 rubric-driven이다.

Week 1:

```text
repository root README.md 존재
+
(week01/README.md 또는 week01-01/README.md 존재)
```

Week 1에서는 README 내부:

```text
student_id
name
```

을 점수에 사용하지 않는다.

다른 rubric이 identity partial scoring을 활성화할 경우에만 해당 로직을 사용한다.

Project README는 rubric에 명시된 두 정확한 경로 중 하나여야 하며 root README를 대체하지 않는다.

---

# 17. Canonical grading record

Canonical record는 자동 채점 결과의 authoritative source다. 승인된 private manual grade adjustment가 있으면 보고서의 effective grade는 canonical 자동 점수와 adjustment를 함께 사용한다.

경로 예:

```text
records/section01/week01.json
```

Excel은 canonical record를 읽어 생성하는 파생 artifact다.

절대:

```text
Excel → canonical record
```

역방향 import를 만들지 않는다.

---

# 18. Canonical overwrite 금지

기존 record:

```text
records/sectionXX/weekXX.json
```

가 존재하면 일반 grading으로 덮어쓰지 않는다.

정상 동작:

```text
existing record
+ normal grading
→ RECORD_ALREADY_EXISTS
```

재채점은 명시적:

```text
--regrade
```

만 허용한다.

---

# 19. Regrade

Regrade:

```text
기존 canonical
→ archive
→ archive 검증
→ revision + 1
→ 새 canonical atomic replace
```

Archive 실패 시 기존 canonical을 유지한다.

손상된 canonical record를 자동 덮어쓰지 않는다.

---

# 20. Excel

Excel은:

```text
canonical records
→ gradebook
→ XLSX
```

으로만 생성한다.

Excel report 생성 중 GitHub API를 호출하지 않는다.

공식 출력 구조:

```text
output/
└─ excel/
   ├─ week01_results.xlsx
   ├─ week02_results.xlsx
   ├─ ...
   └─ final_practical_grade.xlsx
```

주차 workbook:

```text
채점기준
SectionXX...
요약
```

최종 workbook:

```text
SectionXX...
전체
주차별현황
```

---

# 21. Excel score semantics

Canonical:

```text
1.0 → numeric 1.0
0.5 → numeric 0.5
0.0 → numeric 0.0
null → blank
```

미래/미채점 week:

```text
blank
```

실제 0.0과 빈 셀을 혼동하지 않는다.

---

# 22. Excel formula injection

학생/Repository/API에서 유래한 문자열은 untrusted text다.

다음으로 시작하는 외부 문자열이 Excel formula가 되지 않도록 한다.

```text
=
+
-
@
```

중앙화된 `safe_excel_text()` 또는 동등한 함수를 사용한다.

Student ID, GitHub ID, repository, SHA, section ID는 text로 유지한다.

---

# 23. Final practical score

최종 실습 성적은 실제 주차별 max score를 사용한다.

개념:

```text
earned
────────────── × final_practice_weight
actual possible
```

주차별 배점이 같다고 가정하지 않는다.

Required week 중 하나라도:

```text
null
MANUAL_REVIEW
UNVERIFIABLE
ERROR
missing
```

이면 최종 실습 성적을 숫자로 확정하지 않는다.

```text
final score = blank
```

실제 `0.0`은 resolved score이므로 계산에 포함한다.

---

# 24. Private local files

다음 파일/디렉터리는 Git에 올라가면 안 된다.

```text
.env
config.json
data/students.csv
records/
archive/
output/
```

`.vscode/`는 현재 프로젝트 정책상 local-only다.

실제 교수/조교 계정은 local `config.json`에만 둔다.

실제 학생 정보는 local `data/students.csv`에만 둔다.

---

# 25. Public example files

Git에 올릴 수 있는 공개 템플릿:

```text
.env.example
config.example.json
data/students.example.csv
rubrics/*.json
```

Example 파일에는 실제 수업 정보나 실제 학생 정보를 넣지 않는다.

---

# 26. 절대 금지 Git 명령 습관

실제 수업 데이터를 사용하는 환경에서는 가능한 한 다음을 피한다.

```text
git add .
git add -A
```

특히 private data가 존재하는 상태에서 blindly stage하지 않는다.

명시적 safe path staging을 우선한다.

금지:

```text
git add -f config.json
git add -f data/students.csv
git add -f records/
git add -f output/
```

---

# 27. Git mutation

Agent는 사용자가 명시적으로 요청하지 않는 한 다음을 하지 않는다.

```text
git add
git commit
git push
```

Pre-commit review 요청에서는:

```text
검증
→ safe staging
→ staged diff 검토
→ commit 직전 STOP
```

까지만 수행한다.

---

# 28. 실제 운영 순서

실제 주차 운영은 다음 순서를 권장한다.

```text
1. GitHub 인증 확인
2. Preflight
3. Dry Run
4. Dry Run 결과 검토
5. 필요하면 --details 표본 검증
6. 실제 Grade
7. canonical record 확인
8. Weekly Excel 생성
```

명령 예:

```powershell
gh auth status

.\.venv\Scripts\python.exe main.py preflight --week 1 --section 01

.\.venv\Scripts\python.exe main.py grade --week 1 --section 01 --dry-run

.\.venv\Scripts\python.exe main.py grade --week 1 --section 01 --dry-run --details

.\.venv\Scripts\python.exe main.py grade --week 1 --section 01
```

Weekly Excel:

```powershell
.\.venv\Scripts\python.exe main.py week-report --week 1
```

Final Excel:

```powershell
.\.venv\Scripts\python.exe main.py final-report
```

---

# 29. Dry Run

`--dry-run`은 실제 GitHub evidence를 수집하고 판정할 수 있지만:

```text
records/
archive/
output/
```

에 production artifact를 만들면 안 된다.

Dry Run은 grading policy를 검증하기 위한 안전 단계다.

---

# 30. Dry Run details

기본 `--dry-run`은 aggregate 중심으로 출력한다.

`--dry-run --details`는 운영 검증을 위해 최소한의 식별자만 보여줄 수 있다.

권장:

```text
student_id
status
reason
evidence source
```

금지:

```text
full README
repository URL
raw API response
token
complete roster
```

---

# 31. Preflight

Preflight는 실제 채점 전 BLOCKER/WARNING/INFO를 구분해야 한다.

BLOCKER 예:

- private config tracked
- roster tracked
- authentication 없음
- malformed rubric
- invalid deadline
- unknown section/week

WARNING 예:

- 일부 학생 GitHub 미등록
- manual review 예상

INFO 예:

- student count
- registered count
- effective deadline
- evidence policy

---

# 32. 실제 채점 전 생산 게이트

실제 `grade`를 실행하기 전에 가능하면 다음을 확인한다.

```text
PREFLIGHT_READY
+
dry-run 결과가 실제 rubric과 일치
+
known-valid sample이 잘못 0점 처리되지 않음
```

수업 규칙을 수정한 직후에는 반드시 다시 dry-run 한다.

---

# 33. Known-valid false-negative 금지

수동으로 확인한 정상 제출 사례가:

```text
NOT_SUBMITTED
0.0
```

으로 판정된다면 실제 grading을 중단한다.

그 상태에서 canonical record를 생성하지 않는다.

먼저 evidence selection logic 또는 rubric을 수정한다.

---

# 34. 테스트 데이터

Tracked tests에서는 반드시 fictional data만 사용한다.

실제:

- 학생 이름
- 학번
- GitHub ID
- repository
- 교수 계정
- 조교 계정
- 실제 grade

를 fixture로 복사하지 않는다.

실제 문제를 regression test로 만들 때는 동일한 evidence shape만 fictional fixture로 재현한다.

---

# 35. 테스트

변경 후 가능한 한 전체 offline suite를 실행한다.

기본 명령:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

추가 검증:

```text
Python compile/syntax
project imports
pip check
git diff --check
```

Generated cache는 repository 정책에 따라 정리한다.

---

# 36. Network-dependent tests

기본 pytest는:

```text
GitHub CLI
token
internet
```

없이도 실행 가능해야 한다.

Live test는 explicit opt-in이어야 한다.

실제 학생 repository를 mutation test에 사용하지 않는다.

---

# 37. Windows 기준

주 개발 환경은 Windows + PowerShell이다.

파일 처리에서는:

- Windows path behavior
- locked XLSX
- file handle close
- `os.replace`
- atomic temp file
- CRLF/LF warning

을 고려한다.

LF/CRLF 안내 자체를 오류로 오판하지 않는다.

---

# 38. 문서 언어

Tracked Markdown 설명:

```text
주로 한국어
```

기술 identifier:

```text
English 유지
```

예:

```text
PushEvent
GradeResult
README.md
commit SHA
MANUAL_REVIEW
UNVERIFIABLE
```

을 억지로 번역하지 않는다.

---

# 39. 코드 주석 및 docstring

설명형 주석/docstring은 주로 한국어로 작성한다.

주석은 WHAT보다 WHY를 설명한다.

좋은 예:

```python
# PushEvent가 없다는 이유만으로 미제출을 확정하지 않는다.
# 해당 rubric이 허용하는 commit-history fallback을 먼저 검사한다.
```

나쁜 예:

```python
# event 검사
# 나중에 수정
```

---

# 40. GitHub publication rule

Tracked file에 쓰기 전에 항상 다음을 확인한다.

> 이 내용이 GitHub history에 영구적으로 남아도 괜찮은가?

아니라면 tracked file에 넣지 않는다.

금지:

- 실제 학생 데이터
- 실제 성적
- private GitHub account information
- token
- local absolute path
- AI conversation reference
- temporary debug note

---

# 41. README와 USAGE

`README.md`:

```text
프로젝트 개요 + Quick Start
```

`docs/USAGE.md`:

```text
실제 TA 운영 매뉴얼
```

역할을 분리한다.

README에 전체 운영 매뉴얼을 중복하지 않는다.

---

# 42. Rubric 수정 시

주차 채점 기준이 변경되면 먼저 rubric 표현이 가능한지 확인한다.

가능하면 Python 로직에 주차 특례를 추가하지 않는다.

우선:

```text
rubric field
configuration
generic decision logic
```

순서로 해결한다.

새 rubric 기능이 정말 필요할 때만 generic model을 확장한다.

---

# 43. Rubric regression

새 Week 정책을 구현하면서 기존 future rubric capability를 제거하지 않는다.

예를 들어 Week 1에서:

```text
branch enforcement false
```

라고 해서 branch 기능 자체를 삭제하지 않는다.

Week 1에서:

```text
0.5 없음
```

이라고 해서 `IDENTITY_PARTIAL` scoring mode를 삭제하지 않는다.

Week-specific behavior와 system capability를 구분한다.

---

# 44. GradeResult 변경

GradeResult 또는 canonical schema에 필드를 추가할 때는 반드시 확인한다.

- Phase 5 record validation
- round-trip serialization
- regrade/archive
- Phase 6 gradebook reconstruction
- Excel generation
- tests

한 계층만 수정하고 downstream을 깨뜨리지 않는다.

---

# 45. Canonical schema 변경

Production canonical record가 이미 존재하는 경우 schema 변경은 매우 신중하게 한다.

현재 실제 Week 1 record가 아직 생성되지 않았다면 migration 요구는 낮지만, generic schema compatibility는 유지한다.

Schema version을 조용히 변경하지 않는다.

---

# 46. Excel 변경

Excel column/sheet 구조 변경 시:

- canonical source는 변경하지 않는다.
- Excel만 보고 grading logic을 수정하지 않는다.
- `output/`은 계속 ignored 한다.
- 실제 XLSX를 tracked fixture로 추가하지 않는다.

---

# 47. 실제 학생 정보 출력

Terminal 기본 출력은 PII를 최소화한다.

Aggregate mode:

```text
count
status
summary
```

위주.

Details mode에서 필요한 경우:

```text
student_id
```

정도만 사용한다.

이름/Repository URL 전체를 기본 출력하지 않는다.

---

# 48. 오류 발생 시

실제 grading 중 이상한 결과가 나오면 바로 점수를 확정하지 않는다.

먼저 다음 중 어디의 문제인지 분류한다.

```text
RUBRIC_ERROR
CONFIGURATION_ERROR
EVIDENCE_MODEL_ERROR
GITHUB_API_LIMITATION
AUTHENTICATION_ERROR
REPOSITORY_FIXTURE_PROBLEM
IMPLEMENTATION_BUG
```

정확한 원인을 확인하기 전에는 학생에게 불리한 방향으로 추측하지 않는다.

---

# 49. 변경 보고서

상당한 변경 후에는 최소한 다음을 보고한다.

```text
변경 파일
변경 정책
테스트 결과
privacy/security 결과
실제 grading 수행 여부
remaining blocker
readiness
```

실제 학생별 상세 성적은 요청받지 않는 한 보고서에 나열하지 않는다.

---

# 50. 최종 불변식

항상 다음을 유지한다.

```text
실제 수업 규칙
> generic grader assumption
```

```text
rubric
> hidden implementation default
```

```text
reliable failure
→ 0.0
```

```text
technical uncertainty
→ null
```

```text
PushEvent absence
≠ automatic NOT_SUBMITTED
```

```text
canonical JSON
= authoritative automatic grading record

private manual grade adjustment
= human-approved effective-grade correction
```

```text
Excel
= derived report
```

```text
real private data
≠ Git tracked data
```

```text
dry-run first
→ real grading later
```

학생 성적을 결정하는 시스템이므로 false negative를 줄이기 위해 보수적으로 판단하되, 실제 rubric에서 명시적으로 허용한 evidence는 빠뜨리지 않는다.
```

이 `AGENTS.md`의 가장 중요한 부분은 사실 마지막에 있는 이 세 규칙입니다.

```text
실제 수업 규칙 > generic grader assumption

rubric > hidden implementation default

PushEvent absence ≠ automatic NOT_SUBMITTED
