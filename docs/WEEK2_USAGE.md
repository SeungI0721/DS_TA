# Week 2 채점 및 증거 판정 Runbook

이 문서는 Week 2의 완전한 운영 명세다. 실제 채점 시 원본 PDF나 별도 정답 코드를 요구하지 않는다. 자동 checker의 독립 oracle과 `rubrics/week02.json`이 아래 정책을 구현한다.

## 점수와 분반 매핑

Week 2는 네 개의 독립 component를 합산하며 각 component는 `0.25`, 총점은 `1.00`이다. 가능한 자동 점수는 `0.00`, `0.25`, `0.50`, `0.75`, `1.00`이다.

| 분반 | Project | Practice | Checker | 배점 |
| --- | --- | ---: | --- | ---: |
| 01 | `week02-01` | 1 | `MAX_VALUE` | 0.25 |
| 01 | `week02-02` | 3 | `NEGATIVE_COUNT` | 0.25 |
| 01 | `week02-03` | 5 | `MAX_INDEX_FIRST` | 0.25 |
| 01 | `week02-04` | 7 | `ARRAY_COMPARE_MAE` | 0.25 |
| 02 | `week02-01` | 2 | `MIN_VALUE` | 0.25 |
| 02 | `week02-02` | 4 | `POSITIVE_SUM_AVERAGE` | 0.25 |
| 02 | `week02-03` | 6 | `MIN_INDEX_FIRST` | 0.25 |
| 02 | `week02-04` | 7 | `ARRAY_COMPARE_MAE` | 0.25 |

## 공식 마감과 historical snapshot

공식 마감은 `2026-09-09 23:59 KST`, 비교 해상도는 `MINUTE`다. 따라서 `23:59:59 KST`까지 같은 마감 분으로 인정하고 `2026-09-10 00:00:00 KST`부터 늦은 제출이다. 공지 시각을 초 단위 공지로 표현하지 않는다.

제출 시작 하한, late partial-credit window, branch 이름 제한은 없다. `PushEvent`를 우선 사용하고 없으면 `commit.committer.date` 기반 commit history fallback을 사용한다. 언제나 마감 전 최종 snapshot 하나만 검사한다. 더 이른 정상 구현을 뒤의 마감 전 commit이 삭제·손상했다면 이전 상태를 찾아 점수를 주지 않으며, 마감 뒤 수정이나 삭제도 점수에 반영하지 않는다.

## Practice 1–7 명세

1. `MAX_VALUE`: 정수 배열 `{3,7,1,9,4,6,2}`를 pointer 기반으로 순회하고 첫 원소로 최댓값을 초기화하여 결과 `9`를 산출한다. 함수명과 출력 문구는 자유다.
2. `MIN_VALUE`: 같은 배열에서 최솟값 `1`을 산출한다.
3. `NEGATIVE_COUNT`: `{3,-1,-4,9,-2,6,0}`을 pointer 기반으로 순회하여 `x < 0`인 원소 3개만 센다. 0은 음수가 아니다.
4. `POSITIVE_SUM_AVERAGE`: `{3,-1,4,-2,6,0,2}`에서 `x > 0`만 사용해 합 `15`, 개수 `4`, 평균 `3.75`를 계산한다. 0은 양수가 아니며 양수가 없을 때 0으로 나누지 않고 zero-safe 결과를 처리한다.
5. `MAX_INDEX_FIRST`: `{3,7,1,9,4,9,2}`의 최대값 첫 index `3`을 산출한다. 중복 최대값의 뒤 index `5`는 오답이다.
6. `MIN_INDEX_FIRST`: `{3,7,1,9,1,6,2}`의 최소값 첫 index `2`를 산출한다. 뒤 index `4`는 오답이다.
7. `ARRAY_COMPARE_MAE`: `A={10,20,30,40,50}`, `B={12,18,33,37,55}`에서 A 평균 `30.0`, B 평균 `31.0`, 대응 절대 오차 `2,2,3,3,5`, 그리고 `sum(|A[i]-B[i]|)/N`으로 MAE `3.0`을 계산한다.

Practice 7 PDF 예시의 `3.4`는 산술 오류다. 명시된 공식과 skeleton의 `errSum / n`이 authoritative하므로 checker는 `3.0`을 사용한다.

## Content checker 정책

선택된 SHA의 각 project 아래에서 `.c` 파일을 재귀 검색한다. `build`, `Debug`, `Release`, `x64`, `generated`, `obj`, `bin` 산출물은 제외하며 `main.c`, 특정 함수명, 변수명, 정확한 `printf` 문구를 요구하지 않는다. 여러 C 파일은 함께 검사한다.

