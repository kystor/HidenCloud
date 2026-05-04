#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
from seleniumbase import SB
from datetime import datetime

# =========================================================
# 配置区域：解析环境变量中的多账号数据
# =========================================================
HIDENCLOUD_ENV = os.getenv("HIDENCLOUD", "")

account_list = []
if HIDENCLOUD_ENV:
    for account_str in HIDENCLOUD_ENV.split(","):
        account_str = account_str.strip()
        if ":" in account_str:
            email, pwd = account_str.split(":", 1)
            account_list.append({"email": email, "pwd": pwd})
        elif account_str:
            print(f"[WARN] 跳过格式错误的账号: {account_str}")

if not account_list:
    raise ValueError("❌ 没有找到有效的账号配置，请检查环境变量 (账号:密码,账号:密码)")

BASE_URL = "https://dash.hidencloud.com"

# =========================================================
# 准备工作：设置截图保存的文件夹
# =========================================================
SCREENSHOT_DIR = "screenshots"
if not os.path.exists(SCREENSHOT_DIR):
    os.makedirs(SCREENSHOT_DIR)

def take_screenshot(sb, account_index, step_name):
    """辅助函数：给当前网页拍照并保存"""
    file_path = os.path.join(SCREENSHOT_DIR, f"acc{account_index}_{step_name}.png")
    try:
        sb.save_screenshot(file_path)
        print(f"    ↳ 📸 截图: {os.path.basename(file_path)}")
    except Exception:
        pass


# =========================================================
# 处理 Cloudflare 整页 5 秒盾 (完全照搬你的有效逻辑)
# =========================================================
def is_cloudflare_interstitial(sb) -> bool:
    try:
        page_source = sb.get_page_source()
        title = sb.get_title().lower() if sb.get_title() else ""
        indicators = ["Just a moment", "Verify you are human", "Checking your browser", "Checking if the site connection is secure"]
        for ind in indicators:
            if ind in page_source:
                return True
        if "just a moment" in title or "attention required" in title:
            return True
        
        body_len = sb.execute_script('(function() { return document.body ? document.body.innerText.length : 0; })();')
        if body_len is not None and body_len < 200 and "challenges.cloudflare.com" in page_source:
            return True
        return False
    except:
        return False

def bypass_cloudflare_interstitial(sb, account_index, max_attempts=3) -> bool:
    print("    🛡️ 检测到 CF 5秒盾，准备破除...")
    take_screenshot(sb, account_index, "01-1_CF5秒盾拦截")
    for attempt in range(max_attempts):
        print(f"      ▶ 尝试绕过 ({attempt+1}/{max_attempts})...")
        try:
            sb.uc_gui_click_captcha()
            time.sleep(6)
            if not is_cloudflare_interstitial(sb):
                print("      ✅ CF 5秒盾已通过！")
                take_screenshot(sb, account_index, f"01-2_CF盾绕过成功")
                return True
        except Exception as e:
            print(f"      ⚠️ 绕过异常: {e}")
        time.sleep(3)
    take_screenshot(sb, account_index, "01-3_CF盾绕过失败")
    return False


# =========================================================
# 处理 Turnstile 组件 (完全照搬你的有效逻辑)
# =========================================================
def handle_turnstile_verification(sb, account_index) -> bool:
    try:
        cookie_btn = 'button[data-cky-tag="accept-button"]'
        if sb.is_element_visible(cookie_btn):
            print("    🍪 清理 Cookie 弹窗干扰...")
            sb.click(cookie_btn)
            time.sleep(1)
    except:
        pass

    sb.execute_script('''
        try {
            var t = document.querySelector('.cf-turnstile') || 
                    document.querySelector('iframe[src*="challenges.cloudflare"]') || 
                    document.querySelector('iframe[src*="turnstile"]');
            if (t) t.scrollIntoView({behavior:'smooth', block:'center'});
        } catch(e) {}
    ''')
    time.sleep(2)
    take_screenshot(sb, account_index, "03_处理Turnstile验证前")

    has_turnstile = False
    for _ in range(15):
        if (sb.is_element_present('iframe[src*="challenges.cloudflare"]') or 
            sb.is_element_present('iframe[src*="turnstile"]') or 
            sb.is_element_present('.cf-turnstile') or 
            sb.is_element_present('input[name="cf-turnstile-response"]')):
            has_turnstile = True
            break
        time.sleep(1)

    if not has_turnstile:
        print("    🟢 无感验证通过 (未发现 Turnstile)")
        return True

    print("    🧩 发现验证码，执行拟人点击...")
    verified = False
    
    for attempt in range(1, 4):
        print(f"      ▶ 点击尝试 ({attempt}/3)...")
        try:
            sb.uc_gui_click_captcha()
        except:
            pass
            
        for _ in range(10):
            if sb.is_element_present('input[name="cf-turnstile-response"]'):
                token = sb.get_attribute('input[name="cf-turnstile-response"]', 'value')
                if token and len(token) > 20:
                    print("      ✅ 物理点击成功，已获取 Token！")
                    verified = True
                    break
            time.sleep(1)
            
        if verified:
            break

    if not verified:
        print("    ⏳ 等待验证码自动计算 (最多30秒)...")
        for _ in range(30):
            if sb.is_element_present('input[name="cf-turnstile-response"]'):
                token = sb.get_attribute('input[name="cf-turnstile-response"]', 'value')
                if token and len(token) > 20:
                    print("      ✅ 验证码自动放行，已获取 Token！")
                    verified = True
                    break
            time.sleep(1)

    if not verified:
        print("    ❌ 验证失败，未获取有效 Token。")
        take_screenshot(sb, account_index, "03-2_Turnstile验证失败")
        return False
        
    take_screenshot(sb, account_index, "03-1_Turnstile验证成功")
    return True


