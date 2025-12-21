import streamlit as st
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
import re
import jieba
from collections import Counter
from pyecharts import options as opts
from pyecharts.charts import WordCloud, Bar, Line, Pie, Radar, Scatter, HeatMap, TreeMap
from streamlit_echarts import st_pyecharts
import time
from datetime import datetime

# 配置请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://jsjds.blcu.edu.cn/"
}

# 基础域名（用于补全相对路径）
BASE_DOMAIN = "http://jsjds.blcu.edu.cn/"

def complete_url(relative_url: str) -> str:
    """补全相对路径为绝对URL"""
    if not relative_url:
        return ""
    # 已为绝对路径，直接返回
    if relative_url.startswith("http"):
        return relative_url
    # 相对路径，补全基础域名
    relative_url = relative_url.replace("../", "/").lstrip("/")
    return f"{BASE_DOMAIN}{relative_url}"

def is_file_link(link: str, text: str) -> bool:
    """判断是否为文件链接（pdf/docx/附件/下载等）"""
    file_extensions = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip", ".rar", ".ppt", ".pptx"]
    file_keywords = ["附件", "下载", "文件", "资料", "文档"]
    # 链接含文件后缀 或 文本含文件关键词
    return any(ext in link.lower() for ext in file_extensions) or any(keyword in text for keyword in file_keywords)

def recursive_extract(node, content_parts):
    """递归遍历节点，提取文本、图片、文件链接"""
    # 核心过滤关键词：面包屑、结构文本、导航文本
    filter_keywords = ["大赛动态首页", "正文", "发布者：", "时间：", "浏览："]
    # 面包屑标志：包含>符号
    breadcrumb_symbol = ">"

    if isinstance(node, NavigableString):
        # 文本节点处理：
        text = node.strip()
        # 过滤条件：
        # 1. 空文本
        # 2. 包含面包屑符号（>）
        # 3. 包含过滤关键词
        # 4. 纯空白或长度过短（<2个字符）
        if not text or breadcrumb_symbol in text or any(kw in text for kw in filter_keywords) or len(text) < 2:
            return
        # 保留有效文本
        content_parts.append(text)
    elif isinstance(node, Tag):
        # 标签节点：跳过无关标签
        if node.name in ["script", "style", "nav", "footer", "header", "aside", "iframe"]:
            return
        # 图片标签：提取图片链接
        if node.name == "img":
            img_src = complete_url(node.get("src", ""))
            if img_src:
                content_parts.append(f"\n[图片链接：{img_src}]\n")
            # 继续遍历子节点（避免图片标签内有文本）
            for child in node.contents:
                recursive_extract(child, content_parts)
        # 文件链接标签：提取文件链接
        elif node.name == "a":
            a_href = complete_url(node.get("href", ""))
            a_text = node.get_text(strip=True)
            if a_href and is_file_link(a_href, a_text):
                content_parts.append(f"\n[文件链接：{a_href}（描述：{a_text}）]\n")
            else:
                # 普通链接：提取文本
                for child in node.contents:
                    recursive_extract(child, content_parts)
        # 段落标签：提取文本后添加换行
        elif node.name == "p":
            p_text = []
            for child in node.contents:
                recursive_extract(child, p_text)
            p_combined = "".join(p_text).strip()
            if p_combined:
                content_parts.append(f"{p_combined}\n\n")
        # 其他标签：递归遍历子节点
        else:
            for child in node.contents:
                recursive_extract(child, content_parts)

