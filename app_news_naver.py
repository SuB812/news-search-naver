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


def get_table_name(search_engine):
    """검색 엔진에 따라 저장할 Supabase 테이블명을 반환합니다."""
    if search_engine == "네이버":
        return "naver_news_history"
    elif search_engine == "구글":
        return "google_news_history"
    else:
        return "naver_news_history"


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

    else:
        st.error(f"네이버 검색 API 오류: {response.status_code}")
        st.code(response.text)
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


def save_news_to_supabase(search_engine, db_data):
    """검색 엔진에 따라 다른 Supabase 테이블에 저장합니다."""
    table_name = get_table_name(search_engine)

    try:
        supabase.table(table_name).insert(db_data).execute()
        return True

    except Exception as e:
        error_message = str(e)

        # url UNIQUE 제약조건 때문에 같은 기사가 이미 저장된 경우
        if "duplicate key value" in error_message or "23505" in error_message:
            st.warning(f"이미 저장된 기사입니다: {db_data.get('title', '')}")
            return False

        else:
            st.error(f"Supabase 저장 오류: {e}")
            return False


# -------------------------------------------------------------------
# 3. UI 및 메인 로직
# -------------------------------------------------------------------

st.title("📰 최신 뉴스 AI 요약기")

tab1, tab2, tab3 = st.tabs([
    "🔍 뉴스 검색 및 저장",
    "💾 저장된 목록",
    "📊 검색 통계 요약"
])


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
                    saved_count = 0
                    duplicate_count = 0

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

                        # Supabase 저장 데이터
                        db_data = {
                            "keyword": keyword,
                            "title": clean_title,
                            "source": item.get("source", search_engine),
                            "news_date": item.get("pubDate", ""),
                            "url": item.get("link", ""),
                            "summary": summary
                        }

                        saved = save_news_to_supabase(search_engine, db_data)

                        if saved:
                            saved_count += 1
                        else:
                            duplicate_count += 1

                    st.success(
                        f"{search_engine} 뉴스 처리 완료: "
                        f"신규 저장 {saved_count}건 / 중복 또는 실패 {duplicate_count}건"
                    )


with tab2:
    saved_engine = st.radio(
        "저장된 목록을 선택하세요",
        ["네이버", "구글"],
        horizontal=True
    )

    table_name = get_table_name(saved_engine)

    try:
        res = (
            supabase
            .table(table_name)
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )

        if res.data:
            st.subheader(f"💾 {saved_engine} 저장 뉴스 목록")
            st.dataframe(
                pd.DataFrame(res.data),
                use_container_width=True
            )

        else:
            st.info(f"아직 저장된 {saved_engine} 뉴스가 없습니다.")

    except Exception as e:
        st.error(f"저장된 목록을 불러오는 중 오류가 발생했습니다: {e}")

with tab3:
    st.subheader("📊 검색 통계 요약")

    try:
        naver_res = (
            supabase
            .table("naver_news_history")
            .select("*")
            .execute()
        )

        google_res = (
            supabase
            .table("google_news_history")
            .select("*")
            .execute()
        )

        naver_df = pd.DataFrame(naver_res.data)
        google_df = pd.DataFrame(google_res.data)

        if not naver_df.empty:
            naver_df["search_engine"] = "네이버"

        if not google_df.empty:
            google_df["search_engine"] = "구글"

        df_all = pd.concat(
            [naver_df, google_df],
            ignore_index=True
        )

        if df_all.empty:
            st.info("아직 저장된 뉴스 데이터가 없습니다.")

        else:
            # 날짜 변환
            df_all["created_at"] = pd.to_datetime(
                df_all["created_at"],
                errors="coerce"
            )

            # 기본 지표
            total_count = len(df_all)
            naver_count = len(naver_df)
            google_count = len(google_df)
            unique_keyword_count = df_all["keyword"].nunique()
            unique_source_count = df_all["source"].nunique()

            col1, col2, col3, col4, col5 = st.columns(5)

            col1.metric("전체 저장 기사 수", total_count)
            col2.metric("네이버 기사 수", naver_count)
            col3.metric("구글 기사 수", google_count)
            col4.metric("검색 키워드 수", unique_keyword_count)
            col5.metric("출처 수", unique_source_count)

            st.divider()

            # 검색엔진별 기사 수
            st.markdown("### 1. 검색엔진별 수집 기사 수")

            engine_count = (
                df_all
                .groupby("search_engine")
                .size()
                .reset_index(name="count")
            )

            st.bar_chart(
                engine_count,
                x="search_engine",
                y="count"
            )

            st.dataframe(
                engine_count,
                use_container_width=True
            )

            st.divider()

            # 키워드별 기사 수
            st.markdown("### 2. 키워드별 저장 기사 수")

            keyword_count = (
                df_all
                .groupby("keyword")
                .size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
            )

            st.bar_chart(
                keyword_count,
                x="keyword",
                y="count"
            )

            st.dataframe(
                keyword_count,
                use_container_width=True
            )

            st.divider()

            # 출처별 기사 수
            st.markdown("### 3. 출처별 기사 수 TOP 10")

            source_count = (
                df_all
                .groupby("source")
                .size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
                .head(10)
            )

            st.bar_chart(
                source_count,
                x="source",
                y="count"
            )

            st.dataframe(
                source_count,
                use_container_width=True
            )

            st.divider()

            # 최근 저장된 기사
            st.markdown("### 4. 최근 저장된 기사")

            recent_df = (
                df_all
                .sort_values("created_at", ascending=False)
                .head(10)
            )

            st.dataframe(
                recent_df[
                    [
                        "search_engine",
                        "keyword",
                        "title",
                        "source",
                        "news_date",
                        "created_at",
                        "url"
                    ]
                ],
                use_container_width=True
            )

    except Exception as e:
        st.error(f"검색 통계를 불러오는 중 오류가 발생했습니다: {e}")
