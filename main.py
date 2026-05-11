import os
import time
import re
from datetime import datetime, timedelta
from seleniumbase import SB

# =========================================================
# 准备工作：设置截图保存的文件夹
# =========================================================
SCREENSHOT_DIR = "screenshots"
if not os.path.exists(SCREENSHOT_DIR):
    os.makedirs(SCREENSHOT_DIR)

def take_screenshot(sb, account_index, step_name):
    """辅助函数：给当前网页拍照并保存，方便排查报错"""
    file_path = os.path.join(SCREENSHOT_DIR, f"acc{account_index}_{step_name}.png")
    try:
        sb.save_screenshot(file_path)
        print(f"    ↳ 📸 截图: {os.path.basename(file_path)}")
    except Exception as e:
        pass

# =========================================================
# 处理 Cloudflare 验证
# =========================================================
def is_cloudflare_interstitial(sb) -> bool:
    try:
        page_source = sb.get_page_source()
        title = sb.get_title().lower() if sb.get_title() else ""
        indicators = ["Just a moment", "Verify you are human", "Checking your browser"]
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
            pass
        time.sleep(3)
    return False

def handle_turnstile_verification(sb) -> bool:
    try:
        cookie_btn = 'button[data-cky-tag="accept-button"]'
        if sb.is_element_visible(cookie_btn):
            sb.click(cookie_btn)
            time.sleep(1)
    except:
        pass

    sb.execute_script('''
        try {
            var t = document.querySelector('.cf-turnstile') || document.querySelector('iframe[src*="turnstile"]');
            if (t) t.scrollIntoView({behavior:'smooth', block:'center'});
        } catch(e) {}
    ''')
    time.sleep(2)

    has_turnstile = False
    for _ in range(15):
        if sb.is_element_present('iframe[src*="challenges.cloudflare"]') or sb.is_element_present('.cf-turnstile'):
            has_turnstile = True
            break
        time.sleep(1)

    if not has_turnstile:
        print("    🟢 无感验证通过")
        return True

    print("    🧩 发现验证码，执行拟人点击...")
    verified = False
    for attempt in range(1, 4):
        try:
            sb.uc_gui_click_captcha()
        except:
            pass
        for _ in range(10):
            if sb.is_element_present('input[name="cf-turnstile-response"]'):
                token = sb.get_attribute('input[name="cf-turnstile-response"]', 'value')
                if token and len(token) > 20:
                    print("      ✅ 验证成功获取 Token！")
                    verified = True
                    break
            time.sleep(1)
        if verified:
            break

    if not verified:
        print("    ❌ 验证失败。")
        return False
    return True

