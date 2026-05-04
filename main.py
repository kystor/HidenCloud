#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
from seleniumbase import Driver
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
# 如果文件夹不存在，就自动创建一个
if not os.path.exists(SCREENSHOT_DIR):
    os.makedirs(SCREENSHOT_DIR)

def take_screenshot(driver, account_index, step_name):
    """
    辅助函数：给当前网页拍照并保存
    参数说明：
    - account_index: 当前是第几个账号（用于文件名前缀排版）
    - step_name: 这一步做了什么（用于文件名后缀说明）
    """
    # 拼接出像 "acc1_01_访问初始页.png" 这样的文件名
    file_path = os.path.join(SCREENSHOT_DIR, f"acc{account_index}_{step_name}.png")
    try:
        driver.save_screenshot(file_path)
        print(f"    📸 截图保存: {os.path.basename(file_path)}")
    except Exception as e:
        print(f"    ⚠️ 截图保存失败: {e}")


# =========================================================
# 处理 Cloudflare 整页 5 秒盾
# =========================================================
def is_cloudflare_interstitial(driver) -> bool:
    """检查当前页面是否是 Cloudflare 的 5 秒盾等待页"""
    try:
        page_source = driver.get_page_source()
        title = driver.get_title().lower() if driver.get_title() else ""
        indicators = ["Just a moment", "Verify you are human", "Checking your browser", "Checking if the site connection is secure"]
        for ind in indicators:
            if ind in page_source:
                return True
        if "just a moment" in title or "attention required" in title:
            return True
        
        body_len = driver.execute_script('(function() { return document.body ? document.body.innerText.length : 0; })();')
        if body_len is not None and body_len < 200 and "challenges.cloudflare.com" in page_source:
            return True
        return False
    except:
        return False

def bypass_cloudflare_interstitial(driver, account_index, max_attempts=3) -> bool:
    """尝试绕过 Cloudflare 的整页盾，并加入截图反馈"""
    print("    🛡️ 检测到 CF 5秒盾，准备破除...")
    take_screenshot(driver, account_index, "02_发现CF5秒盾拦截")
    
    for attempt in range(max_attempts):
        print(f"      ▶ 尝试绕过 ({attempt+1}/{max_attempts})...")
        try:
            driver.uc_gui_click_captcha()
            time.sleep(6)
            
            # 每次尝试后截图看看结果
            take_screenshot(driver, account_index, f"02-1_CF盾绕过尝试{attempt+1}")
            
            if not is_cloudflare_interstitial(driver):
                print("      ✅ CF 5秒盾已通过！")
                return True
        except Exception as e:
            print(f"      ⚠️ 绕过异常: {e}")
        time.sleep(3)
        
    take_screenshot(driver, account_index, "02-2_CF盾绕过彻底失败")
    return False


# =========================================================
# 处理 Turnstile 组件（打勾验证码）
# =========================================================
def handle_turnstile_verification(driver, account_index) -> bool:
    """综合处理登录页和弹窗中的 CF Turnstile 验证码，加入截图"""
    try:
        cookie_btn = 'button[data-cky-tag="accept-button"]'
        if driver.is_element_visible(cookie_btn):
            print("    🍪 清理 Cookie 弹窗干扰...")
            driver.click(cookie_btn)
            time.sleep(1)
    except:
        pass

    driver.execute_script('''
        try {
            var t = document.querySelector('.cf-turnstile') || 
                    document.querySelector('iframe[src*="challenges.cloudflare"]') || 
                    document.querySelector('iframe[src*="turnstile"]');
            if (t) t.scrollIntoView({behavior:'smooth', block:'center'});
        } catch(e) {}
    ''')
    time.sleep(2)
    take_screenshot(driver, account_index, "04_准备处理Turnstile验证码")

    has_turnstile = False
    for _ in range(15):
        if (driver.is_element_present('iframe[src*="challenges.cloudflare"]') or 
            driver.is_element_present('iframe[src*="turnstile"]') or 
            driver.is_element_present('.cf-turnstile') or 
            driver.is_element_present('input[name="cf-turnstile-response"]')):
            has_turnstile = True
            break
        time.sleep(1)

    if not has_turnstile:
        print("    🟢 无感验证通过 (未发现 Turnstile，可能系统认为你很安全)")
        return True

    print("    🧩 发现验证码，执行拟人点击...")
    verified = False
    
    for attempt in range(1, 4):
        print(f"      ▶ 点击尝试 ({attempt}/3)...")
        try:
            driver.uc_gui_click_captcha()
        except:
            pass
            
        for _ in range(10):
            if driver.is_element_present('input[name="cf-turnstile-response"]'):
                token = driver.get_attribute('input[name="cf-turnstile-response"]', 'value')
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
            if driver.is_element_present('input[name="cf-turnstile-response"]'):
                token = driver.get_attribute('input[name="cf-turnstile-response"]', 'value')
                if token and len(token) > 20:
                    print("      ✅ 验证码自动放行，已获取 Token！")
                    verified = True
                    break
            time.sleep(1)

    if not verified:
        print("    ❌ 验证失败，未获取有效 Token。")
        take_screenshot(driver, account_index, "04-2_Turnstile验证失败")
        return False
        
    take_screenshot(driver, account_index, "04-1_Turnstile验证成功通过")
    return True


