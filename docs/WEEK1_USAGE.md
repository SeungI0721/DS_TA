# DS-TA Week 1 사용 가이드

이 문서는 검증된 Week 1 채점 기준과 실제 운영 절차를 재현하기 위한 runbook이다. 설치와 전체 시스템의 공통 운영 방법은 [DS-TA 사용 가이드](USAGE.md)를 참고한다. 이후 주차는 다른 rubric을 사용할 수 있으므로 이 문서의 Week 1 규칙을 자동으로 일반화하지 않는다.

Week 1은 실제 수업 repository를 대상으로 authenticated read-only Dry Run과 표본 검증을 거쳐 canonical record 및 weekly Excel 생성까지 운영 검증을 완료했다. 이 문서는 실제 학생 식별정보나 점수 분포를 포함하지 않는다.

## 1. Week 1 개요

Week 1 작업 흐름은 다음과 같다.

```text
GitHub repository
→ submission evidence
→ Week 1 rubric
→ GradeResult
→ canonical JSON
→ weekly Excel
```

canonical JSON은 authoritative grade record다. Excel은 canonical record에서 재생성하는 derived report이며 성적 원본이 아니다.

## 2. Week 1 확정 채점 기준

Section 01과 Section 02는 모두 다음 deadline을 사용한다.

```text
2026-09-03T23:59:59+09:00
```

최대 점수는 `1.0`, scoring mode는 `BINARY`이며 `0.5`는 없다.

`1.0`을 받으려면 다음 두 조건을 모두 만족해야 한다.

- 허용된 증거로 deadline까지 repository root의 `README.md`가 존재했음이 확인된다.
- 설정된 assistant/TA collaborator가 현재 `ACTIVE`다.

`0.0`은 empty repository, deadline 이후 제출만 존재, 적격 historical snapshot의 root README 누락, assistant collaborator의 확실한 `MISSING`처럼 학생 측 실패가 신뢰성 있게 확인된 경우에만 사용한다.

`null`은 `MISSING_REPOSITORY_INFO`, API/auth/permission 실패, 불충분한 history, 해결할 수 없는 SHA, collaborator `UNKNOWN/ERROR`처럼 점수를 확정할 수 없는 경우에 사용한다.

Week 1은 professor collaborator, README 내부 학번·이름, 특정 branch 이름, submission start boundary, late window 완료, PushEvent 자체, `0.5` partial score를 요구하지 않는다.

## 3. Week 1 제출 증거 정책

### PUSH_EVENT_CONFIRMED

적격 PushEvent가 있으면 이 경로를 우선한다.

- actor가 학생 GitHub ID와 일치해야 한다.
- ref는 `refs/heads/...` 형식의 branch ref여야 한다. `refs/tags/...`는 제외한다.
- `created_at`이 deadline 이하여야 하며 lower boundary는 적용하지 않는다.
- deadline 이전의 최신 적격 PushEvent를 선택한다.
- `payload.head` commit SHA를 historical snapshot으로 사용한다.
- 그 SHA의 repository root에서 `README.md`를 확인한다.

### COMMIT_HISTORY_CONFIRMED

적격 PushEvent가 없으면 Week 1 rubric이 허용한 commit-history fallback을 사용한다.

- GitHub REST API가 반환한 commit history를 조회한다.
- cutoff에는 `commit.committer.date`를 사용하고 `commit.author.date`는 사용하지 않는다.
- deadline 이전 후보를 최신순으로 검사한다.
- root `README.md`가 존재하는 가장 최신 후보의 정확한 SHA를 snapshot으로 사용한다.
- commit pagination은 현재 최대 10페이지로 제한하며, 그 범위로 absence를 확정할 수 없으면 `UNVERIFIABLE/null`로 남긴다.

`PushEvent.created_at`은 GitHub 측 push 시각이므로 더 강한 증거다. `commit.committer.date`는 더 약한 Git metadata이지만, 유효한 저장소에서 과거 PushEvent가 보이지 않을 수 있으므로 Week 1 정책이 fallback으로 명시적으로 허용한다.

### 기타 GitHub event

`CreateEvent`와 `MemberEvent`는 provenance를 보강할 수 있지만 단독으로 README 제출을 증명하지 않는다.

