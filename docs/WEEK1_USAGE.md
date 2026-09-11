# DS-TA Week 1 채점 운영 가이드

이 문서는 Week 1의 실제 채점 기준과 증거 판정 절차만 설명한다. 설치, 인증, 공통 CLI, canonical record, 재채점 및 Excel 생성의 일반 절차는 [DS-TA 사용 가이드](USAGE.md)를 따른다.

## 1. 확정 채점 기준

Section 01과 Section 02에 같은 기준을 적용한다.

- 공지 원문 기준 마감: `2026-09-03 23:59 KST`
- 기계 비교 cutoff: `2026-09-03T23:59:59+09:00`
- 최대 점수: `1.0`
- 허용 점수: `1.0`, `0.0`
- scoring mode: `BINARY`

초 단위가 없는 공지의 “23:59까지”를 결정적으로 비교하기 위해 해당 분의 끝을 cutoff로 정규화했다. `23:59:59`를 교수자가 직접 공지한 것으로 해석하지 않으며, `23:59:01`부터 `23:59:59`까지의 제출도 배제하지 않는다.

`1.0`은 다음 조건을 모두 신뢰성 있게 만족할 때만 부여한다.

```text
professor collaborator가 현재 ACTIVE
AND
assistant collaborator가 현재 ACTIVE
AND
선택된 마감 전 SHA에 README.md 존재
AND
(
    선택된 같은 SHA에 week01/README.md 존재
    OR
    선택된 같은 SHA에 week01-01/README.md 존재
)
```

README의 학번, 이름, 문구, 길이, 품질 및 heading은 채점하지 않는다. 특정 branch 이름, submission start boundary, late window도 적용하지 않는다. 일반 branch ref(`refs/heads/...`)는 허용하지만 tag ref(`refs/tags/...`)는 제출 branch로 인정하지 않는다.

## 2. 제출 증거와 historical snapshot

Week 1은 현재 repository 상태로 과거 제출을 추정하지 않는다. 모든 필수 경로는 하나의 선택된 historical SHA에서 정확한 대소문자와 경로로 검사한다.

### PUSH_EVENT_CONFIRMED

조건에 맞는 PushEvent가 있으면 이를 우선한다.

- rubric이 요구하는 경우 actor가 학생 GitHub ID와 일치해야 한다.
- ref는 일반 branch ref여야 한다.
- `PushEvent.created_at <= normalized cutoff`여야 한다.
- 가장 최신 적격 event의 `payload.head`를 selected SHA로 사용한다.
- 필수 경로 그룹 전체를 그 SHA에서 검사한다.

### COMMIT_HISTORY_CONFIRMED

PushEvent가 보이지 않는다는 이유만으로 미제출을 확정하지 않는다. Week 1 rubric은 commit-history fallback을 허용한다.

- `commit.committer.date`를 cutoff와 비교한다. `commit.author.date`는 사용하지 않는다.
- 마감 전 commit을 최신순으로 검사한다.
- `README.md AND (week01/README.md OR week01-01/README.md)`를 모두 만족하는 가장 최신 commit SHA를 선택한다.
- 더 최신 commit에서 필수 파일이 삭제되었을 수 있으므로 파일 존재를 단조 증가한다고 가정하지 않는다.
- 조회 범위로 absence를 확정할 수 없으면 `UNVERIFIABLE/null`로 보수적으로 처리한다.

`PushEvent.created_at`은 GitHub 측 push 시각이라는 점에서 더 강한 증거다. `commit.committer.date`는 push 시각과 동일하지 않은 Git metadata이며, Week 1 정책이 명시적으로 허용한 fallback이다.

## 3. 파일 경로 판정

Rubric의 각 `required_path_groups`는 필수이며, 한 그룹 안의 `ANY`는 후보 중 하나 이상이 존재하면 충족된다.

| 그룹 | 정확한 후보 경로 | 충족 조건 |
| --- | --- | --- |
| `repository_root_readme` | `README.md` | 존재 |
| `week_project_readme` | `week01/README.md`, `week01-01/README.md` | 둘 중 하나 이상 존재 |

`Week01/README.md`, `week1/README.md`, `week01/readme.md`, `docs/README.md` 등 rubric에 없는 경로는 자동 인정하지 않는다. 두 그룹은 반드시 같은 selected SHA에서 평가한다.

## 4. Collaborator 판정

Professor와 assistant 두 역할 모두 private `config.json`에 설정된 계정의 현재 상태를 검사한다.

- 현재 `ACTIVE`: 해당 역할 충족
- 신뢰 가능한 `MISSING`: `0.0`
- `UNKNOWN`, API/permission 오류: `null`