# =========================================================
# 工具函数
# =========================================================
def parse_due_date(text):
    """将网页上抓到的日期转换为标准格式 YYYY-MM-DD"""
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
# 单账号核心处理流程
# =========================================================
def process_single_account(driver, email, pwd, account_index):
    """
    在这里，我们将序号 account_index 一直传下去，保证截图的文件名是对的
    """
    try:
        print(f"\n[INFO] >>> 开始处理账号: {email} <<<")
        
        # --- 步骤 1：访问主页 ---
        target_url = f"{BASE_URL}/dashboard"
        print(f"[INFO] 🌐 正在使用智能重连模式访问: {target_url}")
        
        try:
            driver.uc_open_with_reconnect(target_url, reconnect_time=8)
        except AttributeError:
            driver.get(target_url)
            
        time.sleep(4)
        take_screenshot(driver, account_index, "01_访问后台主页")
        
        # 检查是否有 5 秒盾
        if is_cloudflare_interstitial(driver):
            if not bypass_cloudflare_interstitial(driver, account_index):
                print(f"[ERROR] 无法绕过 CF 整页拦截，跳过此账号。")
                return None
            time.sleep(3)
        
        # --- 步骤 2：填写表单 ---
        print("[INFO] 填写账号与密码...")
        driver.type("input#username", email)
        driver.type("input#password", pwd)
        time.sleep(2)
        take_screenshot(driver, account_index, "03_账号密码已填写")
        
        # 处理登录框下方的 Turnstile 验证码
        print("[INFO] 检测并处理登录安全验证...")
        handle_turnstile_verification(driver, account_index)

        # --- 步骤 3：提交登录 ---
        print("[INFO] 提交登录...")
        driver.click("button[type='submit']")
        time.sleep(10)
        take_screenshot(driver, account_index, "05_提交登录跳转后")

        # --- 步骤 4：提取服务器并进入管理页 ---
        try:
            element = driver.find_element("xpath", "//span[contains(text(),'Free Server #')]")
            sid = re.search(r'Free Server #(\d+)', element.text).group(1)
            manage_url = f"{BASE_URL}/service/{sid}/manage"
            driver.get(manage_url)
            time.sleep(5)
            take_screenshot(driver, account_index, "06_成功进入服务器管理页")
        except Exception as e:
            print(f"[ERROR] 找不到服务器或登录失败: {e}")
            take_screenshot(driver, account_index, "06-1_服务器定位或登录失败")
            return None

        # --- 步骤 5：执行续订 ---
        print("[INFO] 尝试点击 Renew 按钮...")
        try:
            renew_btn = driver.find_element("xpath", "//button[contains(text(),'Renew')]")
            renew_btn.click()
            time.sleep(3)
            take_screenshot(driver, account_index, "07_点击Renew弹出确认框")
            
            print("[INFO] 创建订单并支付...")
            driver.click(f"div#renewService-{sid} button[type='submit']")
            time.sleep(5)
            take_screenshot(driver, account_index, "08_确认支付完毕")
        except:
            print("[WARN] 未找到续期按钮，可能还没有到可续期的时间")
            take_screenshot(driver, account_index, "07-1_无续期按钮")

        # --- 步骤 6：抓取最终到期时间 ---
        driver.get(manage_url)
        time.sleep(5)
        take_screenshot(driver, account_index, "09_刷新页面获取最终结果")
        
        due_elem = driver.find_element("xpath", "//h6[contains(text(),'Due date')]/following-sibling::div")
        raw_date = due_elem.text.strip()
        std_date = parse_due_date(raw_date)
        
        print(f"[INFO] 账号 {email} 的当前到期时间为: {std_date}")
        return std_date
        
    except Exception as e:
        print(f"[ERROR] 账号 {email} 处理时发生异常: {e}")
        take_screenshot(driver, account_index, "99_发生崩溃异常")
        return None


# =========================================================
# 程序主入口
# =========================================================
def main():
    print("[INFO] 启动浏览器自动化 (包含强化版 CF 绕过与全程截图)...")
    driver = Driver(headless=True, uc=True)
    
    earliest_date_obj = None
    
    try:
        # enumerate(account_list, 1) 会自动给每个账号编号，1, 2, 3...
        for index, acc in enumerate(account_list, 1):
            email = acc["email"]
            pwd = acc["pwd"]
            
            print("=" * 50)
            print(f"▶ 正在测试账号 [{index}/{len(account_list)}]")
            print("=" * 50)
            
            # 把账号序号 index 也传进去，方便截图命名
            std_date_str = process_single_account(driver, email, pwd, index)
            
            if std_date_str:
                current_date_obj = datetime.strptime(std_date_str, "%Y-%m-%d")
                if earliest_date_obj is None or current_date_obj < earliest_date_obj:
                    earliest_date_obj = current_date_obj
                    
            print(f"\n⏳ 清理环境，冷却后准备切换下一账号...\n")
            driver.delete_all_cookies()
            time.sleep(3)

        if earliest_date_obj:
            earliest_date_str = earliest_date_obj.strftime("%Y-%m-%d")
            print(f"到期时间(标准): {earliest_date_str}")
        else:
            print("[WARN] 所有账号均未能成功获取到期时间")

    finally:
        print("\n" + "=" * 50)
        print("🎊 任务执行完毕，关闭浏览器。")
        print("=" * 50 + "\n")
        driver.quit()

if __name__ == "__main__":
    main()
