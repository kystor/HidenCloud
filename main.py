import os
import time
from seleniumbase import SB

# =========================================================
# 准备工作：设置截图保存的文件夹
# =========================================================
SCREENSHOT_DIR = "screenshots"
if not os.path.exists(SCREENSHOT_DIR):
    os.makedirs(SCREENSHOT_DIR)

def take_screenshot(sb, account_index, step_name):
    """辅助函数：给当前网页拍照并保存，方便排查报错原因"""
    file_path = os.path.join(SCREENSHOT_DIR, f"acc{account_index}_{step_name}.png")
    try:
        sb.save_screenshot(file_path)
        print(f"    ↳ 📸 截图: {os.path.basename(file_path)}")
    except Exception as e:
        pass

# =========================================================
# 处理 Cloudflare 整页 5 秒盾 (完全照搬你的完美逻辑)
# =========================================================
def is_cloudflare_interstitial(sb) -> bool:
    """检查当前页面是否是 Cloudflare 的 5 秒盾等待页"""
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

def bypass_cloudflare_interstitial(sb, max_attempts=3) -> bool:
    """尝试绕过 Cloudflare 的整页盾"""
    print("    🛡️ 检测到 CF 5秒盾，准备破除...")
    for attempt in range(max_attempts):
        print(f"      ▶ 尝试绕过 ({attempt+1}/{max_attempts})...")
        try:
            sb.uc_gui_click_captcha()
            time.sleep(6)
            if not is_cloudflare_interstitial(sb):
                print("      ✅ CF 5秒盾已通过！")
                return True
        except Exception as e:
            print(f"      ⚠️ 绕过异常: {e}")
        time.sleep(3)
    return False

# =========================================================
# 处理 Turnstile 组件 (完全照搬你的完美逻辑)
# =========================================================
def handle_turnstile_verification(sb) -> bool:
    """综合处理登录页和弹窗中的 CF Turnstile 验证码"""
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
        return False
        
    return True