# =========================================================
# 单个账号的处理主流程
# =========================================================
def process_account(account_index, username, password):
    earliest_date_for_account = None 

    with SB(uc=True, test=True, locale="en", chromium_arg="--disable-blink-features=AutomationControlled") as sb:
        print(f"  [1/4] 🌐 访问 HidenCloud 登录页...")
        sb.uc_open_with_reconnect("https://dash.hidencloud.com/dashboard", reconnect_time=8)
        time.sleep(4)
        take_screenshot(sb, account_index, "01_访问初始页")
        
        if is_cloudflare_interstitial(sb):
            if not bypass_cloudflare_interstitial(sb):
                print(f"  ❌ 终止测试：无法绕过 CF 整页拦截。")
                take_screenshot(sb, account_index, "01-1_整页拦截失败")
                return None

        print(f"  [2/4] 🔑 填写账号与密码...")
        try:
            sb.wait_for_element_visible('input[type="email"], input[type="text"]', timeout=10)
            sb.type('input[type="email"], input[type="text"]', username)
            sb.type('input[type="password"]', password)
            take_screenshot(sb, account_index, "02_表单填写")
        except Exception as e:
            print(f"  ❌ 填写表单失败: {e}")
            take_screenshot(sb, account_index, "02_报错")
            return None

        handle_turnstile_verification(sb)
        
        try:
            sb.click('button[type="submit"]')
        except:
            sb.execute_script('(function() { document.querySelector("form").submit(); })();')

        time.sleep(6) 
        take_screenshot(sb, account_index, "04_提交登录后")

        print(f"  [3/4] 📂 获取服务器列表与解析信息...")
        sb.open("https://dash.hidencloud.com/dashboard")
        time.sleep(5)
        take_screenshot(sb, account_index, "05_面板主页")

        print(f"  [4/4] 🔄 智能解析并执行续期逻辑...")
        try:
            rows_selector = "tr[data-accordion-target]"
            if sb.is_element_visible(rows_selector):
                elements = sb.find_elements(rows_selector)
                print(f"    📊 发现 {len(elements)} 台服务器，开始解析状态：")

                for i in range(len(elements)):
                    row = sb.find_elements(rows_selector)[i]
                    row_text = row.text 
                    
                    sid_match = re.search(r'#(\d+)', row_text)
                    date_match = re.search(r'(\d{2}\s+[A-Za-z]{3}\s+\d{4})', row_text)
                    status_match = re.search(r'(Active|Pending|Suspended)', row_text, re.IGNORECASE)

                    if sid_match and date_match and status_match:
                        sid = sid_match.group(1)
                        due_date_str = date_match.group(1)
                        status = status_match.group(1)
                        
                        due_date = datetime.strptime(due_date_str, "%d %b %Y")
                        now = datetime.utcnow()
                        time_left = due_date - now
                        hours_left = time_left.total_seconds() / 3600
                        
                        if not earliest_date_for_account or due_date < earliest_date_for_account:
                            earliest_date_for_account = due_date

                        print(f"    ------------------------------------")
                        print(f"    📦 服务器 ID: {sid}")
                        print(f"    📌 当前状态 : {status}")
                        print(f"    📅 到期时间 : {due_date_str} (剩余 {hours_left:.1f} 小时)")

                        # 距离到期不足 20 小时触发续期
                        if hours_left <= 20:
                            print(f"      ⚠️ 触发续期：距离到期不足 20 小时！")
                            manage_url = f"https://dash.hidencloud.com/service/{sid}/manage"
                            sb.open(manage_url)
                            time.sleep(5)
                            take_screenshot(sb, account_index, f"06_ID_{sid}_管理页")
                            
                            # =========================================================
                            # 【流程一】点击绿色的 Renew 唤出弹窗
                            # =========================================================
                            renew_btn_selector = "button[data-modal-target^='renewService-']"
                            
                            if sb.is_element_visible(renew_btn_selector):
                                print(f"      🖱️ 1. 成功找到 [Renew] 续期按钮，准备点击...")
                                sb.click(renew_btn_selector)
                                time.sleep(3)  
                                take_screenshot(sb, account_index, f"07_ID_{sid}_唤出弹窗")
                                
                                handle_turnstile_verification(sb)
                                
                                # =========================================================
                                # 【流程二】在弹窗中点击 Create Invoice 确认创建账单
                                # =========================================================
                                print(f"      🖱️ 2. 确认续期弹窗，点击 [Create Invoice]...")
                                confirm_btn_selector = f"button[data-modal-hide='renewService-{sid}']"
                                sb.wait_for_element_visible(confirm_btn_selector, timeout=10)
                                sb.click(confirm_btn_selector)
                                
                                # =========================================================
                                # 【流程三】等待页面跳转并点击 Pay 完成支付 (新增步骤)
                                # =========================================================
                                print(f"      ⏳ 3. 等待页面跳转至支付页...")
                                time.sleep(4) # 给网页留出充足的时间跳转并加载
                                
                                take_screenshot(sb, account_index, f"08_ID_{sid}_支付确认页")
                                print(f"      🖱️ 4. 寻找并点击 [Pay] 支付按钮...")
                                
                                # 使用 normalize-space() 清除 HTML 里的换行和空格，精准定位带有 Pay 文字的按钮
                                pay_btn_selector = "//button[@type='submit' and contains(normalize-space(), 'Pay')]"
                                
                                # 等待支付按钮出现，并点击
                                sb.wait_for_element_visible(pay_btn_selector, timeout=15)
                                sb.click(pay_btn_selector)
                                
                                time.sleep(5) # 等待支付成功的反馈页面
                                take_screenshot(sb, account_index, f"09_ID_{sid}_全流程完成")
                                print(f"      ✨ 服务器 {sid} 续期且支付操作完美结束！")
                                
                                earliest_date_for_account = due_date + timedelta(days=30) 
                            else:
                                print(f"      ℹ️ 管理页未找到续期按钮。请检查截图：06_ID_{sid}_管理页.png")
                                
                            # 跑完当前服务器后，回到主面板继续检查下一台
                            sb.open("https://dash.hidencloud.com/dashboard")
                            time.sleep(5)
                        else:
                            print(f"      🟢 判定结果：时间充足，本次跳过续期。")
                    else:
                        print(f"    ⚠️ 无法完整解析该行数据。")
            else:
                print(f"    ℹ️ 未发现任何服务器实例。")
                
        except Exception as e:
            print(f"  ❌ 操作过程中发生错误: {e}")
            take_screenshot(sb, account_index, "99_操作报错")

        print(f"  🎉 账号 {account_index} 测试完成！")
        return earliest_date_for_account

