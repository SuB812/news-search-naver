# app_news_naver_openai_search.py
# -------------------------------------------------------------------
# 네이버 뉴스 API + OpenAI Web Search 뉴스 검색/요약 + Supabase 저장 앱
#
# 핵심:
# 1) 네이버 검색: Naver News Open API로 기사 검색 → GPT로 요약
# 2) OpenAI 검색: OpenAI Responses API의 Web Search 도구로 실제 웹 기사 검색+요약
# 3) 절대 임의 기사 생성 금지: OpenAI 프롬프트에서 "실제 검색으로 확인된 기사만" 요구
# 4) 뉴스 출처(source), 원문 URL(url), 날짜(news_date), 요약(summary) 저장
# 5) Supabase 테이블 분리 저장
#
# requirements.txt:
# streamlit
# pandas
# requests
# openai
# supabase
#
# Streamlit Cloud Secrets 예시:
# OPENAI_API_KEY = "sk-..."
# NAVER_CLIENT_ID = "네이버_CLIENT_ID"
# NAVER_CLIENT_SECRET = "네이버_CLIENT_SECRET"
# SUPABASE_URL = "https://xxxx.supabase.co"
# SUPABASE_KEY = "supabase_anon_or_service_role_key"
# -------------------------------------------------------------------

import json
import re
import html
from email.utils import parsedate_to_datetime

import pandas as pd
import requests
import streamlit as st
from openai import OpenAI
from supabase import create_client, Client


# -------------------------------------------------------------------
# 1. 페이지 기본 설정
# -------------------------------------------------------------------

st.set_page_config(
    page_title="뉴스 검색 및 저장 앱",
    page_icon="📰",
    layout="wide"
)


# -------------------------------------------------------------------
# 2. Secrets 불러오기
# -------------------------------------------------------------------

OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]

NAVER_CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]


# -------------------------------------------------------------------
# 3. 클라이언트 초기화
# -------------------------------------------------------------------

@st.cache_resource
def init_openai_client() -> OpenAI:
    return OpenAI(api_key=OPENAI_API_KEY)


@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


openai_client = init_openai_client()
supabase = init_supabase()


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


def normalize_naver_date(pub_date):
    """네이버 pubDate 문자열을 YYYY-MM-DD 형태로 변환합니다."""
    if not pub_date:
        return ""

    try:
        dt = parsedate_to_datetime(pub_date)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return pub_date


def get_table_name(search_engine):
    """검색 방식에 따라 저장할 Supabase 테이블명을 반환합니다."""
    if search_engine == "네이버":
        return "naver_news_history"

    if search_engine == "OpenAI Search":
        return "openai_news_history"

    return "openai_news_history"


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


def is_valid_article_item(item):
    """
    기사 데이터가 최소 조건을 만족하는지 확인합니다.
    title과 url이 없으면 저장하지 않습니다.
    """
    title = clean_text(item.get("title", ""))
    url = clean_text(item.get("url", ""))

    if not title:
        return False

    if not url:
        return False

    if not url.startswith("http"):
        return False

    return True


def save_news_to_supabase(search_engine, db_data):
    """검색 방식에 따라 다른 Supabase 테이블에 저장합니다."""
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

