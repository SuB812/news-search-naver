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

def get_naver_news(query):
    """네이버 API를 통해 최신 뉴스 3개를 가져옵니다."""
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    # sort='sim'은 정확도순, 'date'는 최신순입니다. 최신을 위해 'date' 설정
    params = {"query": query, "display": 3, "sort": "date"}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json().get('items', [])
    return []

def summarize_news(title, description):
    """GPT를 사용하여 뉴스 내용을 요약합니다."""
    prompt = f"다음 뉴스 제목과 내용을 바탕으로 2문장 내외로 핵심만 요약해줘.\n제목: {title}\n내용: {description}"
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return response.choices[0].message.content

# -------------------------------------------------------------------
# 3. UI 및 메인 로직
# -------------------------------------------------------------------
st.title("📰 네이버 최신 뉴스 AI 요약기")

tab1, tab2 = st.tabs(["🔍 뉴스 검색 및 저장", "💾 저장된 목록"])

with tab1:
    keyword = st.text_input("검색어를 입력하세요", placeholder="예: 삼성전자, 생성형 AI")
    
    if st.button("최신 뉴스 3개 가져오기", type="primary"):
        if not keyword:
            st.warning("키워드를 입력하세요.")
        else:
            with st.spinner("네이버에서 최신 뉴스를 불러오는 중..."):
                items = get_naver_news(keyword)
                
                if not items:
                    st.error("뉴스 결과를 가져오지 못했습니다.")
                else:
                    for item in items:
                        # 데이터 정제 (HTML 태그 제거)
                        clean_title = item['title'].replace('<b>', '').replace('</b>', '').replace('&quot;', '"')
                        summary = summarize_news(clean_title, item['description'])
                        
                        # 화면 출력
                        with st.container(border=True):
                            st.subheader(clean_title)
                            st.write(f"**요약:** {summary}")
                            st.caption(f"🔗 [원문 보기]({item['link']}) | 발행일: {item['pubDate']}")
                        
                        # Supabase 저장[cite: 4]
                        db_data = {
                            "keyword": keyword,
                            "title": clean_title,
                            "source": "Naver News",
                            "news_date": item['pubDate'],
                            "url": item['link'],
                            "summary": summary
                        }
                        supabase.table("news_history").insert(db_data).execute()
                    
                    st.success("최신 뉴스 3개를 성공적으로 저장했습니다!")

with tab2:
    # 저장된 데이터 불러오기 로직 (이전과 동일)[cite: 4]
    res = supabase.table("news_history").select("*").order("created_at", desc=True).execute()
    if res.data:
        st.dataframe(pd.DataFrame(res.data), use_container_width=True)
