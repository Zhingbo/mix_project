from curl_cffi import requests
import json
import os
import random
import time
import hashlib
import base64
from datetime import datetime
from baidu_data_extractor import BaiduDataExtractor

cached_cookie = None

def generate_base_cookie():
    timestamp = int(time.time() * 1000)
    
    # 使用更真实的 cookie 结构，但动态变化部分值
    baiduid = hashlib.md5(f"{timestamp}{random.random()}".encode()).hexdigest()
    
    # 生成更真实的 BDUSS（包含特定格式）
    bduss_base = base64.b64encode(os.urandom(60)).decode('utf-8').rstrip('=')
    bduss = bduss_base + '=='  # 添加padding
    
    bclid = str(int(time.time()))[-18:] + str(random.randint(100, 999))
    
    bdrcvfr = ''.join(random.choices('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz', k=16))
    
    bdsfrcvid = base64.b64encode(os.urandom(25)).decode('utf-8').replace('=', '')[:42]
    
    # 使用更简单的追踪码
    h_bdclkid_parts = []
    for _ in range(3):
        part = ''.join(random.choices('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz', k=20))
        h_bdclkid_parts.append(part)
    h_bdclkid = '-'.join(h_bdclkid_parts)
    
    cookie_parts = [
        f"BDUSS_BFESS={bduss}",
        f"BAIDUID_BFESS={baiduid}:FG=1",
        f"BDRCVFR[feWj1Vr5u3D]={bdrcvfr}",
        "delPer=0",
        f"PSINO={random.choice(['0', '1', '2'])}",
        f"BCLID_BFESS={bclid}",
        f"BDSFRCVID={bdsfrcvid}",
        f"BDSFRCVID_BFESS={bdsfrcvid}",
        f"H_BDCLCKID_SF={h_bdclkid}",
        f"H_BDCLCKID_SF_BFESS={h_bdclkid}"
    ]
    
    return '; '.join(cookie_parts)

cookie_list = []

def get_random_user_agent():
    # 使用最新版本的PC版Chrome User-Agent
    pc_user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0'
    ]
    return random.choice(pc_user_agents)

def get_random_cookie():
    if not cookie_list:
        return generate_base_cookie()
    return random.choice(cookie_list)

def refresh_cookie():
    global cached_cookie
    
    refresh_url = "https://sp1.baidu.com/-L-Xsjip0QIZ8tyhnq/v.gif"
    
    timestamp_ms = int(time.time() * 1000)
    random_qid = "0x{:016x}".format(random.randint(0x1000000000, 0xFFFFFFFFFF))
    random_glogid = str(random.randint(1000000000, 9999999999))
    
    params = {
        'logactid': random_glogid,
        'showTab': '10000',
        'opType': 'showpv',
        'mod': 'superman:lib',
        'submod': 'index',
        'utype': '',
        'superver': 'supernewplus',
        'portrait': '',
        'logPortrait': 'public.1.{}.cXZxPkYEB8VV_jBpPLprxQ?_d={}'.format(
            hashlib.md5(str(timestamp_ms).encode()).hexdigest()[:16],
            random.randint(10000000, 99999999)
        ),
        'glogid': random_glogid,
        'type': '2011',
        'pid': '315',
        'isLogin': '1',
        'version': 'PCHome',
        'terminal': 'PC',
        'qid': random_qid,
        'sid': '_'.join(str(random.randint(60000, 70000)) for _ in range(30)),
        'super_frm': '',
        'from_login': '',
        'from_reg': '',
        'query': '',
        'curcard': '99',
        'curcardtab': '',
        '_r': str(random.random())
    }
    
    user_agent = get_random_user_agent()
    headers = {
        'Pragma': 'no-cache',
        'Cache-Control': 'no-cache',
        'User-Agent': user_agent,
        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://www.baidu.com/',
        'Cookie': get_random_cookie()
    }
    
    print("正在刷新 cookie...")
    response = requests.get(refresh_url, params=params, headers=headers, timeout=10, impersonate="chrome")
    
    if response.status_code != 200:
        raise Exception(f"刷新失败，状态码: {response.status_code}")
    
    response_cookies = response.cookies
    
    cookie_dict = {}
    if hasattr(response_cookies, 'items'):
        for name, value in response_cookies.items():
            cookie_dict[name] = value
    else:
        for cookie in response_cookies:
            if hasattr(cookie, 'name') and hasattr(cookie, 'value'):
                cookie_dict[cookie.name] = cookie.value
            else:
                pass
    
    if not cookie_dict:
        raise Exception("刷新失败：未获取到任何新 cookie")
    
    cookie_str = '; '.join([f'{k}={v}' for k, v in cookie_dict.items()])
    cached_cookie = cookie_str
    print(f"Cookie 刷新成功! 获取到 {len(cookie_dict)} 个新 cookie 字段")
    return cached_cookie

