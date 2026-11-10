from urllib.parse import urlparse, parse_qs, unquote
import requests
import os
import re


# 配置项：指定下载文件夹（可自行修改）
DOWNLOAD_DIR = "."
# 模拟浏览器请求头（避免403拒绝）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

def decode_lms_url(viewer_url):
    """解码LMS的pdf-viewer链接，返回真实PDF地址"""
    try:
        parsed = urlparse(viewer_url)
        params = parse_qs(parsed.query)
        if "file" not in params:
            return None
        real_url = unquote(params["file"][0])
        return real_url
    except:
        return None

def get_original_filename(real_pdf_url):
    """从真实PDF链接中提取源文件名（严格匹配源链接命名）"""
    # 解码URL中的特殊字符（如中文、空格、%20等）
    decoded_url = unquote(real_pdf_url)
    # 解析URL路径，提取最后一段作为文件名
    parsed_url = urlparse(decoded_url)
    filename = os.path.basename(parsed_url.path)
    
    # 仅当文件名为空/无.pdf后缀时，才生成默认名（避免命名失败）
    if not filename or not filename.endswith(".pdf"):
        # 保留源链接特征的默认名（用URL最后部分生成）
        fallback_name = parsed_url.path.replace("/", "_").strip("_")
        filename = f"{fallback_name}.pdf" if not fallback_name.endswith(".pdf") else fallback_name
    
    return filename

def create_download_dir():
    """创建下载文件夹（不存在则创建）"""
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        print(f"✅ 下载文件夹已创建：{os.path.abspath(DOWNLOAD_DIR)}")

def download_pdf(real_url, save_dir):
    """下载PDF，文件名严格使用源链接中的名称"""
    filename = ""
    try:
        # 提取源链接中的原始文件名
        filename = get_original_filename(real_url)
        save_path = os.path.join(save_dir, filename)

        # 跳过已存在的文件
        if os.path.exists(save_path):
            print(f"⚠️ 文件已存在，跳过：{filename}")
            return True

        # 流式下载（适配大文件）
        response = requests.get(real_url, headers=HEADERS, stream=True, timeout=30)
        response.raise_for_status()

        # 分块写入文件
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB/块
                if chunk:
                    f.write(chunk)

        print(f"✅ 下载完成：{filename} → {os.path.abspath(save_path)}")
        return True
    except requests.exceptions.HTTPError as e:
        print(f"❌ 下载失败（HTTP {e.response.status_code}）：{filename}")
        return False
    except Exception as e:
        print(f"❌ 下载失败（{str(e)}）：{filename}")
        return False

def main():
    print("="*60)
    print("NJU LMS PDF解码+下载工具（文件名匹配源链接）")
    print("说明：输入pdf-viewer链接，空行结束输入")
    print("="*60 + "\n")

    # 初始化下载文件夹
    create_download_dir()

    # 接收用户输入链接
    urls = []
    print("请输入需要处理的链接（每行1个，空行结束）：")
    
    # 读取所有输入行，直到遇到空行
    # 跳过初始空行，处理包含链接的行
    while True:
        u = input().strip()
        if not u:
            # 只有当已经处理过非空行后，空行才会结束输入
            if urls:
                break
            else:
                # 初始空行，继续读取
                continue
        
        # 尝试从输入中提取可能的链接（即使包含其他字符）
        # 简单的链接检测：包含http或https的字符串
        link_matches = re.findall(r'https?://[^\s\n]+', u)
        if link_matches:
            for link in link_matches:
                urls.append(link)
        else:
            # 如果没有检测到http/https，仍然尝试处理整个输入
            # 可能是相对链接或其他格式
            urls.append(u)

    if not urls:
        print("⚠️ 未输入任何链接，程序退出")
        return

    # 批量解码+下载
    print(f"\n📌 共检测到 {len(urls)} 个链接，开始处理...\n")
    success_count = 0
    for idx, url in enumerate(urls, 1):
        print(f"--- 处理第 {idx}/{len(urls)} 个链接 ---")
        real_url = decode_lms_url(url)
        if real_url:
            print(f"🔍 解码成功：{real_url}")
            if download_pdf(real_url, DOWNLOAD_DIR):
                success_count += 1
        else:
            print(f"❌ 解码失败：{url}")

    # 最终统计
    print("\n" + "="*60)
    print(f"📊 处理完成！总计 {len(urls)} 个链接，成功下载 {success_count} 个文件")
    print(f"📁 文件保存路径：{os.path.abspath(DOWNLOAD_DIR)}")
    print("="*60)

if __name__ == "__main__":
    main()