## 4. Week 1에서 사용하지 않는 조건

| 항목 | Week 1 적용 여부 |
| --- | --- |
| 제출 deadline | O |
| submission start boundary | X |
| 특정 branch 이름 | X |
| root `README.md` | O |
| README 학번 | X |
| README 이름 | X |
| assistant collaborator | O |
| professor collaborator | X |
| PushEvent 필수 | X |
| late window | X |
| `0.5` | X |

## 5. 실행 전 필요한 파일

- `config.json`: 실제 과목, 분반, GitHub 계정과 API 설정을 담는 private local 설정
- `data/students.csv`: 실제 roster와 GitHub 등록정보를 담는 private local 파일
- `rubrics/week01.json`: 공개 가능한 Week 1 채점 기준

새 환경에서는 `config.example.json`과 `data/students.example.csv`를 복사해 private 파일을 준비한다. 공개 template에는 fictional 값만 유지한다.

## 6. 학생 CSV 형식

```csv
section,student_id,name,github_id,repository
01,EXAMPLE001,Example Student,example-student,example-student/example-repository
```

`repository`는 `owner/repository`로 해석될 수 있어야 한다. `github_id`와 `repository`를 모두 비워 두는 것은 허용되며, 이 경우 `MISSING_REPOSITORY_INFO`, `MANUAL_REVIEW`, `score = null`이 된다. 미등록을 `NOT_SUBMITTED/0.0`으로 바꾸거나 해당 학생 때문에 분반 전체를 중단하지 않는다.

## 7. GitHub 인증 확인

```powershell
gh auth status
```

활성 계정이 있고 인증 token이 유효하다는 결과를 확인한다. 인증이 실패하면 다음 명령으로 로그인한 뒤 다시 확인한다.

```powershell
gh auth login
```

인증이 정상화되기 전에는 dry-run 결과를 신뢰하거나 실제 채점을 진행하지 않는다.

## 8. VS Code에서 실행

VS Code에서 `Terminal` → `Run Task...`를 선택하면 현재 로컬 설정에 다음 Task가 제공된다.

- `DS-TA: Preflight`
- `DS-TA: Dry Run`
- `DS-TA: REAL Grade Section/Week`
- `DS-TA: Regrade Section/Week`
- `DS-TA: Week Report`
- `DS-TA: Final Report`
- `DS-TA: Run Tests`

`.vscode/`는 현재 프로젝트 정책상 local-only이며 tracked Task가 있다고 가정해서는 안 된다.

## 9. Preflight

```powershell
.\.venv\Scripts\python.exe main.py preflight --week 1 --section 01
.\.venv\Scripts\python.exe main.py preflight --week 1 --section 02
```

성공 시 마지막에 `PREFLIGHT_READY`가 출력된다. Week 1에서는 다음 내용을 확인한다.

- effective deadline: `2026-09-03T23:59:59+09:00`
- submission start boundary: `NOT_ENFORCED`
- submission branch policy: `ANY_BRANCH_REF`
- late window: `LATE_WINDOW_NOT_REQUIRED`
- accepted evidence sources: `PUSH_EVENT, COMMIT_HISTORY`
- GitHub authentication: available
- event settle 시각 경과

`BLOCKER`가 있으면 진행하지 않는다. `WARNING`은 검토가 필요하지만 학생 GitHub 미등록처럼 해당 학생을 null로 유지할 수 있는 상태다. `INFO`는 현재 설정과 정책의 확인 정보다.

## 10. Dry Run

```powershell
.\.venv\Scripts\python.exe main.py grade --week 1 --section 01 --dry-run
.\.venv\Scripts\python.exe main.py grade --week 1 --section 02 --dry-run
```

Dry Run은 실제 read-only GitHub evidence acquisition과 점수 계산을 수행한다. canonical record, archive, production Excel을 만들지 않으며 GitHub repository를 수정하지 않는다.

Aggregate 출력에서 `1.0`, `0.5`, `0.0`, `null`, 제출 상태, null 원인과 evidence-source count를 확인한다. Week 1의 `0.5`는 반드시 0이어야 한다.

## 11. Dry Run 상세 확인

```powershell
.\.venv\Scripts\python.exe main.py grade --week 1 --section 01 --dry-run --details
```