def get_naver_news(query, display_count):
    """네이버 API를 통해 최신 뉴스를 가져옵니다."""
    url = "https://openapi.naver.com/v1/search/news.json"

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }

    params = {
        "query": query,
        "display": display_count,
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
            title = clean_text(item.get("title", ""))
            description = clean_text(item.get("description", ""))
            link = item.get("originallink") or item.get("link", "")
            pub_date = normalize_naver_date(item.get("pubDate", ""))

            results.append({
                "title": title,
                "source": "Naver News",
                "news_date": pub_date,
                "url": link,
                "description": description,
                "summary": ""
            })

        return results

    st.error(f"네이버 검색 API 오류: {response.status_code}")
    st.code(response.text)
    return []


# -------------------------------------------------------------------
# 6. 네이버 기사 GPT 요약 함수
# -------------------------------------------------------------------

def summarize_news_with_gpt(title, description):
    """네이버 API가 가져온 제목/설명을 GPT로 요약합니다."""
    prompt = f"""
다음 뉴스 제목과 내용을 바탕으로 핵심만 한국어 2문장 내외로 요약해줘.
추측하지 말고, 제공된 제목과 내용 안에서만 요약해줘.

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
        temperature=0.2
    )

    return response.choices[0].message.content.strip()


# -------------------------------------------------------------------
# 7. OpenAI Web Search 뉴스 검색 함수
# -------------------------------------------------------------------
def search_news_with_openai(keyword, result_count):
    """
    OpenAI Web Search 도구로 실제 뉴스 검색 후,
    검색 결과를 다시 JSON 배열로 정리합니다.
    """

    # ------------------------------------------------------------
    # 1단계: OpenAI Web Search로 실제 기사 검색
    # ------------------------------------------------------------
    search_prompt = f"""
당신은 뉴스 리서처입니다.

아래 키워드와 관련된 최신 뉴스 기사 {result_count}건을 웹 검색으로 찾아주세요.

키워드: "{keyword}"

매우 중요한 규칙:
- 반드시 웹 검색 도구로 실제 존재하는 기사만 찾으세요.
- 절대 기사를 지어내면 안 됩니다.
- 각 기사마다 제목, 언론사/사이트명, 날짜, 원문 URL, 핵심 내용을 포함하세요.
- 실제 원문 URL을 확인하지 못한 기사는 제외하세요.
- 검색 결과 페이지 URL이 아니라 실제 기사 원문 URL이어야 합니다.
- 한국어로 정리하세요.
"""

    search_response = openai_client.responses.create(
        model="gpt-4.1-mini",
        tools=[
            {
                "type": "web_search_preview"
            }
        ],
        input=search_prompt,
    )

    search_text = search_response.output_text or ""

    # 디버깅용: OpenAI가 실제로 뭐라고 답했는지 확인 가능
    with st.expander("OpenAI Search 원본 응답 확인"):
        st.write(search_text)

    # ------------------------------------------------------------
    # 2단계: 검색 결과 텍스트를 JSON 배열로 변환
    # ------------------------------------------------------------
json_prompt = f"""
아래는 웹 검색으로 확인한 실제 뉴스 검색 결과입니다.

이 텍스트에 포함된 기사만 사용해서 JSON으로 변환하세요.
텍스트에 없는 기사는 절대 추가하지 마세요.
URL이 없는 항목은 제외하세요.

검색 키워드: "{keyword}"
요청 기사 수: {result_count}

웹 검색 결과:
{search_text}

반드시 아래 JSON 객체 형식으로만 응답하세요.
설명, 인사말, 코드블록은 절대 포함하지 마세요.

{{
  "articles": [
    {{
      "title": "기사 제목",
      "source": "언론사 이름 또는 사이트명",
      "news_date": "YYYY-MM-DD",
      "url": "https://원본기사주소",
      "summary": "기사 핵심 내용을 한국어 3~4문장으로 요약"
    }}
  ]
}}

규칙:
- 실제 검색 결과에 포함된 기사만 변환하세요.
- title, source, url은 검색 결과에 있는 정보만 사용하세요.
- url이 없으면 해당 기사는 제외하세요.
- news_date를 알 수 없으면 ""로 두세요.
- summary는 검색 결과 내용을 근거로만 작성하세요.
- JSON 객체 외 텍스트는 절대 출력하지 마세요.
"""

    json_response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": json_prompt
            }
        ],
        temperature=0.1,
        response_format={
            "type": "json_object"
        }
    )

    json_text = json_response.choices[0].message.content or ""

    # json_object 모드에서는 보통 {"articles": [...]} 형태가 더 안정적이라 보정
    parsed = json.loads(json_text)

    if isinstance(parsed, dict):
        if "articles" in parsed:
            news_data = parsed["articles"]
        else:
            # 혹시 다른 key로 들어온 경우 첫 번째 list 값을 사용
            news_data = []
            for value in parsed.values():
                if isinstance(value, list):
                    news_data = value
                    break
    elif isinstance(parsed, list):
        news_data = parsed
    else:
        news_data = []

    results = []

    for news in news_data:
        if not isinstance(news, dict):
            continue

        item = {
            "title": clean_text(news.get("title", "")),
            "source": clean_text(news.get("source", "OpenAI Web Search")),
            "news_date": clean_text(news.get("news_date", "")),
            "url": clean_text(news.get("url", "")),
            "description": clean_text(news.get("summary", "")),
            "summary": clean_text(news.get("summary", ""))
        }

        if is_valid_article_item(item):
            results.append(item)

    return results


# -------------------------------------------------------------------
# 8. Supabase 조회 함수
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
    """네이버/OpenAI 테이블을 모두 불러와 하나의 DataFrame으로 합칩니다."""
    naver_data = load_table_data("naver_news_history")
    openai_data = load_table_data("openai_news_history")

    naver_df = pd.DataFrame(naver_data)
    openai_df = pd.DataFrame(openai_data)

    if not naver_df.empty:
        naver_df["search_engine"] = "네이버"

    if not openai_df.empty:
        openai_df["search_engine"] = "OpenAI Search"

    df_all = pd.concat(
        [naver_df, openai_df],
        ignore_index=True
    )

    return df_all, naver_df, openai_df


# -------------------------------------------------------------------
# 9. 화면 UI
# -------------------------------------------------------------------

st.title("📰 AI 최신 뉴스 검색 & 자동 저장기")
st.info(
    "💡 검색 방식: 네이버 뉴스 API 또는 OpenAI Web Search. "
    "검색된 기사 원문 URL과 출처를 함께 저장합니다."
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
        ["네이버", "OpenAI Search"],
        horizontal=True
    )

    keyword = st.text_input(
        "검색할 뉴스 키워드를 입력하세요",
        placeholder="예: 삼성전자, 생성형 AI, 테슬라, ESG"
    )

    result_count = st.selectbox(
        "가져올 기사 수",
        [3, 5, 10],
        index=0
    )

    if st.button("뉴스 검색 및 자동 저장", type="primary"):
        keyword_clean = keyword.strip()

        if not keyword_clean:
            st.warning("키워드를 입력해주세요!")

        else:
            with st.spinner(f"{search_engine}로 최신 뉴스를 검색하고 DB에 저장하는 중입니다..."):
                try:
                    if search_engine == "네이버":
                        news_items = get_naver_news(
                            query=keyword_clean,
                            display_count=result_count
                        )
                    else:
                        news_items = search_news_with_openai(
                            keyword=keyword_clean,
                            result_count=result_count
                        )

                    if not news_items:
                        st.error("뉴스 결과를 가져오지 못했습니다.")

                    else:
                        saved_count = 0
                        duplicate_count = 0
                        skipped_count = 0

                        st.success(f"'{keyword_clean}'에 대한 검색이 완료되었습니다!")

                        for news in news_items:
                            title = clean_text(news.get("title", ""))
                            source = clean_text(news.get("source", search_engine))
                            news_date = clean_text(news.get("news_date", ""))
                            url = clean_text(news.get("url", ""))
                            description = clean_text(news.get("description", ""))

                            if search_engine == "네이버":
                                summary = summarize_news_with_gpt(
                                    title,
                                    description
                                )
                            else:
                                summary = clean_text(news.get("summary", ""))

                            db_record = {
                                "keyword": keyword_clean,
                                "title": title,
                                "source": source,
                                "news_date": news_date,
                                "url": url,
                                "summary": summary
                            }

                            # 최소 조건 검증: 제목과 실제 URL 없으면 표시/저장하지 않음
                            if not is_valid_article_item(db_record):
                                skipped_count += 1
                                continue

                            # 화면 출력
                            with st.container(border=True):
                                st.markdown(f"#### [{title}]({url})")
                                st.caption(
                                    f"🏢 **출처:** {source} | "
                                    f"📅 **날짜:** {news_date} | "
                                    f"🔎 **검색:** {search_engine}"
                                )
                                st.write(summary)

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
                            f"🔄 중복/실패 생략됨: {duplicate_count}건 | "
                            f"⚠️ URL 없는 항목 제외: {skipped_count}건"
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
        ["네이버", "OpenAI Search", "전체"],
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
                "summary",
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
        df_all, naver_df, openai_df = load_all_news_data()

        if df_all.empty:
            st.info("통계를 표시할 데이터가 부족합니다.")

        else:
            df_all["created_at"] = pd.to_datetime(
                df_all["created_at"],
                errors="coerce"
            )

            total_count = len(df_all)
            naver_count = len(naver_df)
            openai_count = len(openai_df)
            unique_keyword_count = df_all["keyword"].nunique()
            unique_source_count = df_all["source"].nunique()

            col1, col2, col3, col4, col5 = st.columns(5)

            col1.metric("전체 저장 기사 수", total_count)
            col2.metric("네이버 기사 수", naver_count)
            col3.metric("OpenAI Search 기사 수", openai_count)
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