def get_html(keyword, page=1, max_retries=5, use_refreshed_cookie=False):
    # 先访问百度首页建立会话
    session = requests.Session(impersonate="chrome")
    
    try:
        # 首次访问首页获取初始cookie
        home_resp = session.get("https://www.baidu.com", timeout=10)
    except:
        pass
    
    url = "https://www.baidu.com/s"
    pn = (page - 1) * 10

    params = {
        'ie': "utf-8",
        "wd": keyword,
        "pn": pn,
        "rn": "10",
        "oq": keyword,
        "rsv_idx": str(random.randint(1, 3)),
        "rsv_pq": 'rn' + str(random.choice([10, 8, 12])),
        'rsv_t': str(random.randint(1000, 9999)),
        "rsv_enter": str(random.randint(0, 1)),
        "rsv_spt": str(random.randint(1, 3)),
        "bs": "",
        "f": str(random.choice([8, 4, 1])),
        "rsv_bp": str(random.randint(0, 1))
    }

    base_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Chromium";v="110", "Not A(Brand";v="24", "Google Chrome";v="110"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "DNT": "1"
    }
    
    if use_refreshed_cookie:
        if not cached_cookie:
            raise Exception("要求使用刷新的 cookie，但缓存为空，请先调用 refresh_cookie()")
        cookie_to_use = cached_cookie
        print(f"使用已缓存的刷新 cookie")
    else:
        cookie_to_use = None
    
    for attempt in range(max_retries):
        try:
            user_agent = get_random_user_agent()
            
            if use_refreshed_cookie:
                cookie = cookie_to_use
            else:
                cookie = get_random_cookie()
                
            headers = base_headers.copy()
            headers["User-Agent"] = user_agent
            headers["Cookie"] = cookie

            print(f"尝试第 {attempt + 1} 次请求")

            response = session.get(url, params=params, headers=headers, timeout=10, impersonate="chrome")
            response.raise_for_status()
            html = response.text

            if len(html) >= 10000:
                return html
            else:
                if attempt < max_retries - 1:
                    wait_time = 2 * (attempt + 1)
                    time.sleep(wait_time)
                    continue
                else:
                    return html

        except requests.exceptions.Timeout:
            print(f"第 {attempt + 1} 次超时")
        except requests.exceptions.HTTPError as e:
            print(f"第 {attempt + 1} 次HTTP错误: {e}")
        except requests.exceptions.RequestException as e:
            print(f"第 {attempt + 1} 次网络错误: {e}")
        except Exception as e:
            print(f"第 {attempt + 1} 次未知错误: {e}")

        if attempt < max_retries - 1:
            wait_time = 2 * (attempt + 1)
            print(f"等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)

    raise Exception(f"经过 {max_retries} 次尝试后仍然失败")
 
def search_single_page(keyword, page=1, save_html=True, use_refreshed_cookie=False):
    html = get_html(keyword, page, use_refreshed_cookie=use_refreshed_cookie)

    if len(html) < 10000:
        print(f"第{page}页: HTML异常短，可能遇到反爬虫")
        return []

    if save_html:
        html_dir = "html_files"
        if not os.path.exists(html_dir):
            os.makedirs(html_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{html_dir}/baidu_search_{keyword}_第{page}页_{timestamp}.html"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"HTML已保存到: {filename}")

    extractor = BaiduDataExtractor()
    extractor.load_html_content(html)
    results = extractor.extract_search_results()

    if results:
        # 去重：基于完整的URL
        seen_urls = set()
        unique_results = []
        
        for result in results:
            url = result.get('url', '')
            title = result.get('title', '')
            
            # 跳过无效结果
            if not title or len(title) < 5:
                continue
            
            # 跳过移动版相关搜索链接
            if 'm.baidu.com/from' in url and 's?word=' in url:
                continue
            
            # 跳过百度内部功能链接
            skip_patterns = ['baidu.com/link?url=www.baidu.com', 'baidu.com/link?url=zhidao']
            if any(pattern in url for pattern in skip_patterns):
                continue
            
            # 使用完整URL去重
            if url in seen_urls:
                continue
            
            seen_urls.add(url)
            unique_results.append(result)
        
        print(f"第{page}页成功提取 {len(unique_results)} 条搜索结果（去重后）")
        return unique_results
    else:
        print(f"第{page}页未能提取到有效数据")
        return []

def search_multiple_pages(keyword, max_pages=3):
    global cached_cookie
    
    all_results = []
    seen_urls = set()  # 全局去重
    
    print(f"开始多页搜索，共 {max_pages} 页")
    
    for page in range(1, max_pages + 1):
        try:
            if page == 1:
                print(f"\n=== 第 {page} 页：使用动态生成的 cookie ===")
                results = search_single_page(keyword, page, use_refreshed_cookie=False)
            else:
                print(f"\n === 第 {page} 页：使用动态生成的 cookie ===")
                results = search_single_page(keyword, page, use_refreshed_cookie=False)
                
            if results:
                # 全局去重
                page_unique_results = []
                for result in results:
                    url = result.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        result['index'] = len(all_results) + 1
                        result['page'] = page
                        page_unique_results.append(result)
                
                print(f"第{page}页去重后新增 {len(page_unique_results)} 条结果")
                all_results.extend(page_unique_results)
                
                if len(page_unique_results) == 0:
                    print(f"第{page}页没有新结果，停止搜索")
                    break
            else:
                print(f"第{page}页没有更多结果，停止搜索")
                break

            if page < max_pages:
                time.sleep(1)

        except Exception as e:
            print(f"第{page}页搜索出错: {e}")
            break

    return all_results

def main():
    keyword = input("请输入关键词：")

    print("\n选择搜索模式:")
    print("1. 单页搜索")
    print("2. 多页搜索")

    choice = input("请选择 (1 或 2，默认1): ").strip() or "1"

    if choice == "2":
        try:
            max_pages = int(input("请输入要搜索的页数 (默认3): ") or "3")
        except ValueError:
            max_pages = 3

        print(f"\n开始搜索 {max_pages} 页数据...")
        all_results = search_multiple_pages(keyword, max_pages)

        if all_results:
            print(f"\n总共成功提取 {len(all_results)} 条搜索结果")

            result_data = {
                "keyword": keyword,
                "search_time": datetime.now().isoformat(),
                "total_results": len(all_results),
                "total_pages": max_pages,
                "results": all_results
            }

            json_filename = f"search_results_{keyword}_多页.json"
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
            print(f"结果已保存到: {json_filename}")

            page_counts = {}
            for result in all_results:
                page = result.get('page', 1)
                page_counts[page] = page_counts.get(page, 0) + 1

            print(f"\n各页结果数量:")
            for page in sorted(page_counts.keys()):
                print(f"第{page}页: {page_counts[page]}条")

            print(f"\n前5个搜索结果:")
            for i, result in enumerate(all_results[:5], 1):
                print(f"{i}. {result['title']} (第{result.get('page', 1)}页)")
                if result.get('description'):
                    desc = result['description'][:80] + '...' if len(result['description']) > 80 else result['description']
                    print(f"   {desc}")
                print()
        else:
            print("未能提取到任何有效数据")

    else:
        print("\n单页搜索模式：使用动态生成的 cookie")
        results = search_single_page(keyword, use_refreshed_cookie=False)

        if results:
            result_data = {
                "keyword": keyword,
                "search_time": datetime.now().isoformat(),
                "total_results": len(results),
                "page": 1,
                "results": results
            }

            json_filename = f"search_results_{keyword}.json"
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
            print(f"结果已保存到: {json_filename}")

            print(f"\n前3个搜索结果:")
            for i, result in enumerate(results[:3], 1):
                print(f"{i}. {result['title']}")
                if result.get('description'):
                    desc = result['description'][:100] + '...' if len(result['description']) > 100 else result['description']
                    print(f"   {desc}")
                print()
        else:
            print("未能提取到有效数据")

if __name__ == "__main__":
    main()