상세 출력은 다음 그룹을 분리한다.

- `Resolved 1.0 students`: student ID와 `PUSH_EVENT_CONFIRMED` 또는 `COMMIT_HISTORY_CONFIRMED`
- `Resolved 0.0 students`: student ID와 `README_MISSING`, `NOT_SUBMITTED`, `LATE`, `ASSISTANT_COLLABORATOR_MISSING` 등의 이유
- `Unresolved students`: student ID와 `MISSING_REPOSITORY_INFO`, `UNVERIFIABLE` 등의 이유

`INSUFFICIENT_EVIDENCE`는 신뢰할 수 있는 제출 snapshot을 확정하지 못했음을 뜻한다. 상세 출력에도 이름, repository URL, README 내용, raw API response 또는 token을 노출하지 않는다.

## 12. Dry Run 결과 검증 방법

새 rubric을 처음 production에 사용할 때는 dry-run 결과를 표본 검증한다.

- 확정 `0.0` 사례 2–3개를 확인한다.
- 확정 `1.0` 사례 1–2개를 확인한다.
- 의심스러운 저장소는 exact API timestamp, commit history, historical README snapshot, collaborator 상태를 비교한다.

GitHub UI의 `4 days ago`, `last week` 같은 상대 시각은 deadline 판정에 사용하지 않는다.

## 13. 직접 GitHub 증거 확인하기

다음 명령은 fictional placeholder를 사용하는 read-only 점검 예시다.

전체 repository event:

```powershell
gh api repos/<owner>/<repo>/events --paginate --jq '.[] | [.type, .created_at, .actor.login, (.payload.ref // ""), (.payload.head // "")] | @tsv'
```

PushEvent만 확인:

```powershell
gh api repos/<owner>/<repo>/events --paginate --jq '.[] | select(.type=="PushEvent") | [.created_at, .actor.login, .payload.ref, .payload.head] | @tsv'
```

Commit history 확인:

```powershell
gh api repos/<owner>/<repo>/commits --paginate --jq '.[] | [.sha, .commit.author.date, .commit.committer.date, .commit.message] | @tsv'
```

`Z`로 끝나는 GitHub API timestamp는 UTC이며 KST는 UTC보다 9시간 빠르다. PushEvent가 있으면 `created_at`을 우선하고, fallback cutoff에는 `commit.committer.date`를 사용한다. `commit.author.date`는 Week 1 cutoff 증거가 아니다.

## 14. 실제 채점

다음 조건을 모두 확인한 뒤에만 실행한다.

```text
PREFLIGHT_READY
+ dry-run 검토 완료
+ known-valid 표본이 잘못 거절되지 않음
```

```powershell
.\.venv\Scripts\python.exe main.py grade --week 1 --section 01
.\.venv\Scripts\python.exe main.py grade --week 1 --section 02
```

이 명령은 canonical record를 생성한다.

## 15. Canonical record

예상 경로:

```text
records/section01/week01.json
records/section02/week01.json
```

Canonical record에는 실제 성적과 증거가 포함되며 private/local source of truth다. Git에서 무시하고, 임의로 편집하지 않는다. 일반 grading은 기존 section/week record를 덮어쓰지 않는다. Numeric `0.0`과 unresolved `null`은 서로 다른 값으로 유지한다.

## 16. 재채점

```powershell
.\.venv\Scripts\python.exe main.py grade --week 1 --section 01 --regrade --regrade-reason "<reason>"
```

Regrade는 기존 canonical record를 `archive/sectionXX/weekXX/...`에 보존하고 검증한 뒤 revision을 증가시켜 새 canonical을 설치한다. Excel을 다시 만들기 위한 용도로 regrade하지 않는다.

## 17. Week 1 Excel 생성

```powershell
.\.venv\Scripts\python.exe main.py week-report --week 1
```

결과는 `output/excel/week01_results.xlsx`이며 `채점기준`, `Section01`, `Section02`, `요약` sheet를 포함한다. Canonical `1.0`과 `0.0`은 numeric cell이고 null은 blank다. 보고서 생성은 canonical record만 읽고 GitHub를 호출하지 않는다.

## 18. Excel과 canonical record의 차이

```text
canonical JSON = authoritative record
Excel = derived report
```