def crawl_article_detail(link: str) -> str:
    """抓取详情页正文"""
    try:
        response = requests.get(link, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")

        # 精准定位目标网站的正文容器
        main_content = soup.find("div", class_="wp_articlecontent")
        if not main_content:
            # 降级方案：查找常见正文容器
            content_containers = [
                soup.find("div", class_=re.compile(r"content|article|main|text")),
                soup.find("div", id=re.compile(r"content|article|main")),
                soup.find("article"),
                soup.find("body"),
            ]
            for container in content_containers:
                if container:
                    main_content = container
                    break
            if not main_content:
                return "未找到正文内容"

        # 递归提取所有内容（文本+图片+文件链接）
        content_parts = []
        recursive_extract(main_content, content_parts)

        # 最终清理：移除残留的无效内容
        raw_content = "".join(content_parts)
        content = re.sub(r"\n+", "\n\n", raw_content).strip()
        content = re.sub(r"([。！？；])", r"\1\n\n", content)
        content_lines = content.split("\n")
        filtered_lines = []
        for line in content_lines:
            line_stripped = line.strip()
            if line_stripped not in ["首页", "大赛动态", "正文"] and len(line_stripped) > 1:
                filtered_lines.append(line)
        content = "\n".join(filtered_lines).strip()
        content = re.sub(r"\n+", "\n\n", content).strip()

        return content if content else "未提取到有效正文"

    except Exception as e:
        return f"抓取详情页失败：{str(e)}"

def remove_html_tags(text: str) -> str:
    """使用正则表达式去除文本中的HTML标签"""
    html_pattern = re.compile(r'<[^>]+>')
    clean_text = html_pattern.sub('', text)
    return clean_text

def remove_punctuation(text: str) -> str:
    """去除文本中的所有标点符号、特殊字符"""
    punctuation_pattern = re.compile(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]')
    clean_text = punctuation_pattern.sub(' ', text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

def segment_and_count(text: str, min_freq: int = 2) -> tuple:
    """对文本进行jieba分词，过滤无效词，统计词频"""
    word_list = jieba.lcut(text)
    filtered_words = []
    for word in word_list:
        if len(word) > 1 and not word.isdigit() and word.strip():
            filtered_words.append(word)
    word_count = Counter(filtered_words)
    # 过滤低频词
    filtered_word_count = {word: count for word, count in word_count.items() if count >= min_freq}
    top20_words = sorted(filtered_word_count.items(), key=lambda x: x[1], reverse=True)[:20]
    return filtered_word_count, top20_words

def create_wordcloud(word_data: dict) -> WordCloud:
    """创建词云图"""
    word_list = list(word_data.items())
    wordcloud = (
        WordCloud()
        .add(series_name="词频", data_pair=word_list, word_size_range=[20, 100])
        .set_global_opts(
            title_opts=opts.TitleOpts(title="词云图"),
            tooltip_opts=opts.TooltipOpts(is_show=True),
        )
    )
    return wordcloud

def create_bar_chart(top20_words: list) -> Bar:
    """创建柱状图"""
    words = [word for word, count in top20_words]
    counts = [count for word, count in top20_words]
    bar = (
        Bar()
        .add_xaxis(words)
        .add_yaxis("词频", counts)
        .set_global_opts(
            title_opts=opts.TitleOpts(title="词频前20柱状图"),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=45)),
            tooltip_opts=opts.TooltipOpts(is_show=True),
        )
    )
    return bar

def create_line_chart(top20_words: list) -> Line:
    """创建折线图"""
    words = [word for word, count in top20_words]
    counts = [count for word, count in top20_words]
    line = (
        Line()
        .add_xaxis(words)
        .add_yaxis("词频", counts)
        .set_global_opts(
            title_opts=opts.TitleOpts(title="词频前20折线图"),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=45)),
            tooltip_opts=opts.TooltipOpts(is_show=True),
        )
    )
    return line

def create_pie_chart(top20_words: list) -> Pie:
    """创建饼图"""
    words = [word for word, count in top20_words]
    counts = [count for word, count in top20_words]
    pie = (
        Pie()
        .add("", list(zip(words, counts)))
        .set_global_opts(
            title_opts=opts.TitleOpts(title="词频前20饼图"),
            tooltip_opts=opts.TooltipOpts(is_show=True),
        )
        .set_series_opts(label_opts=opts.LabelOpts(formatter="{b}: {c}"))
    )
    return pie

def create_radar_chart(top20_words: list) -> Radar:
    """创建雷达图"""
    words = [word for word, count in top20_words]
    counts = [count for word, count in top20_words]
    max_count = max(counts) if counts else 1
    schema = [opts.RadarIndicatorItem(name=word, max_=max_count) for word in words]
    radar = (
        Radar()
        .add_schema(schema=schema, shape="circle")
        .add("词频", [counts])
        .set_global_opts(title_opts=opts.TitleOpts(title="词频前20雷达图"))
    )
    return radar

def create_scatter_chart(top20_words: list) -> Scatter:
    """创建散点图"""
    words = [word for word, count in top20_words]
    counts = [count for word, count in top20_words]
    scatter = (
        Scatter()
        .add_xaxis(words)
        .add_yaxis("词频", counts)
        .set_global_opts(
            title_opts=opts.TitleOpts(title="词频前20散点图"),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=45)),
            tooltip_opts=opts.TooltipOpts(is_show=True),
        )
    )
    return scatter

