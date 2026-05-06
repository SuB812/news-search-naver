# app_news_naver_gemini.py
# -------------------------------------------------------------------
# 네이버 뉴스 API + Gemini Google Search Grounding 뉴스 검색/요약 앱
#
# requirements.txt:
# streamlit
# pandas
# requests
# openai
# supabase
# google-genai
#
# Streamlit Secrets:
# OPENAI_API_KEY = "sk-..."
# NAVER_CLIENT_ID = "네이버_CLIENT_ID"
# NAVER_CLIENT_SECRET = "네이버_CLIENT_SECRET"
# GEMINI_API_KEY = "제미나이_API_KEY"
# SUPABASE_URL = "https://xxxx.supabase.co"
# SUPABASE_KEY = "supabase_anon_or_service_role_key"
# -------------------------------------------------------------------

import json
import re
import html

import pandas as pd
import requests
import streamlit as st
from openai import OpenAI
from supabase import create_client, Client
from google import genai
from google.genai import types


# -------------------------------------------------------------------
# 1. 페이지 기본 설정
# -------------------------------------------------------------------

st.set_page_config(
    page_title="최신 뉴스 검색 및 저장 앱",
    page_icon="📰",
    layout="wide"
)


# -------------------------------------------------------------------
# 2. Secrets 불러오기
# -------------------------------------------------------------------

OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]

NAVER_CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]

GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]


# -------------------------------------------------------------------
# 3. 클라이언트 초기화
# -------------------------------------------------------------------

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


@st.cache_resource
def init_openai_client() -> OpenAI:
    return OpenAI(api_key=OPENAI_API_KEY)


@st.cache_resource
def init_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)


supabase = init_supabase()
openai_client = init_openai_client()
gemini_client = init_gemini_client()


# -------------------------------------------------------------------
# 4. 공통 유틸 함수
# -------------------------------------------------------------------

def clean_text(text):
    """HTML 태그와 특수문자를 정리합니다."""
    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(r"<.*?>", "", text)
    text = text.replace("&quot;", '"')
    text = text.replace("&amp;", "&")
    text = text.strip()

    return text


def get_table_name(search_engine):
    """검색 엔진에 따라 저장할 Supabase 테이블명을 반환합니다."""
    if search_engine == "네이버":
        return "naver_news_history"

    if search_engine == "제미나이":
        return "gemini_news_history"

    return "naver_news_history"


def extract_json_array(text):
    """모델 응답에서 JSON 배열만 추출합니다."""
    text = (text or "").strip()

    # ```json ... ``` 제거
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    match = re.search(r"\[\s*\{.*?\}\s*\]", text, re.DOTALL)

    if not match:
        raise ValueError("응답에서 JSON 배열을 찾을 수 없습니다.")

    json_text = match.group(0)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 파싱 실패: {e}")

    if not isinstance(data, list):
        raise ValueError("JSON 응답이 배열 형식이 아닙니다.")

    return data


def save_news_to_supabase(search_engine, db_data):
    """검색 엔진에 따라 다른 Supabase 테이블에 저장합니다."""
    table_name = get_table_name(search_engine)

    try:
        supabase.table(table_name).insert(db_data).execute()
        return True

    except Exception as e:
        error_message = str(e)

        # url UNIQUE 제약조건으로 중복 저장 방지
        if "duplicate key value" in error_message or "23505" in error_message:
            return False

        st.error(f"Supabase 저장 오류: {e}")
        return False


# -------------------------------------------------------------------
# 5. 네이버 뉴스 검색 함수
# -------------------------------------------------------------------

def get_naver_news(query):
    """네이버 API를 통해 최신 뉴스 3개를 가져옵니다."""
    url = "https://openapi.naver.com/v1/search/news.json"

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }

    params = {
        "query": query,
        "display": 3,
        "sort": "date"
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=20
    )

    if response.status_code == 200:
        items = response.json().get("items", [])

        results = []

        for item in items:
            results.append({
                "title": clean_text(item.get("title", "")),
                "description": clean_text(item.get("description", "")),
                "link": item.get("link", ""),
                "pubDate": item.get("pubDate", ""),
                "source": "Naver News"
            })

        return results

    st.error(f"네이버 검색 API 오류: {response.status_code}")
    st.code(response.text)
    return []