Excel을 삭제하면 canonical record에서 다시 생성한다. Excel을 수동 편집해도 canonical grade는 바뀌지 않는다. Excel에서 canonical record로 역방향 import하지 않는다.

## 19. 자주 발생하는 상태

| 상태 | 의미 | 점수 | 권장 조치 |
| --- | --- | --- | --- |
| `MISSING_REPOSITORY_INFO` | GitHub 등록정보 누락 | null | roster 등록정보 확인 |
| `README_MISSING` | 적격 historical SHA의 root README 없음 | 0.0 | 선택 SHA와 root 경로 표본 확인 |
| `NOT_SUBMITTED` | empty repository 등 신뢰 가능한 제출 부재 | 0.0 | commit endpoint와 저장소 초기화 여부 확인 |
| `LATE` | commit 또는 제출 증거가 deadline 이후에만 존재 | 0.0 | exact API timestamp 확인 |
| `PUSH_EVENT_CONFIRMED` | PushEvent가 선택 snapshot을 확정 | 해당 판정 | selected SHA 확인 |
| `COMMIT_HISTORY_CONFIRMED` | commit-history fallback이 snapshot을 확정 | 해당 판정 | committer date와 SHA 확인 |
| `INSUFFICIENT_EVIDENCE` | 증거가 부족해 snapshot을 확정하지 못함 | null | history/API 범위 확인 |
| `API_ERROR` | 실제 GitHub API 처리 실패 | null | 인증, status, rate limit 확인 |
| `MANUAL_REVIEW` | 자동 점수 확정 불가 | null | 기록된 reason 검토 |
| `UNVERIFIABLE` | history 또는 SHA를 신뢰성 있게 검증할 수 없음 | null | API 응답과 coverage 확인 |

## 20. Empty repository 처리

접근 가능한 repository에 commit이 하나도 없으면 신뢰 가능한 non-submission으로 판정한다.

```text
empty repository → NOT_SUBMITTED / 0.0
post-deadline commit only → LATE / 0.0
actual API failure → ERROR / null
```

정상적인 빈 commit 목록은 API 실패가 아니다.

## 21. README historical check

현재 branch에 README가 있다는 사실만으로 deadline 이전 제출을 증명하지 않는다. Grader는 PushEvent의 `payload.head` 또는 commit-history fallback이 선택한 historical SHA에서 repository-root `README.md`를 확인한다.

```text
pre-deadline selected SHA에 root README 존재 → README 조건 충족
README가 post-deadline commit에만 존재 → 1.0 대상 아님
```

Nested README는 root README를 대신하지 않는다.

## 22. 개인정보와 Git

다음 경로는 실제 계정, 학생 정보 또는 성적을 포함할 수 있으므로 commit하지 않는다.

- `.env`
- `config.json`
- `data/students.csv`
- `records/`
- `archive/`
- `output/`

실제 운영 중 `git add .`과 `git add -A`를 피하고 공개 가능한 경로만 명시적으로 선택한다. `.gitignore`는 이미 tracked 상태인 파일을 자동으로 제거하지 않는다.

## 23. 실제 운영 체크리스트

- [ ] `gh auth status` 정상
- [ ] `rubrics/week01.json`의 deadline과 정책 확인
- [ ] `config.json`과 `data/students.csv`가 Git에 비추적 상태인지 확인
- [ ] Section 01 Preflight 실행
- [ ] Section 02 Preflight 실행
- [ ] Section 01 Dry Run 실행
- [ ] Section 02 Dry Run 실행
- [ ] `0.5 = 0` 확인
- [ ] null 원인 검토
- [ ] `0.0`/`1.0` 표본 확인
- [ ] 실제 Section 01 Grade 실행
- [ ] 실제 Section 02 Grade 실행
- [ ] canonical record 확인
- [ ] `week01_results.xlsx` 생성
- [ ] Excel 요약 검토

## 24. Week 2 이후 사용 시 주의

Week 1 규칙을 Week 2 이후에 그대로 복사하지 않는다. 이후 rubric은 submission start boundary, branch enforcement, professor collaborator, README identity, partial `0.5`, late window, 다른 evidence source 또는 다른 max score를 사용할 수 있다. 항상 해당 주차의 validated rubric을 source of truth로 사용한다.