def create_heatmap(top20_words: list) -> HeatMap:
    """创建热力图"""
    words = [word for word, count in top20_words]
    counts = [count for word, count in top20_words]
    data = [[i, 0, count] for i, count in enumerate(counts)]
    heatmap = (
        HeatMap()
        .add_xaxis(words)
        .add_yaxis("词频", [""], data)
        .set_global_opts(
            title_opts=opts.TitleOpts(title="词频前20热力图"),
            visualmap_opts=opts.VisualMapOpts(min_=min(counts), max_=max(counts)),
            tooltip_opts=opts.TooltipOpts(is_show=True),
        )
    )
    return heatmap

def create_treemap(top20_words: list) -> TreeMap:
    """创建树图"""
    data = [{"name": word, "value": count} for word, count in top20_words]
    treemap = (
        TreeMap()
        .add("词频", data)
        .set_global_opts(
            title_opts=opts.TitleOpts(title="词频前20树图"),
            tooltip_opts=opts.TooltipOpts(is_show=True),
        )
    )
    return treemap

def main():
    st.title("文章词频分析系统")
    st.sidebar.title("图形筛选")
    
    # 侧边栏图形选择
    chart_type = st.sidebar.selectbox(
        "选择图表类型",
        ["词云图", "柱状图", "折线图", "饼图", "雷达图", "散点图", "热力图", "树图"]
    )
    
    # 侧边栏低频词过滤
    min_freq = st.sidebar.slider("过滤低频词（词频≥）", 1, 10, 2)
    
    # URL输入
    url = st.text_input("输入文章URL", "http://jsjds.blcu.edu.cn/dsdt.htm")
    
    if st.button("开始分析"):
        with st.spinner("正在抓取文章内容..."):
            content = crawl_article_detail(url)
            
            # 文章内容展示优化
            st.subheader("📄 文章内容")
            if content and content != "未提取到有效正文" and "抓取详情页失败" not in content:
                # 统计信息
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("文章字数", len(content))
                with col2:
                    st.metric("段落数", len([p for p in content.split('\n\n') if p.strip()]))
                with col3:
                    st.metric("图片链接数", content.count("[图片链接"))
                
                # 格式化显示文章内容
                st.markdown("### 文章正文")
                paragraphs = content.split('\n\n')
                for i, paragraph in enumerate(paragraphs[:10]):  # 显示前10段，避免太长
                    if paragraph.strip():
                        if "[图片链接" in paragraph or "[文件链接" in paragraph:
                            st.info(paragraph)
                        else:
                            st.write(paragraph)
                
                if len(paragraphs) > 10:
                    with st.expander("查看更多内容"):
                        for paragraph in paragraphs[10:]:
                            if paragraph.strip():
                                if "[图片链接" in paragraph or "[文件链接" in paragraph:
                                    st.info(paragraph)
                                else:
                                    st.write(paragraph)
            else:
                st.error("未能成功抓取文章内容，请检查URL是否正确")
            
            # 文本处理
            st.subheader("🔍 文本处理")
            content_no_html = remove_html_tags(content)
            content_clean = remove_punctuation(content_no_html)
            word_count, top20_words = segment_and_count(content_clean, min_freq)
            
            # 处理统计信息
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("有效词汇数", len(word_count))
            with col2:
                st.metric("总词频", sum(word_count.values()))
            with col3:
                st.metric("平均词频", round(sum(word_count.values()) / len(word_count), 2) if word_count else 0)
            
            # 展示词频前20
            st.subheader("📊 词频排名前20的词汇")
            top20_df = {"词汇": [word for word, count in top20_words], "词频": [count for word, count in top20_words]}
            st.table(top20_df)
            
            # 绘制图表
            st.subheader(f"{chart_type}")
            if chart_type == "词云图":
                wordcloud = create_wordcloud(word_count)
                st_pyecharts(wordcloud)
            elif chart_type == "柱状图":
                bar = create_bar_chart(top20_words)
                st_pyecharts(bar)
            elif chart_type == "折线图":
                line = create_line_chart(top20_words)
                st_pyecharts(line)
            elif chart_type == "饼图":
                pie = create_pie_chart(top20_words)
                st_pyecharts(pie)
            elif chart_type == "雷达图":
                radar = create_radar_chart(top20_words)
                st_pyecharts(radar)
            elif chart_type == "散点图":
                scatter = create_scatter_chart(top20_words)
                st_pyecharts(scatter)
            elif chart_type == "热力图":
                heatmap = create_heatmap(top20_words)
                st_pyecharts(heatmap)
            elif chart_type == "树图":
                treemap = create_treemap(top20_words)
                st_pyecharts(treemap)

if __name__ == "__main__":
    main()