import streamlit as st
import pandas as pd
import requests
from datetime import datetime
from openai import OpenAI
from supabase import create_client, Client

# -------------------------------------------------------------------
# 1. 페이지 설정 및 비밀 키 불러오기
# -------------------------------------------------------------------
st.set_page_config(page_title="네이버 AI 뉴스 저장소", page_icon="📰", layout="wide")

# Streamlit Cloud의 Secrets에 아래 키들을 모두 등록해야 합니다.
NAVER_CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# 클라이언트 초기화
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------------------------------------------------
# 2. 기능 함수 (네이버 검색 및 GPT 요약)
# -------------------------------------------------------------------
# -------------------------------------------------------------------
# 2. 기능 함수 (네이버/구글 검색 및 GPT 요약)
# -------------------------------------------------------------------

def clean_text(text):
    """HTML 태그와 특수문자를 정리합니다."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<.*?>", "", text)
    text = text.replace("&quot;", '"')
    text = text.replace("&amp;", "&")
    text = text.strip()
    return text


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

    response = requests.get(url, headers=headers, params=params)

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

    return []


def get_google_news(query):
    """Google Custom Search API를 통해 최신 뉴스 3개를 가져옵니다."""
    url = "https://www.googleapis.com/customsearch/v1"

    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CX,
        "q": f"{query} 뉴스",
        "num": 3,
        "gl": "kr",
        "lr": "lang_ko",
        "dateRestrict": "d7"
    }

    response = requests.get(url, params=params)

    if response.status_code == 200:
        items = response.json().get("items", [])

        results = []
        for item in items:
            title = clean_text(item.get("title", ""))
            description = clean_text(item.get("snippet", ""))
            link = item.get("link", "")
            source = item.get("displayLink", "Google Search")

            # Google 검색 결과에는 발행일이 항상 명확히 들어오지 않음
            pub_date = ""

            pagemap = item.get("pagemap", {})
            metatags = pagemap.get("metatags", [])

            if metatags:
                meta = metatags[0]
                pub_date = (
                    meta.get("article:published_time")
                    or meta.get("datePublished")
                    or meta.get("date")
                    or meta.get("pubdate")
                    or ""
                )

            results.append({
                "title": title,
                "description": description,
                "link": link,
                "pubDate": pub_date,
                "source": source
            })

        return results

    else:
        st.error(f"Google 검색 API 오류: {response.status_code}")
        st.code(response.text)
        return []


def summarize_news(title, description):
    """GPT를 사용하여 뉴스 내용을 요약합니다."""
    prompt = f"""
다음 뉴스 제목과 내용을 바탕으로 2문장 내외로 핵심만 요약해줘.

제목: {title}
내용: {description}
"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.5
    )

    return response.choices[0].message.content
# -------------------------------------------------------------------
# 3. UI 및 메인 로직
# -------------------------------------------------------------------
st.title("📰 네이버 최신 뉴스 AI 요약기")

tab1, tab2 = st.tabs(["🔍 뉴스 검색 및 저장", "💾 저장된 목록"])
with tab1:
    search_engine = st.radio(
        "검색 엔진을 선택하세요",
        ["네이버", "구글"],
        horizontal=True
    )

    keyword = st.text_input(
        "검색어를 입력하세요",
        placeholder="예: 삼성전자, 생성형 AI"
    )

    if st.button("최신 뉴스 3개 가져오기", type="primary"):
        if not keyword:
            st.warning("키워드를 입력하세요.")

        else:
            with st.spinner(f"{search_engine}에서 최신 뉴스를 불러오는 중..."):

                if search_engine == "네이버":
                    items = get_naver_news(keyword)
                else:
                    items = get_google_news(keyword)

                if not items:
                    st.error("뉴스 결과를 가져오지 못했습니다.")

                else:
                    for item in items:
                        clean_title = clean_text(item.get("title", ""))
                        clean_description = clean_text(item.get("description", ""))

                        summary = summarize_news(
                            clean_title,
                            clean_description
                        )

                        # 화면 출력
                        with st.container(border=True):
                            st.subheader(clean_title)
                            st.write(f"**요약:** {summary}")
                            st.caption(
                                f"🔗 [원문 보기]({item.get('link', '')}) "
                                f"| 발행일: {item.get('pubDate', '')} "
                                f"| 출처: {item.get('source', search_engine)}"
                            )

                        # Supabase 저장
                        db_data = {
                            "keyword": keyword,
                            "title": clean_title,
                            "source": item.get("source", search_engine),
                            "news_date": item.get("pubDate", ""),
                            "url": item.get("link", ""),
                            "summary": summary
                        }

                        supabase.table("news_history").insert(db_data).execute()

                    st.success(f"{search_engine} 최신 뉴스 3개를 성공적으로 저장했습니다!")

with tab2:
    # 저장된 데이터 불러오기 로직 (이전과 동일)[cite: 4]
    res = supabase.table("news_history").select("*").order("created_at", desc=True).execute()
    if res.data:
        st.dataframe(pd.DataFrame(res.data), use_container_width=True)