초대·수락 시각이 마감 전이었는지는 채점하지 않는다. 마감 후 collaborator가 추가되었더라도 채점 시점에 현재 `ACTIVE`이면 Week 1 collaborator 조건을 충족한다.

Professor 계정 철자에는 실제 성적을 바꿀 수 있는 운영상 모호성이 있었다. 계정 값을 추측하거나 공개 문서에 기록하지 않는다. 운영자가 intended account를 확인한 뒤 private `config.json`의 `operator_confirmations`에 `professor_github_identity`를 추가해야 한다. 확인 전 preflight는 `OPERATOR_CONFIRMATION_REQUIRED` BLOCKER를 반환하며 실제 grade/regrade 명령도 중단된다.

## 5. `0.0`과 `null`

신뢰 가능한 학생 측 실패만 `0.0`이다.

| 원인 | 결과 |
| --- | --- |
| accessible repository의 commit history가 실제로 비어 있음 | `EMPTY_REPOSITORY` 또는 `NOT_SUBMITTED`, `0.0` |
| 허용 가능한 commit이 모두 cutoff 이후 | `LATE`, `0.0` |
| selected SHA에 root README 없음 | `ROOT_README_MISSING`, `0.0` |
| selected SHA에 project README 두 후보 모두 없음 | `PROJECT_README_MISSING`, `0.0` |
| required professor 현재 `MISSING` | `PROFESSOR_COLLABORATOR_MISSING`, `0.0` |
| required assistant 현재 `MISSING` | `ASSISTANT_COLLABORATOR_MISSING`, `0.0` |

기술적·역사적 불확실성은 `null`이다. GitHub 등록정보 누락, 인증·권한·network·rate-limit·server 오류, 불완전한 history, 해석 불가능한 SHA, collaborator `UNKNOWN/ERROR`를 0점으로 바꾸지 않는다. Week 1에는 `0.5` 경로가 없다.

## 6. 운영 전 확인

먼저 교수자 계정 identity를 실제 공지 또는 권한 있는 운영자에게 확인한다. 값 자체는 tracked 파일이나 출력에 남기지 않는다. 그 다음 두 분반에서 preflight를 실행한다.

```powershell
.\.venv\Scripts\python.exe main.py preflight --week 1 --section 01
.\.venv\Scripts\python.exe main.py preflight --week 1 --section 02
```

`PREFLIGHT_READY` 전에 다음을 확인한다.

- scoring mode: `BINARY`
- 공지 기준: `2026-09-03 23:59 KST`
- normalized cutoff: `2026-09-03T23:59:59+09:00`
- submission start: `NOT_ENFORCED`
- branch name: `NOT_ENFORCED`
- late window: `NOT_REQUIRED`
- collaborators: professor, assistant
- paths: `README.md AND (week01/README.md OR week01-01/README.md)`
- evidence: `PUSH_EVENT, COMMIT_HISTORY`
- private operator confirmation: complete

## 7. Read-only Dry Run

오프라인 테스트가 통과하고 GitHub 인증이 유효한 경우에만 실행한다.

```powershell
.\.venv\Scripts\python.exe main.py grade --week 1 --section 01 --dry-run --details
.\.venv\Scripts\python.exe main.py grade --week 1 --section 02 --dry-run --details
```

기본 `--dry-run`은 aggregate만 출력한다. `--details`는 student ID와 최소 판정 사유만 보여준다. 이름, repository URL, README 본문, token, raw GitHub response는 출력하지 않는다.

새 rubric은 이전보다 professor collaborator와 project README 조건이 추가되었으므로 과거 점수 분포와 같을 필요가 없다. 새 `0.0` 가운데 collaborator missing, root/project README missing, late, empty repository 사례를 대표 표본으로 수동 확인한다.

## 8. Production regrade 승인 조건

다음 항목을 모두 검증하기 전에는 production regrade를 실행하지 않는다.

- professor account spelling과 intended account 확인
- 두 collaborator의 current-state 판정 확인
- root/project README의 동일 historical SHA 검사 확인
- `week01 OR week01-01` 판정 확인
- identity·branch·start boundary가 숨은 조건으로 남지 않음
- `0.5`가 불가능함
- PushEvent 부재가 자동 0점이 아님
- 전체 오프라인 테스트 통과
- authenticated Dry Run과 새 0점 표본 검토 완료

승인 후에만 기존 canonical record를 직접 덮어쓰지 않고 명시적 `--regrade` workflow로 archive한 뒤 새 revision을 만든다. 새 canonical revision이 성공한 후 `week-report --week 1`로 Excel을 재생성한다. 현재 작업에서는 이 명령들을 실행하지 않는다.