Checker는 임시 directory에 source 복사본을 만들고 지원 compiler가 있을 때만 제한된 시간과 출력 크기로 실행한다. Windows에서는 현재 shell의 `cl.exe`와 Visual Studio 설치 metadata를 먼저 확인한 뒤 `clang`, `gcc` 순서로 탐색하며, Visual Studio 개발자 환경은 compiler subprocess에만 적용한다. GCC/Clang과 MSVC의 compile option은 분리한다. 숫자 의미와 필요한 값의 개수를 검사하며 장식 문자열, 언어, 공백, 출력 순서를 exact match하지 않는다. Project 부재, relevant C source 부재, 명확한 실행 오답은 `FAIL/0.00`이다. Compiler 부재, source/API 조회 실패, checker 내부 오류처럼 학생 책임으로 확정할 수 없는 상태는 `UNVERIFIABLE/null`이다. 하나라도 `UNVERIFIABLE`이면 자동 총점도 `null`이다.

Practice 1과 3의 pointer 처리는 명시적 요구다. 알려진 동등 pointer parameter 표현은 인정하고, 특이한 구현이라 자동 판정이 불가능하면 0점 대신 manual review로 남긴다.

Week 2는 README, collaborator, branch 이름, repository 이름, commit message, 정확한 source 파일명·함수명·출력 문구를 채점하지 않는다.

## 판정 표시와 수동 검토

`--dry-run --details`와 주차 Excel은 component 결과와 사유를 `한국어 설명 (INTERNAL_CODE)`로 표시한다. `정상 (PASS)`은 충족, `미충족 (FAIL)`은 신뢰 가능한 학생 측 실패, `수동 확인 필요 (UNVERIFIABLE)`은 자동 판정을 확정할 수 없어 `null`로 둔 상태다.

- `프로젝트 폴더를 찾을 수 없음 (PROJECT_MISSING)`: 마감 snapshot에 해당 project 경로가 없다.
- `채점 가능한 C 소스 파일을 찾을 수 없음 (NO_RELEVANT_SOURCE)`: 검증할 관련 `.c` 파일이 없다.
- `동일한 극값 중 첫 번째 인덱스를 반환하지 않음 (FIRST_MATCH_RULE_INCORRECT)`: 첫 index 규칙 미충족이다.
- `평균 절대 오차(MAE) 계산이 올바르지 않음 (MAE_CALCULATION_INCORRECT)`: authoritative MAE 계산과 다르다.
- `계산 로직을 자동으로 확정할 수 없음 (COMPUTATION_UNVERIFIABLE)`: 학생 실패로 단정하지 않고 수동 검토한다.
- `채점 환경에서 실행 검증 불가 (GRADER_ENVIRONMENT_FAILURE)`와 `자동 채점기 내부 오류 (CHECKER_ERROR)`: 기술적 불확실성이므로 `0.0`으로 바꾸지 않는다.

표시 문구는 점수나 canonical 의미를 변경하지 않는다.

## 운영 절차

```powershell
.\.venv\Scripts\python.exe main.py preflight --week 2 --section 01
.\.venv\Scripts\python.exe main.py preflight --week 2 --section 02

.\.venv\Scripts\python.exe main.py grade --week 2 --section 01 --dry-run --details
.\.venv\Scripts\python.exe main.py grade --week 2 --section 02 --dry-run --details

.\.venv\Scripts\python.exe main.py grade --week 2 --section 01
.\.venv\Scripts\python.exe main.py grade --week 2 --section 02

.\.venv\Scripts\python.exe main.py manual-review-report --week 2
.\.venv\Scripts\python.exe main.py import-manual-review --week 2 --dry-run
.\.venv\Scripts\python.exe main.py import-manual-review --week 2
.\.venv\Scripts\python.exe main.py week-report --week 2
```

`preflight`는 fictional 최소 C 프로그램을 compile하고 제한 시간 안에 실행하는 probe까지 통과해야 `INFO C_TOOLCHAIN_AVAILABLE`을 출력한다. 실행 파일이 보이더라도 compile 또는 runtime probe가 실패하면 `BLOCKER C_TOOLCHAIN_UNAVAILABLE`이며, 해결 전 production grading을 수행하지 않는다. 이 검사는 C 실행 component가 있는 rubric에만 적용되므로 Week 1에는 영향을 주지 않는다.

Dry Run과 표본 검토가 끝난 뒤에만 실제 grading을 수행한다. 생성된 canonical에서 null component가 있으면 수동 검토 workbook에는 해당 component만 표시된다. TA가 입력하는 `수동확정 점수`는 component 부분점수가 아니라 해당 학생의 최종 Week 2 총점이다. 먼저 import `--dry-run`을 확인한 뒤 실제 import하고 주차 보고서를 재생성한다.

수동으로 승인한 예외는 canonical JSON이 아니라 private `data/manual_grade_adjustments.csv`에 기록한다. Week 2에서 허용되는 adjustment 점수는 `0.00`, `0.25`, `0.50`, `0.75`, `1.00`뿐이다. 일반 주차 Excel은 성적 입력 원본으로 사용하지 않는다.