# =========================================================
# 修改工作流并推送到 GitHub
# =========================================================
def update_github_workflow_cron(global_earliest_date):
    """根据最早到期时间和 REPO_TOKEN 的存在情况，动态修改并推送工作流文件"""
    print("\n" + "=" * 50)
    print("⚙️ 开始执行工作流自动优化逻辑...")
    
    repo_token = os.environ.get("REPO_TOKEN", "").strip()
    workflow_dir = ".github/workflows"
    
    target_file = None
    if os.path.exists(workflow_dir):
        for file in os.listdir(workflow_dir):
            if file.endswith(".yml") or file.endswith(".yaml"):
                target_file = os.path.join(workflow_dir, file)
                break
                
    if not target_file:
        print("  ⚠️ 未找到 .github/workflows 下的 YAML 文件，跳过此步骤。")
        return

    # 计算新的 Cron 表达式
    if not repo_token:
        print("  ℹ️ 未检测到有效 REPO_TOKEN，应用默认规则：每天执行一次。")
        new_cron = "0 0 * * *"
    else:
        if global_earliest_date:
            now = datetime.utcnow()
            time_left = global_earliest_date - now
            hours_left = time_left.total_seconds() / 3600
            
            run_in_hours = hours_left - 20
            if run_in_hours <= 0:
                run_in_hours = 4  
                
            next_run = now + timedelta(hours=run_in_hours)
            new_cron = f"{next_run.minute} {next_run.hour} {next_run.day} {next_run.month} *"
            print(f"  ⏰ 已追踪到全局最先到期时间！下一次启动预定在 UTC {next_run.strftime('%Y-%m-%d %H:%M')}")
            print(f"  📝 生成的 Cron 表达式: '{new_cron}'")
        else:
            print("  ⚠️ 未能提取到任何有效服务器日期，回退至默认规则：每天执行一次。")
            new_cron = "0 0 * * *"

    try:
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        new_content = re.sub(r"cron:\s*'.*?'", f"cron: '{new_cron}'", content)
        new_content = re.sub(r'cron:\s*".*?"', f'cron: "{new_cron}"', new_content)
        
        if new_content != content:
            with open(target_file, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"  ✅ 成功将新的时间写入文件: {target_file}")
            
            if repo_token:
                github_repo = os.environ.get("GITHUB_REPOSITORY")
                if github_repo:
                    print("  🚀 正在使用 REPO_TOKEN 提交并推送修改到 GitHub...")
                    os.system('git config --global user.name "github-actions[bot]"')
                    os.system('git config --global user.email "github-actions[bot]@users.noreply.github.com"')
                    os.system(f'git remote set-url origin https://x-access-token:{repo_token}@github.com/{github_repo}.git')
                    os.system(f'git add {target_file}')
                    os.system('git commit -m "🔄 自动更新下次续期时间 [skip ci]"')
                    os.system('git push')
                    print("  🌟 GitHub 仓库时间线已成功更新！")
        else:
            print("  ℹ️ Cron 时间与当前一致，无需提交更改。")
            
    except Exception as e:
        print(f"  ❌ 修改或推送工作流文件时出错: {e}")

# =========================================================
# 程序入口点
# =========================================================
def main():
    accounts_str = os.environ.get("TEST_ACCOUNTS", "你的邮箱@outlook.com:你的密码")
    if not accounts_str:
        return
    
    account_list = [pair.split(':', 1) for pair in accounts_str.split(',') if ':' in pair]
    print(f"\n✅ 初始化成功，开始执行任务...\n")

    global_earliest_date = None 

    for index, (username, password) in enumerate(account_list, 1):
        username, password = username.strip(), password.strip()
        print("=" * 50)
        print(f"▶ 正在测试账号 [{index}/{len(account_list)}]: {username}")
        print("=" * 50)
        try:
            acc_earliest_date = process_account(index, username, password)
            if acc_earliest_date:
                if not global_earliest_date or acc_earliest_date < global_earliest_date:
                    global_earliest_date = acc_earliest_date
        except Exception as e:
            print(f"❌ 崩溃异常: {e}")
        time.sleep(5)
        
    update_github_workflow_cron(global_earliest_date)
    print("\n" + "=" * 50)
    print("🎊 自动化流程全剧终！期待下次唤醒。")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    main()
