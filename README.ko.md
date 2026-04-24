# skill-dashboard-for-kimi

CLI 스킬과 MCP 서버를 관리하는 웹 기반 대시보드입니다. 원래 [Kimi CLI](https://github.com/moonshot-ai/Kimi-CLI)용으로 개발되었지만, Claude Code, Codex CLI, OpenCode CLI 등 YAML frontmatter로 메타데이터를 관리하는 어떤 CLI와도 호환됩니다.

## 기능

- **통합 테이블**: 모든 스킬과 MCP 서버를 하나의 정렬/필터 가능한 테이블에서 확인
- **헬스 체크**: SKILL.md 존재 여부, YAML frontmatter, 설명 필드를 자동 검증
- **활성화 제어**: 스킬과 MCP 서버를 한 클릭으로 활성화/비활성화
- **인라인 편집**: Detail 모달에서 카테고리, 설명, URL을 직접 수정
- **안전한 삭제**: 확인 다이얼로그에서 "remove"를 정확히 입력해야 스킬이 삭제됨
- **카테고리 분포**: 스킬 카테고리 분포를 보여주는 가로 막대 차트
- **크로스-CLI**: Kimi, Claude Code, Codex CLI, OpenCode CLI 지원

## 요구사항

- Python 3.10+
- 최신 웹 브라우저

## 설치

### 옵션 A: Kimi CLI 스킬 (권장)

```bash
cd ~/.kimi/skills/
git clone https://github.com/ktkarchive/skill-dashboard-for-kimi.git
```

그리고 Kimi에게 말하세요:

> "스킬 대시보드를 실행해줘"

Kimi가 `scripts/skill_dashboard.py`를 실행하고 브라우저를 열어줍니다.

### 옵션 B: 독립 실행

```bash
git clone https://github.com/ktkarchive/skill-dashboard-for-kimi.git
cd skill-dashboard-for-kimi
python3 scripts/skill_dashboard.py --port 8080 --open
```

## 사용 방법

서버가 실행되면 (기본: `http://localhost:8080`):

### 1. 대시보드 열기
웹 브라우저를 열고 터미널에 표시된 URL로 접속하세요 (예: `http://localhost:8080`). 상단에 다음이 표시됩니다:
- **통계 카드** (전체, 스킬, MCP 서버, 활성, 비활성, 건강)
- **카테고리 차트** — 스킬 카테고리 분포
- **메인 테이블** — 모든 스킬과 MCP 서버 목록

### 2. 검색 및 필터
- **Search** 입력란으로 이름 필터링
- **Category** 드롭다운으로 카테고리 필터링
- **Status** 드롭다운으로 활성/비활성만 보기
- **Type** 드롭다운으로 스킬 또는 MCP 서버만 보기

### 3. 정렬
테이블 헤더를 클릭하면 해당 컬럼 기준으로 정렬됩니다:
- **Name**, **Category**, **Description**, **Health**, **Last Used**, **Last Updated**
- 다시 클릭하면 오름차순/내림차순 전환

### 4. 활성화 / 비활성화
- **Disable** 버튼으로 스킬 또는 MCP 서버 비활성화
- **Enable** 버튼으로 다시 활성화
- 비활성 항목은 ⚫ 상태 배지와 회색 버튼으로 표시

### 5. 메타데이터 편집
- 아무 행의 **Detail** 버튼 클릭
- 모달에서 **Category**, **Description**, **URL** 수정
- **Save** 버튼 누륾면 페이지 새로고침 없이 즉시 적용
- URL이 설정되면 테이블 설명 옆에 🔗 링크 이모지 표시

### 6. 스킬 삭제
- 스킬 행의 **Remove** 버튼 클릭 (MCP 서버에는 없음)
- 경고 메시지 확인
- 입력란에 정확히 `remove` 입력
- **Confirm Remove** 클릭 시 스킬 디렉토리 영구 삭제
- **Cancel** 클릭 또는 잘못 입력 시 취소

### 7. 새로고침
**Refresh** 버튼을 누륾면 스킬 디렉토리와 MCP 설정을 다시 스캔하고 테이블을 갱신합니다.

## 크로스-CLI 설정

스크립트는 기본적으로 Kimi CLI 경로를 사용합니다. 다른 CLI에서 사용하려면 `scripts/skill_dashboard.py` 상단의 경로를 주석 해제하세요:

```python
# Kimi CLI (기본):
SKILLS_DIR = Path.home() / ".kimi" / "skills"
MCP_JSON = Path.home() / ".kimi" / "mcp.json"

# Claude Code:
# SKILLS_DIR = Path.home() / ".claude" / "skills"
# MCP_JSON = Path.home() / ".claude" / "mcp.json"

# Codex CLI:
# SKILLS_DIR = Path.home() / ".codex" / "skills"
# MCP_JSON = Path.home() / ".codex" / "mcp.json"
```

## 대시보드 UI

### 통계 카드
- 전체 항목, 스킬, MCP 서버, 활성, 비활성, 건강

### 카테고리 차트
- 스킬 카테고리 분포를 보여주는 가로 막대 차트

### 테이블 컬럼
| 컬럼 | 설명 |
|------|------|
| 타입/상태 | 스킬(📦) 또는 MCP(🤖), 활성(🟢) 또는 비활성(⚫) |
| 이름 | 스킬/MCP 이름 |
| 카테고리 | 색상이 입혀진 카테고리 배지 |
| 설명 | URL이 설정되면 🔗 링크 이모지와 함께 표시 |
| 헬스 | ✅ 건강 또는 ⚠️ 문제 |
| 마지막 사용 | 마지막 사용 날짜 |
| 마지막 수정 | 파일 마지막 수정 날짜 |
| 작업 | 활성화/비활성화, 상세보기, 삭제 |

### 상세 모달
**Detail**을 클릭하면 보고 수정할 수 있는 내용:
- 카테고리
- 설명
- URL (설정 시 테이블에 🔗 링크 이모지 표시)
- 헬스 상태 및 이슈
- 참조 파일 수 (스킬)
- 명령어/인자/환경변수 (MCP 서버 — env 값은 마스킹됨)
- 태그
- 파일 경로

### 삭제 확인
스킬 행의 **Remove**를 클릭하면 확인 다이얼로그가 뜹니다. 정확히 `remove`를 입력해야 해당 스킬 디렉토리가 영구 삭제됩니다. MCP 서버는 대시보드에서 삭제할 수 없습니다.

## API 엔드포인트

| 메소드 | 엔드포인트 | 설명 |
|--------|-----------|------|
| GET | `/` | HTML 대시보드 |
| GET | `/api/skills` | JSON 스킬 목록 |
| GET | `/api/mcp` | JSON MCP 서버 목록 |
| GET | `/api/stats` | JSON 통계 |
| POST | `/api/skills/{name}/toggle` | 스킬 활성 상태 토글 |
| POST | `/api/mcp/{name}/toggle` | MCP 서버 활성 상태 토글 |
| POST | `/api/skills/{name}/update` | 스킬 메타데이터 수정 (카테고리, 설명, URL) |
| POST | `/api/mcp/{name}/update` | MCP 메타데이터 수정 (카테고리, 설명, URL) |
| POST | `/api/skills/{name}/remove` | 스킬 영구 삭제 |

## CLI 옵션

```bash
python3 scripts/skill_dashboard.py --port 8080 --open
```

| 플래그 | 설명 |
|--------|------|
| `--port` | 서버 포트 (기본: 8080) |
| `--open` | 브라우저 자동 열기 |
| `--scan` | 모든 항목 스캔 후 목록 출력 |
| `--health` | 헬스 체크 실행 |

## 데이터 저장

- **스킬**: `SKILLS_DIR/*/SKILL.md`에서 읽음
- **MCP 서버**: `MCP_JSON` (보통 `mcp.json`)에서 읽음
- **레지스트리**: `SKILLS_DIR/.skill-registry.json`에 로컬 상태 저장
  - 활성/비활성 상태 추적
  - 수정된 메타데이터 저장 (카테고리, 설명, URL)
- **외부 데이터 수집 없음**: 모든 데이터는 로컬 머신에만 머무름

## 문제 해결

| 문제 | 해결 방법 |
|------|----------|
| "Port already in use" | `--port 9000` 사용 또는 기존 프로세스 종료 |
| 스킬이 보이지 않음 | `SKILLS_DIR`이 올바른 경로를 가리키는지 확인 |
| MCP 서버가 보이지 않음 | `MCP_JSON` 파일이 존재하고 유효한 JSON인지 확인 |
| 변경사항이 저장되지 않음 | 레지스트리 파일에 쓰기 권한이 있는지 확인 |

## 라이선스

MIT