# =========================================================
# 单个账号的处理主流程 (已针对 HidenCloud 修改网址和按钮)
# =========================================================
def process_account(account_index, username, password):
    with SB(uc=True, test=True, locale="en", chromium_arg="--disable-blink-features=AutomationControlled") as sb:
        
        print(f"  [1/6] 🌐 访问 HidenCloud 登录页...")
        # 【修改点1】将网址替换为 HidenCloud 的登录页
        sb.uc_open_with_reconnect("https://panel.hidencloud.com/login", reconnect_time=8)
        time.sleep(4)
        take_screenshot(sb, account_index, "01_访问初始页")

        if is_cloudflare_interstitial(sb):
            if not bypass_cloudflare_interstitial(sb):
                print(f"  ❌ 终止测试：无法绕过 CF 整页拦截。")
                take_screenshot(sb, account_index, "01-1_整页拦截失败")
                return 
            time.sleep(3) 

        print(f"  [2/6] 🔑 填写账号与密码...")
        try:
            # 这里的输入框选择器通用于大多数登录页，保留不动
            sb.wait_for_element_visible('input[type="email"], input[type="text"]', timeout=10)
            sb.type('input[type="email"], input[type="text"]', username)
            sb.type('input[type="password"]', password)
            take_screenshot(sb, account_index, "02_表单填写")
        except Exception as e:
            print(f"  ❌ 填写失败: 未找到输入框 ({e})")
            take_screenshot(sb, account_index, "02_报错")
            return

        print(f"  [3/6] 🛡️ 处理登录安全验证...")
        handle_turnstile_verification(sb)

        print(f"  [4/6] 🚀 提交登录...")
        try:
            # 【修改点2】去掉了原脚本中特有的 `bg-emerald-600` 绿色按钮限制
            # 改为通用的寻找 type="submit" 的提交按钮
            sb.click('button[type="submit"]')
        except:
            try:
                # 备用方案：如果点不到按钮，直接回车提交表单
                sb.execute_script('(function() { document.querySelector("form").submit(); })();')
            except Exception as e:
                print(f"  ❌ 点击登录失败: {e}")

        time.sleep(6) 
        take_screenshot(sb, account_index, "04_提交登录后")

        print(f"  [5/6] 📂 跳转至服务器面板页...")
        # 【修改点3】登录成功后，跳转到 HidenCloud 的主面板 (通常是根目录)
        sb.open("https://panel.hidencloud.com/")
        time.sleep(5)
        take_screenshot(sb, account_index, "05_面板主页")

        print(f"  [6/6] 🔄 扫描并续期/重置...")
        try:
            # 【注意】：由于我无法看到 HidenCloud 面板内部的结构
            # 以下部分保留了原脚本的遍历逻辑，但我把关键词换成了通用的 "Renew"
            # 如果服务器卡片点不进去，你需要根据截图修改这里的选择器 (例如改成提取 a 标签的 href 跳转)
            
            # 寻找页面上可能代表服务器卡片的元素（寻找包含文字的 h3 标题等）
            app_card_selector = "div.cursor-pointer, a[href*='/server/']" 
            
            if sb.is_element_visible(app_card_selector):
                elements = sb.find_elements(app_card_selector)
                app_count = len(elements)
                print(f"    📊 发现 {app_count} 个服务卡片，开始尝试处理：")

                for i in range(app_count):
                    cards = sb.find_elements(app_card_selector)
                    current_card = cards[i]
                    app_name = current_card.text.strip()[:10] # 取前几个字作为简称
                    
                    print(f"    ------------------------------------")
                    print(f"    📦 处理项目 ({i+1}/{app_count}): {app_name}")
                    
                    try:
                        current_card.click()
                        time.sleep(4) 
                        take_screenshot(sb, account_index, f"06_{app_name}_详情页")

                        # 【修改点4】将原先的 'Reset Timer' 改为寻找包含 'Renew' (续期) 的按钮
                        reset_btn_selector = "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'renew')]"
                        
                        if sb.is_element_visible(reset_btn_selector):
                            print(f"      🖱️ 点击 [Renew] 续期按钮...")
                            sb.click(reset_btn_selector)
                            time.sleep(5)  
                            take_screenshot(sb, account_index, f"07_{app_name}_弹窗")
                            
                            print(f"      🛡️ 处理可能的弹窗验证...")
                            handle_turnstile_verification(sb)
                            take_screenshot(sb, account_index, f"08_{app_name}_验证后")

                            # 尝试点击确认按钮
                            print(f"      🖱️ 确认续期...")
                            sb.execute_script('''
                                (function() {
                                    var btns = document.querySelectorAll('button');
                                    for(var i=0; i<btns.length; i++) {
                                        var t = btns[i].innerText.toLowerCase();
                                        if(t.includes('confirm') || t.includes('yes') || t.includes('renew')) {
                                            btns[i].click();
                                            break;
                                        }
                                    }
                                })();
                            ''')
                            time.sleep(5) 
                            print(f"      ✨ 操作完成！")
                        else:
                            print(f"      ℹ️ 当前页面未找到续期按钮。")
                    except Exception as inner_e:
                        print(f"      ⚠️ 点击卡片或续期报错: {inner_e}")
                    
                    print(f"      🔙 返回列表页...")
                    sb.open("https://panel.hidencloud.com/")
                    time.sleep(5)

            else:
                print(f"    ℹ️ 未在主页发现任何可点击的服务器卡片。")
                
        except Exception as e:
            print(f"  ❌ 操作过程中发生错误: {e}")
            take_screenshot(sb, account_index, "99_操作报错")

        print(f"  🎉 账号 {account_index} 测试完成！")

# =========================================================
# 程序入口点
# =========================================================
def main():
    # 为了方便新手本地测试，如果你没有设置环境变量，这里直接写死一个测试账号
    # 实际部署时，它依然会优先读取环境变量 TEST_ACCOUNTS
    accounts_str = os.environ.get("TEST_ACCOUNTS", "你的邮箱@outlook.com:你的密码")
    
    if not accounts_str:
        print("❌ 错误：没有找到账号配置！")
        return

    account_list = []
    for pair in accounts_str.split(','):
        pair = pair.strip()
        if not pair:
            continue
        if ':' in pair:
            username, password = pair.split(':', 1) 
            account_list.append((username.strip(), password.strip()))
        else:
            print(f"⚠️ 警告：跳过无效账号格式 -> {pair}")

    print(f"\n✅ 初始化成功，共载入 {len(account_list)} 个账号，开始执行任务...\n")

    for index, (username, password) in enumerate(account_list, 1):
        masked_user = username
        if "@" in username:
            parts = username.split("@")
            masked_user = parts[0][:2] + "***@" + parts[1]
            
        print("=" * 50)
        print(f"▶ 正在测试账号 [{index}/{len(account_list)}]: {masked_user}")
        print("=" * 50)
        
        try:
            process_account(index, username, password)
        except Exception as e:
            print(f"❌ 账号 {masked_user} 发生崩溃异常: {e}")
            
        if index < len(account_list):
            print(f"\n⏳ 冷却 5 秒后准备切换下一账号...\n")
            time.sleep(5)

    print("\n" + "=" * 50)
    print("🎊 所有账号自动化任务执行完毕！")
    print("   ↳ 请前往存储目录下载并查看截图。")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    main()
