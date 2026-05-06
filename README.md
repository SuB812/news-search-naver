# 📰 AI 최신 뉴스 검색 & 자동 저장기

## 1. 프로젝트 개요

본 프로젝트는 사용자가 입력한 키워드를 기반으로 최신 뉴스 기사를 검색하고, AI를 활용해 기사 내용을 요약한 뒤 Supabase 데이터베이스에 자동 저장하는 Streamlit 웹 애플리케이션이다.

검색 방식은 두 가지를 지원한다.

1. **네이버 뉴스 API 검색**
2. **OpenAI Web Search 기반 검색**

사용자는 Streamlit 화면에서 검색 방식을 선택하고 키워드를 입력하면, 관련 최신 뉴스 기사 목록을 확인할 수 있다. 검색된 뉴스는 제목, 출처, 날짜, 원문 URL, 요약문과 함께 Supabase에 저장된다.

---

## 2. 주요 기능

### 2.1 뉴스 검색

사용자는 검색 방식을 선택할 수 있다.

- 네이버
- OpenAI Search

네이버 검색은 Naver News Open API를 사용하며, OpenAI Search는 OpenAI Responses API의 Web Search 도구를 사용한다.

### 2.2 AI 뉴스 요약

네이버 뉴스 검색 결과는 기사 제목과 설명을 기반으로 OpenAI GPT 모델이 핵심 내용을 2문장 내외로 요약한다.

OpenAI Search 검색 결과는 웹 검색으로 확인된 기사만을 대상으로 제목, 출처, 날짜, URL, 요약 정보를 JSON 형식으로 정리한다.

### 2.3 Supabase 자동 저장

검색된 뉴스는 검색 방식에 따라 각각 다른 Supabase 테이블에 저장된다.

| 검색 방식 | 저장 테이블 |
|---|---|
| 네이버 | `naver_news_history` |
| OpenAI Search | `openai_news_history` |

저장되는 주요 컬럼은 다음과 같다.

| 컬럼명 | 설명 |
|---|---|
| `id` | 고유 ID |
| `keyword` | 검색 키워드 |
| `title` | 뉴스 제목 |
| `source` | 뉴스 출처 |
| `news_date` | 기사 날짜 |
| `url` | 원문 URL |
| `summary` | AI 요약문 |
| `created_at` | 저장 시각 |

### 2.4 중복 저장 방지

`url` 컬럼에 `UNIQUE` 제약조건을 설정하여 같은 뉴스 URL이 중복 저장되지 않도록 한다.

### 2.5 저장된 뉴스 조회

저장된 뉴스 목록을 Streamlit 화면에서 확인할 수 있다.

조회 방식은 다음 세 가지를 지원한다.

- 네이버 저장 뉴스
- OpenAI Search 저장 뉴스
- 전체 저장 뉴스

또한 제목 또는 검색 키워드 기준으로 필터링할 수 있다.

### 2.6 CSV 다운로드

현재 화면에 표시된 저장 뉴스 데이터를 CSV 파일로 다운로드할 수 있다.

### 2.7 통계 대시보드

저장된 뉴스 데이터를 기반으로 간단한 통계 분석을 제공한다.

제공되는 통계는 다음과 같다.

- 전체 저장 기사 수
- 네이버 저장 기사 수
- OpenAI Search 저장 기사 수
- 검색 키워드 수
- 출처 수
- 검색 방식별 저장 기사 수
- 일자별 DB 저장 건수
- 키워드별 누적 저장 건수
- 출처별 기사 수 TOP 10
- 최근 저장된 기사 10건

---

## 3. 기술 스택

| 구분 | 사용 기술 |
|---|---|
| 웹 앱 프레임워크 | Streamlit |
| 데이터 처리 | pandas |
| 뉴스 검색 | Naver News Open API, OpenAI Web Search |
| AI 요약 | OpenAI GPT |
| 데이터베이스 | Supabase |
| API 요청 | requests |
| 배포 환경 | Streamlit Cloud |

---

## 4. 프로젝트 구조

```text
NEWSEARCH/
├── app_news_naver_openai_search.py
├── requirements.txt
└── README.md