# =========================================================
# 工具函数
# =========================================================
def parse_due_date(text):
    if not text: return None
    match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', text)
    if match:
        day, month_str, year = match.groups()
        try:
            dt = datetime.strptime(f"{day} {month_str} {year}", "%d %b %Y")
            return dt.strftime("%Y-%m-%d")
        except: pass
    return None


# =========================================================
# 单账号核心处理流程 (融入你提供的 SB 上下文管理器)
# =========================================================
def process_account(account_index, email, pwd):
    # 【核心优化】完美照搬你的 SB 启动方式，并加上了 headless=True 适应云端，加上 window_size 修复分辨率！
    with SB(uc=True, test=True, headless=True, locale="en", window_size="1920,1080", chromium_arg="--disable-blink-features=AutomationControlled") as sb:
        try:
            print(f"  [1/6] 🌐 访问初始面板页...")
            sb.uc_open_with_reconnect(f"{BASE_URL}/dashboard", reconnect_time=8)
            time.sleep(4)
            take_screenshot(sb, account_index, "01_访问初始页")

            if is_cloudflare_interstitial(sb):
                if not bypass_cloudflare_interstitial(sb, account_index):
                    print(f"  ❌ 终止测试：无法绕过 CF 整页拦截。")
                    return None
                time.sleep(3)

            print(f"  [2/6] 🔑 填写账号与密码...")
            try:
                sb.wait_for_element_visible('input#username', timeout=10)
                sb.type('input#username', email)
                sb.type('input#password', pwd)
                take_screenshot(sb, account_index, "02_表单填写")
            except Exception as e:
                print(f"  ❌ 填写失败: 未找到输入框 ({e})")
                take_screenshot(sb, account_index, "02-1_报错")
                return None

            print(f"  [3/6] 🛡️ 处理登录安全验证...")
            is_verified = handle_turnstile_verification(sb, account_index)
            # 【重要拦截】如果没有成功获取CF的Token，直接中止，防止出现截图中红色的报错！
            if not is_verified:
                print(f"  ❌ 验证未通过，为避免被风控，放弃提交表单！")
                return None

            print(f"  [4/6] 🚀 提交登录...")
            try:
                sb.click("button[type='submit']")
            except:
                try:
                    sb.execute_script('(function() { document.querySelector("form").submit(); })();')
                except Exception as e:
                    print(f"  ❌ 点击登录失败: {e}")

            time.sleep(10) 
            take_screenshot(sb, account_index, "04_提交登录跳转后")

            print(f"  [5/6] 📂 提取服务器信息...")
            try:
                element = sb.find_element("xpath", "//span[contains(text(),'Free Server #')]")
                sid = re.search(r'Free Server #(\d+)', element.text).group(1)
                manage_url = f"{BASE_URL}/service/{sid}/manage"
                sb.get(manage_url)
                time.sleep(5)
                take_screenshot(sb, account_index, "05_进入管理页")
            except Exception as e:
                print(f"  ❌ 找不到服务器或登录失败: {e}")
                return None

            print(f"  [6/6] 🔄 尝试续订与提取时间...")
            try:
                renew_btn = sb.find_element("xpath", "//button[contains(text(),'Renew')]")
                renew_btn.click()
                time.sleep(3)
                
                sb.click(f"div#renewService-{sid} button[type='submit']")
                time.sleep(5)
                take_screenshot(sb, account_index, "06_点击续订后")
            except:
                print("    ℹ️ 未找到续期按钮，可能在 CD 中。")

            sb.get(manage_url)
            time.sleep(5)
            take_screenshot(sb, account_index, "07_最终到期时间检查")
            
            due_elem = sb.find_element("xpath", "//h6[contains(text(),'Due date')]/following-sibling::div")
            raw_date = due_elem.text.strip()
            std_date = parse_due_date(raw_date)
            
            print(f"    ✨ 账号 {email} 当前到期时间为: {std_date}")
            return std_date
            
        except Exception as e:
            print(f"  ❌ 账号 {email} 处理时发生异常: {e}")
            take_screenshot(sb, account_index, "99_重置报错")
            return None


# =========================================================
# 程序主入口
# =========================================================
def main():
    print("\n✅ 初始化成功，共载入", len(account_list), "个账号，开始执行任务...\n")
    earliest_date_obj = None
    
    for index, acc in enumerate(account_list, 1):
        email = acc["email"]
        pwd = acc["pwd"]
        
        masked_user = email
        if "@" in email:
            parts = email.split("@")
            masked_user = parts[0][:2] + "***@" + parts[1]
            
        print("=" * 50)
        print(f"▶ 正在测试账号 [{index}/{len(account_list)}]: {masked_user}")
        print("=" * 50)
        
        # 调用核心逻辑
        std_date_str = process_account(index, email, pwd)
        
        if std_date_str:
            current_date_obj = datetime.strptime(std_date_str, "%Y-%m-%d")
            if earliest_date_obj is None or current_date_obj < earliest_date_obj:
                earliest_date_obj = current_date_obj
                
        if index < len(account_list):
            print(f"\n⏳ 冷却 5 秒后准备切换下一账号...\n")
            time.sleep(5)

    if earliest_date_obj:
        earliest_date_str = earliest_date_obj.strftime("%Y-%m-%d")
        print(f"到期时间(标准): {earliest_date_str}")
    else:
        print("[WARN] 所有账号均未能成功获取到期时间")

    print("\n" + "=" * 50)
    print("🎊 所有账号自动化任务执行完毕！")
    print("   ↳ 请前往 GitHub Actions Artifacts 下载并查看截图。")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    main()
