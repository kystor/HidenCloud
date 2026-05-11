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
    except Exception:
        pass

# =========================================================
# 处理 Cloudflare 验证 (5秒盾)
# =========================================================
def is_cloudflare_interstitial(sb) -> bool:
    """检测当前页面是否处于 Cloudflare 的拦截页面"""
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
    """尝试自动绕过 CF 5秒盾"""
    print("    🛡️ 检测到 CF 5秒盾，准备破除...")
    for attempt in range(max_attempts):
        print(f"      ▶ 尝试绕过 ({attempt+1}/{max_attempts})...")
        try:
            sb.uc_gui_click_captcha()
            time.sleep(6)
            if not is_cloudflare_interstitial(sb):
                print("      ✅ CF 5秒盾已通过！")
                return True
        except Exception:
            pass
        time.sleep(3)
    return False

def handle_turnstile_verification(sb) -> bool:
    """处理 Cloudflare Turnstile 验证码验证逻辑"""
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
                                # 【流程二】强制 UC 点击 Create Invoice
                                # =========================================================
                                print(f"      🖱️ 2. 对 ID 为 {sid} 的 [Create Invoice] 执行强制 UC 点击...")
                                
                                create_invoice_btn = f"#renewService-{sid} button[type='submit']"
                                
                                try:
                                    sb.wait_for_element_visible(create_invoice_btn, timeout=10)
                                except:
                                    print(f"      ❌ 找不到 Create Invoice 按钮")
                                    take_screenshot(sb, account_index, f"07_ID_{sid}_找不到按钮")
                                    sb.open("https://dash.hidencloud.com/dashboard")
                                    time.sleep(5)
                                    continue
                                
                                # 核心：使用 uc_click 处理隐形 CF 验证
                                sb.uc_click(create_invoice_btn)
                                
                                # 简短等待 + 截图（仅用于确认）
                                time.sleep(2)
                                take_screenshot(sb, account_index, f"07_01_ID_{sid}_UC点击后2秒")
                                
                                # =========================================================
                                # 【流程三】等待支付页面出现
                                # =========================================================
                                print(f"      ⏳ 3. 等待页面跳转至支付页...")
                                
                                pay_btn_selector = "button[type='submit']"
                                
                                try:
                                    sb.wait_for_element_visible(pay_btn_selector, timeout=20)
                                    take_screenshot(sb, account_index, f"08_ID_{sid}_支付确认页")
                                    
                                    print(f"      🖱️ 4. 找到 [Pay] 按钮，执行支付...")
                                    sb.click(pay_btn_selector)
                                    
                                    time.sleep(5)
                                    take_screenshot(sb, account_index, f"09_ID_{sid}_支付完成")
                                    print(f"      ✨ 服务器 {sid} 续期并支付完成！")
                                    
                                    # =========================================================
                                    # 【流程四】重新加载仪表盘，获取实际最新到期时间
                                    # =========================================================
                                    print(f"      🔄 返回仪表盘，重新获取服务器最新到期时间...")
                                    sb.open("https://dash.hidencloud.com/dashboard")
                                    time.sleep(5)
                                    take_screenshot(sb, account_index, f"10_ID_{sid}_续期后仪表盘")
                                    
                                    # 重新解析所有服务器，更新最早到期日期
                                    if sb.is_element_visible(rows_selector):
                                        new_elements = sb.find_elements(rows_selector)
                                        print(f"    📊 续期后扫描到 {len(new_elements)} 台服务器：")
                                        new_earliest = None
                                        for idx in range(len(new_elements)):
                                            row = sb.find_elements(rows_selector)[idx]
                                            row_text = row.text
                                            sid_m = re.search(r'#(\d+)', row_text)
                                            date_m = re.search(r'(\d{2}\s+[A-Za-z]{3}\s+\d{4})', row_text)
                                            if sid_m and date_m:
                                                new_sid = sid_m.group(1)
                                                new_due_str = date_m.group(1)
                                                new_due_date = datetime.strptime(new_due_str, "%d %b %Y")
                                                if not new_earliest or new_due_date < new_earliest:
                                                    new_earliest = new_due_date
                                                print(f"      📦 服务器 #{new_sid}: 到期时间 {new_due_str}")
                                        if new_earliest:
                                            earliest_date_for_account = new_earliest
                                            print(f"    🎯 更新账号最早到期时间为: {earliest_date_for_account.strftime('%d %b %Y')}")
                                    
                                    # 完成续期，跳出循环（不再处理当前账号的其他服务器）
                                    break
                                    
                                except Exception:
                                    current_url = sb.get_current_url()
                                    if "invoice" in current_url.lower() or "payment" in current_url.lower():
                                        print(f"      ⚠️ 页面已跳转但未定位到 Pay 按钮，URL: {current_url}")
                                        take_screenshot(sb, account_index, f"98_ID_{sid}_跳转但无Pay按钮")
                                    else:
                                        print(f"      ❌ 未跳转到支付页，停留在: {current_url}")
                                        take_screenshot(sb, account_index, f"98_ID_{sid}_未跳转")
                            else:
                                print(f"      ℹ️ 管理页未找到续期按钮。请检查截图。")
                                
                            # 若未成功续期，也回到仪表盘，继续检查下一台（如果有）
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
# 修改工作流并推送到 GitHub (CI/CD自动化部分) - 强化版
# =========================================================
def update_github_workflow_cron(global_earliest_date):
    """根据最早到期时间动态更新 workflow cron，并推送到 GitHub（需要有效 TOKEN）"""
    print("\n" + "=" * 50)
    print("⚙️ 开始执行工作流自动优化逻辑...")

    # 1. 读取 token，优先使用 REPO_TOKEN，其次 GITHUB_TOKEN（备用）
    repo_token = os.environ.get("REPO_TOKEN", "").strip()
    if not repo_token:
        repo_token = os.environ.get("GITHUB_TOKEN", "").strip()

    # 2. 定位 workflow 文件
    workflow_dir = ".github/workflows"
    target_file = None
    if os.path.exists(workflow_dir):
        for file in os.listdir(workflow_dir):
            if file.endswith((".yml", ".yaml")):
                target_file = os.path.join(workflow_dir, file)
                break

    if not target_file:
        print("  ⚠️ 未找到 .github/workflows 下的 YAML 文件，跳过 cron 更新。")
        return

    # 3. 生成新的 cron 表达式
    if global_earliest_date:
        now = datetime.utcnow()
        time_left = global_earliest_date - now
        hours_left = time_left.total_seconds() / 3600
        run_in_hours = hours_left - 20
        if run_in_hours <= 0:
            run_in_hours = 4  # 保底4小时后运行
        next_run = now + timedelta(hours=run_in_hours)
        new_cron = f"{next_run.minute} {next_run.hour} {next_run.day} {next_run.month} *"
        print(f"  ⏰ 全局最早到期时间 {global_earliest_date.strftime('%Y-%m-%d %H:%M')} UTC")
        print(f"  📝 新 cron 表达式: '{new_cron}'")
    else:
        print("  ⚠️ 未提取到服务器日期，回退至默认每天0点运行。")
        new_cron = "0 0 * * *"

    # 4. 修改文件内容
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()

        # 替换 cron 字段（支持单引号和双引号）
        new_content = re.sub(r"cron:\s*'.*?'", f"cron: '{new_cron}'", content)
        new_content = re.sub(r'cron:\s*".*?"', f'cron: "{new_cron}"', new_content)

        if new_content == content:
            print("  ℹ️ cron 表达式未变化，无需推送。")
            return

        with open(target_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  ✅ 已更新文件: {target_file}")
    except Exception as e:
        print(f"  ❌ 修改文件失败: {e}")
        return

    # 5. 如果有 token，则推送到 GitHub
    if not repo_token:
        print("  ⚠️ 未检测到有效 Token，跳过推送（文件本地已更新但不会生效）。")
        return

    github_repo = os.environ.get("GITHUB_REPOSITORY")
    if not github_repo:
        print("  ❌ 环境变量 GITHUB_REPOSITORY 缺失，无法推送。")
        return

    print("  🚀 使用 token 推送变更...")
    # 配置 git 用户（无关紧要，仅为标识）
    os.system('git config --global user.name "github-actions[bot]"')
    os.system('git config --global user.email "github-actions[bot]@users.noreply.github.com"')
    # 设置带 token 的远程地址（x-access-token 方式，权限严格检查）
    remote_url = f"https://x-access-token:{repo_token}@github.com/{github_repo}.git"
    os.system(f"git remote set-url origin {remote_url}")

    # 提交并推送
    add_ret = os.system(f"git add {target_file}")
    if add_ret != 0:
        print("  ❌ git add 失败，放弃推送。")
        return

    commit_ret = os.system('git commit -m "🔄 自动更新下次续期时间 [skip ci]"')
    # 允许 commit 失败（可能没有变更），但 push 仍需尝试
    push_ret = os.system("git push origin main")
    if push_ret == 0:
        print("  🌟 已成功推送！GitHub 工作流 cron 即将生效。")
    else:
        print("  ❌ git push 失败！请检查 token 权限（需要 repo+workflow）。")
        print("     常见原因：")
        print("     - Token 缺少 workflows 写权限")
        print("     - 分支保护规则阻止推送")
        print("     - Token 已过期或被吊销")

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