# -------------------------------------------------------------------
# 6. OpenAI GPT 요약 함수
# -------------------------------------------------------------------

def summarize_news_with_gpt(title, description):
    """GPT를 사용하여 뉴스 내용을 2문장으로 요약합니다."""
    prompt = f"""
다음 뉴스 제목과 내용을 바탕으로 핵심만 한국어 2문장 내외로 요약해줘.

제목: {title}
내용: {description}
"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.5
    )

    return response.choices[0].message.content.strip()


# -------------------------------------------------------------------
# 7. Gemini Google Search Grounding 검색 함수
# -------------------------------------------------------------------

def get_gemini_news(query):
    """
    Gemini Google Search Grounding을 통해 최신 뉴스 3개를 가져옵니다.
    GOOGLE_API_KEY / GOOGLE_CX는 필요 없습니다.
    GEMINI_API_KEY만 사용합니다.
    """

    prompt = f"""
당신은 뉴스 큐레이션 전문가입니다.

아래 키워드와 관련된 최신 한국어 뉴스 기사 3건을 Google Search를 사용해 찾아주세요.

키워드: "{query}"

각 기사에 대해 다음 정보를 JSON 배열 형식으로만 응답하세요.
설명, 인사말, 머리말, 코드블록(```)은 절대 포함하지 마세요.
응답은 반드시 [ ... ] 로 시작하고 끝나는 순수 JSON 배열이어야 합니다.

JSON 형식:
[
  {{
    "title": "기사 제목",
    "source": "언론사 이름",
    "news_date": "2026-05-06",
    "url": "https://원본기사주소",
    "summary": "기사 핵심 내용을 한국어 3~4문장으로 요약"
  }}
]

규칙:
- 정확히 3건을 반환하세요.
- 가능한 한 최신 기사 위주로 선택하세요.
- url은 실제 기사 원문 URL이어야 합니다.
- 구글 검색 결과 페이지 URL은 금지합니다.
- news_date는 YYYY-MM-DD 형식으로 작성하세요.
- source는 언론사 이름으로 작성하세요.
- summary는 한국어 3~4문장으로 작성하세요.
- JSON 배열 외 텍스트는 절대 출력하지 마세요.
"""

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[
                {
                    "google_search": {}
                }
            ],
            temperature=0.2
        )
    )

    raw_text = response.text or ""
    news_data = extract_json_array(raw_text)

    results = []

    for news in news_data:
        results.append({
            "title": clean_text(news.get("title", "")),
            "description": clean_text(news.get("summary", "")),
            "link": news.get("url", ""),
            "pubDate": news.get("news_date", ""),
            "source": clean_text(news.get("source", "Gemini Google Search")),
            "summary": clean_text(news.get("summary", ""))
        })

    return results


# -------------------------------------------------------------------
# 8. 데이터 조회 함수
# -------------------------------------------------------------------

def load_table_data(table_name):
    """Supabase 테이블 데이터를 최신순으로 불러옵니다."""
    response = (
        supabase
        .table(table_name)
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def load_all_news_data():
    """네이버/제미나이 테이블을 모두 불러와 하나의 DataFrame으로 합칩니다."""
    naver_data = load_table_data("naver_news_history")
    gemini_data = load_table_data("gemini_news_history")

    naver_df = pd.DataFrame(naver_data)
    gemini_df = pd.DataFrame(gemini_data)

    if not naver_df.empty:
        naver_df["search_engine"] = "네이버"

    if not gemini_df.empty:
        gemini_df["search_engine"] = "제미나이"

    df_all = pd.concat(
        [naver_df, gemini_df],
        ignore_index=True
    )

    return df_all, naver_df, gemini_df


# -------------------------------------------------------------------
# 9. 화면 UI
# -------------------------------------------------------------------

st.title("📰 AI 최신 뉴스 검색 & 자동 저장기")
st.info(
    "💡 네이버 API 검색과 Gemini Google Search Grounding 검색을 함께 사용합니다. "
    "검색 결과는 Supabase DB에 자동 저장됩니다."
)

tab1, tab2, tab3 = st.tabs([
    "🔍 검색하기",
    "💾 저장된 뉴스 보기",
    "📊 통계 분석"
])


# ==========================================
# 탭 1: 검색하기 및 자동 저장
# ==========================================

with tab1:
    st.subheader("새로운 뉴스 검색")

    search_engine = st.radio(
        "검색 방식을 선택하세요",
        ["네이버", "제미나이"],
        horizontal=True
    )

    keyword = st.text_input(
        "검색할 뉴스 키워드를 입력하세요",
        placeholder="예: 삼성전자, 생성형 AI, 테슬라, ESG"
    )

    if st.button("뉴스 검색 및 자동 저장", type="primary"):
        keyword_clean = keyword.strip()

        if not keyword_clean:
            st.warning("키워드를 입력해주세요!")

        else:
            with st.spinner(f"{search_engine}에서 최신 뉴스를 검색하고 DB에 저장하는 중입니다..."):
                try:
                    if search_engine == "네이버":
                        news_items = get_naver_news(keyword_clean)
                    else:
                        news_items = get_gemini_news(keyword_clean)

                    if not news_items:
                        st.error("뉴스 결과를 가져오지 못했습니다.")

                    else:
                        saved_count = 0
                        duplicate_count = 0

                        st.success(f"'{keyword_clean}'에 대한 검색이 완료되었습니다!")

                        for news in news_items:
                            title = clean_text(news.get("title", ""))
                            source = clean_text(news.get("source", search_engine))
                            news_date = news.get("pubDate", "")
                            url = news.get("link", "")
                            description = clean_text(news.get("description", ""))

                            # 네이버는 GPT로 요약, 제미나이는 이미 summary가 있으므로 그대로 사용
                            if search_engine == "네이버":
                                summary = summarize_news_with_gpt(
                                    title,
                                    description
                                )
                            else:
                                summary = clean_text(news.get("summary", description))

                            # 화면 출력
                            with st.container(border=True):
                                if url:
                                    st.markdown(f"#### [{title}]({url})")
                                else:
                                    st.markdown(f"#### {title}")

                                st.caption(
                                    f"🏢 **출처:** {source} | "
                                    f"📅 **날짜:** {news_date} | "
                                    f"🔎 **검색:** {search_engine}"
                                )
                                st.write(summary)

                            # DB 저장 데이터
                            db_record = {
                                "keyword": keyword_clean,
                                "title": title,
                                "source": source,
                                "news_date": news_date,
                                "url": url,
                                "summary": summary
                            }

                            saved = save_news_to_supabase(
                                search_engine,
                                db_record
                            )

                            if saved:
                                saved_count += 1
                            else:
                                duplicate_count += 1

                        st.toast(
                            f"✅ 새로 저장됨: {saved_count}건 | "
                            f"🔄 중복/실패 생략됨: {duplicate_count}건"
                        )

                except Exception as e:
                    st.error(f"오류가 발생했습니다: {e}")


# ==========================================
# 탭 2: 저장된 뉴스 보기
# ==========================================

with tab2:
    st.subheader("데이터베이스에 저장된 뉴스 목록")

    saved_engine = st.radio(
        "조회할 저장 목록을 선택하세요",
        ["네이버", "제미나이", "전체"],
        horizontal=True
    )

    search_term = st.text_input(
        "목록 내 키워드 필터링",
        placeholder="제목 또는 검색 키워드 기준으로 필터링"
    )

    try:
        if saved_engine == "전체":
            df, _, _ = load_all_news_data()
        else:
            table_name = get_table_name(saved_engine)
            data = load_table_data(table_name)
            df = pd.DataFrame(data)

            if not df.empty:
                df["search_engine"] = saved_engine

        if df.empty:
            st.info("아직 저장된 뉴스가 없습니다. 탭 1에서 뉴스를 검색해보세요!")

        else:
            if search_term:
                search_term_clean = search_term.strip()

                df = df[
                    df["keyword"].astype(str).str.contains(
                        search_term_clean,
                        case=False,
                        na=False
                    )
                    |
                    df["title"].astype(str).str.contains(
                        search_term_clean,
                        case=False,
                        na=False
                    )
                ]

            display_cols = [
                "search_engine",
                "keyword",
                "title",
                "source",
                "news_date",
                "url",
                "created_at"
            ]

            existing_cols = [
                col for col in display_cols
                if col in df.columns
            ]

            st.dataframe(
                df[existing_cols],
                use_container_width=True,
                hide_index=True
            )

            csv_data = df.to_csv(index=False, encoding="utf-8-sig")

            st.download_button(
                label="📥 현재 표의 데이터 CSV 다운로드",
                data=csv_data,
                file_name="saved_news_history.csv",
                mime="text/csv"
            )

    except Exception as e:
        st.error(f"DB 데이터를 불러오는 중 오류가 발생했습니다: {e}")


# ==========================================
# 탭 3: 통계 분석
# ==========================================

with tab3:
    st.subheader("검색 통계 대시보드")

    try:
        df_all, naver_df, gemini_df = load_all_news_data()

        if df_all.empty:
            st.info("통계를 표시할 데이터가 부족합니다.")

        else:
            df_all["created_at"] = pd.to_datetime(
                df_all["created_at"],
                errors="coerce"
            )

            total_count = len(df_all)
            naver_count = len(naver_df)
            gemini_count = len(gemini_df)
            unique_keyword_count = df_all["keyword"].nunique()
            unique_source_count = df_all["source"].nunique()

            col1, col2, col3, col4, col5 = st.columns(5)

            col1.metric("전체 저장 기사 수", total_count)
            col2.metric("네이버 기사 수", naver_count)
            col3.metric("제미나이 기사 수", gemini_count)
            col4.metric("검색 키워드 수", unique_keyword_count)
            col5.metric("출처 수", unique_source_count)

            st.divider()

            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown("### 검색 방식별 저장 기사 수")

                engine_counts = (
                    df_all["search_engine"]
                    .value_counts()
                    .reset_index()
                )
                engine_counts.columns = ["search_engine", "count"]

                st.bar_chart(
                    engine_counts,
                    x="search_engine",
                    y="count"
                )

                st.dataframe(
                    engine_counts,
                    use_container_width=True,
                    hide_index=True
                )

            with col_right:
                st.markdown("### 일자별 DB 저장 건수")

                df_all["date_only"] = df_all["created_at"].dt.date

                date_counts = (
                    df_all["date_only"]
                    .value_counts()
                    .sort_index()
                    .reset_index()
                )
                date_counts.columns = ["date", "count"]

                st.line_chart(
                    date_counts,
                    x="date",
                    y="count"
                )

                st.dataframe(
                    date_counts,
                    use_container_width=True,
                    hide_index=True
                )

            st.divider()

            st.markdown("### 키워드별 누적 저장 건수")

            keyword_counts = (
                df_all["keyword"]
                .value_counts()
                .reset_index()
            )
            keyword_counts.columns = ["keyword", "count"]

            st.bar_chart(
                keyword_counts,
                x="keyword",
                y="count"
            )

            st.dataframe(
                keyword_counts,
                use_container_width=True,
                hide_index=True
            )

            st.divider()

            st.markdown("### 출처별 기사 수 TOP 10")

            source_counts = (
                df_all["source"]
                .value_counts()
                .head(10)
                .reset_index()
            )
            source_counts.columns = ["source", "count"]

            st.bar_chart(
                source_counts,
                x="source",
                y="count"
            )

            st.dataframe(
                source_counts,
                use_container_width=True,
                hide_index=True
            )

            st.divider()

            st.markdown("### 최근 저장된 기사 10건")

            recent_df = (
                df_all
                .sort_values("created_at", ascending=False)
                .head(10)
            )

            recent_cols = [
                "search_engine",
                "keyword",
                "title",
                "source",
                "news_date",
                "created_at",
                "url"
            ]

            recent_cols = [
                col for col in recent_cols
                if col in recent_df.columns
            ]

            st.dataframe(
                recent_df[recent_cols],
                use_container_width=True,
                hide_index=True
            )

    except Exception as e:
        st.error(f"통계를 불러오는 중 오류가 발생했습니다: {e}")
