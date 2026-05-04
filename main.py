#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HidenCloud 自动续期脚本（SeleniumBase 兼容增强版）

改动重点：
1. 去掉 headless2，避免 UC 模式在 Linux / GitHub Actions 下的关闭窗口超时问题
2. 优先使用 xvfb（适合 Linux / GitHub Actions）
3. 增加打开页面失败后的重试与回退逻辑
4. 统一封装常用操作，尽量降低 SeleniumBase / Selenium 的接口差异风险
"""

import os
import re
import time
import requests
from datetime import datetime, timezone, timedelta

from seleniumbase import Driver
from selenium.webdriver.common.by import By


# =========================================================
# 配置区域
# =========================================================
HIDENCLOUD = os.getenv("HIDENCLOUD", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
PROXY_SERVER = os.getenv("PROXY_SERVER", "")

BASE_URL = "https://dash.hidencloud.com"
STATE_DIR = "browser_state"
SCREENSHOT_DIR = "screenshots"
USER_DATA_DIR = os.path.abspath(os.path.join(STATE_DIR, "selenium_profile"))

os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# 账号格式：email-----password
if "-----" in HIDENCLOUD:
    HIDEN_EMAIL, HIDEN_PWD = HIDENCLOUD.split("-----", 1)
else:
    raise ValueError("❌ HIDENCLOUD 格式错误，应为 email-----password")


# =========================================================
# 工具函数
# =========================================================
def get_bj_time():
    """返回北京时间字符串"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def send_tg_notification(message, photo_path=None):
    """发送 Telegram 通知，可附带截图"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[WARN] 未配置 TG 信息，跳过发送")
        return

    try:
        if photo_path and os.path.exists(photo_path):
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {
                    "chat_id": TG_CHAT_ID,
                    "caption": message,
                    "parse_mode": "Markdown",
                }
                requests.post(url, files=files, data=data, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TG_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            }
            requests.post(url, json=payload, timeout=10)

        print("[INFO] TG 通知已发送")
    except Exception as e:
        print(f"[ERROR] TG 发送失败: {e}")


def take_screenshot(driver, name):
    """截图并返回文件路径"""
    timestamp = datetime.now().strftime("%H%M%S")
    filename = os.path.join(SCREENSHOT_DIR, f"{timestamp}-{name}.png")
    try:
        driver.save_screenshot(filename)
        print(f"[INFO] 截图 → {filename}")
    except Exception as e:
        print(f"[WARN] 截图失败: {e}")
    return filename


def parse_due_date(text):
    """将页面显示的日期字符串转换为 YYYY-MM-DD 格式"""
    if not text:
        return None

    # 例如：28 Apr 2026
    match = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", text)
    if match:
        day, month_str, year = match.groups()
        try:
            dt = datetime.strptime(f"{day} {month_str} {year}", "%d %b %Y")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # 已经是标准格式
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text

    return None


def find_first(driver, selectors):
    """
    按顺序查找第一个可见元素
    selectors: [(By.CSS_SELECTOR, "..."), (By.XPATH, "...")]
    """
    for by, value in selectors:
        try:
            elem = driver.find_element(by, value)
            if elem and elem.is_displayed():
                return elem
        except Exception:
            continue
    return None


def wait_for_element_visible(driver, by, value, timeout=30, interval=0.5):
    """轮询等待某元素可见"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            elem = driver.find_element(by, value)
            if elem and elem.is_displayed():
                return elem
        except Exception:
            pass
        time.sleep(interval)
    return None


def wait_for_turnstile_token(driver, timeout=90):
    """等待 Cloudflare Turnstile token 生成"""
    print("[INFO] ⏳ 等待 Turnstile 验证通过...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            token = driver.execute_script(
                'return document.querySelector("[name=cf-turnstile-response]")?.value || "";'
            )
            if token and len(token) > 20:
                print("[INFO] ✅ Turnstile token 已生成")
                return True
        except Exception:
            pass

        time.sleep(1)

    return False


def wait_for_url_contains(driver, keyword, timeout=45):
    """等待当前 URL 包含特定关键字"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            if keyword in driver.current_url:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def check_login_error(driver):
    """检查页面是否有登录错误信息"""
    error_selectors = [
        (By.CSS_SELECTOR, ".text-red-500"),
        (By.CSS_SELECTOR, ".alert-danger"),
        (By.CSS_SELECTOR, "[role='alert']"),
        (By.CSS_SELECTOR, ".error"),
        (By.CSS_SELECTOR, ".invalid-feedback"),
    ]

    for by, value in error_selectors:
        try:
            elem = driver.find_element(by, value)
            if elem and elem.is_displayed() and elem.text.strip():
                return elem.text.strip()
        except Exception:
            continue

    return None


def mask_email(email):
    """邮箱脱敏显示"""
    if "@" in email:
        local, domain = email.split("@", 1)
        return f"{local[:3]}***@{domain}"
    return f"{email[:3]}***"


def get_current_due_date(driver):
    """获取当前管理页面的到期时间，返回原始字符串和标准化日期"""
    try:
        due_elem = driver.find_element(
            By.XPATH, "//h6[contains(text(),'Due date')]/following-sibling::div"
        )
        raw = due_elem.text.strip()
        std = parse_due_date(raw)
        return raw, std
    except Exception:
        return "N/A", None


def safe_quit(driver):
    """尽量稳妥地关闭浏览器，避免 finally 里再炸一次"""
    if not driver:
        return

    try:
        driver.quit()
    except Exception as e:
        print(f"[WARN] driver.quit() 失败，已忽略: {e}")

    try:
        service = getattr(driver, "service", None)
        if service:
            service.stop()
    except Exception:
        pass


def open_url_safely(driver, url):
    """
    先尝试 UC 专用打开方式，失败后回退到普通 get。
    这样可以降低 UC + GitHub Actions 环境里窗口关闭超时的概率。
    """
    try:
        if hasattr(driver, "uc_open_with_reconnect"):
            try:
                driver.uc_open_with_reconnect(url, 12)
                return
            except Exception as e:
                print(f"[WARN] uc_open_with_reconnect 失败，改用 driver.get(): {e}")

        driver.get(url)
    except Exception:
        # 把异常继续抛给外层，让外层决定是否换一套浏览器参数重试
        raise


def build_driver(headless=False, xvfb=True):
    """构建浏览器驱动"""
    driver_kwargs = {
        "uc": True,
        "headless": headless,
        "xvfb": xvfb,
        "user_data_dir": USER_DATA_DIR,
        "window_size": "1280,753",
        "disable_csp": True,
        "agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
    }

    # 先不要再使用 headless2，UC 模式下这类组合在 Linux/CI 环境更容易出问题
    # driver_kwargs["headless2"] = True

    if PROXY_SERVER:
        driver_kwargs["proxy"] = PROXY_SERVER
        print(f"[INFO] 使用代理: {PROXY_SERVER}")

    driver = Driver(**driver_kwargs)
    driver.set_page_load_timeout(90)
    driver.set_script_timeout(90)
    return driver


def start_driver_with_fallback():
    """
    优先使用 xvfb + 非 headless 模式；
    如果失败，再回退到 headless 模式尝试一次。
    """
    configs = [
        {"headless": False, "xvfb": True},
        {"headless": True, "xvfb": False},
    ]

    last_error = None

    for idx, cfg in enumerate(configs, start=1):
        driver = None
        try:
            print(
                f"[INFO] 尝试启动浏览器 #{idx} "
                f"(headless={cfg['headless']}, xvfb={cfg['xvfb']})"
            )
            driver = build_driver(headless=cfg["headless"], xvfb=cfg["xvfb"])

            # 先打开一个页面验证浏览器可用性
            open_url_safely(driver, f"{BASE_URL}/dashboard")
            time.sleep(3)
            return driver
        except Exception as e:
            last_error = e
            print(f"[WARN] 第 {idx} 套浏览器参数启动失败: {e}")
            safe_quit(driver)
            time.sleep(2)

    raise last_error


# =========================================================
# 主逻辑
# =========================================================
def main():
    print("[INFO] " + "=" * 50)
    print("[INFO] HidenCloud 自动续期脚本 (SeleniumBase)")
    print("[INFO] " + "=" * 50)
    print(f"[INFO] 📂 状态目录: {USER_DATA_DIR}")
    print(f"[INFO] 📸 截图目录: {SCREENSHOT_DIR}")
    print(f"[INFO] 🌐 访问主页: {BASE_URL}/dashboard")

    driver = None
    final_screenshot = None

    result_status = "❌ 续订失败"
    due_date_before_raw = "N/A"
    due_date_before_std = None
    due_date_after_raw = "N/A"
    due_date_after_std = None
    sid = None

    renew_executed = False
    restricted = False
    days_left = None
    threshold = None

    try:
        # -------------------------------------------------
        # 1) 启动浏览器（带回退）
        # -------------------------------------------------
        driver = start_driver_with_fallback()
        print("[INFO] 浏览器已启动，开始执行流程")

        take_screenshot(driver, "01-initial")

        # -------------------------------------------------
        # 2) 登录判断
        # -------------------------------------------------
        need_login = False
        try:
            if "/auth/login" in driver.current_url:
                need_login = True
            elif driver.find_elements(By.CSS_SELECTOR, "input#username"):
                need_login = True
        except Exception:
            need_login = True

        if need_login:
            print("[INFO] 检测到未登录，开始登录流程")
            take_screenshot(driver, "02-login-page")

            masked_email = mask_email(HIDEN_EMAIL)
            print(f"[INFO] ✍️ 填写邮箱: {masked_email}")

            username_input = wait_for_element_visible(
                driver, By.CSS_SELECTOR, "input#username", timeout=30
            )
            password_input = wait_for_element_visible(
                driver, By.CSS_SELECTOR, "input#password", timeout=30
            )

            if not username_input or not password_input:
                take_screenshot(driver, "ERROR-login-inputs-not-found")
                raise Exception("未找到登录输入框")

            username_input.clear()
            username_input.send_keys(HIDEN_EMAIL)

            password_input.clear()
            password_input.send_keys(HIDEN_PWD)

            take_screenshot(driver, "03-credentials-filled")

            print("[INFO] ⏳ 等待 Turnstile 加载...")
            time.sleep(5)

            # 如果页面上有 turnstile，就尝试点击/触发
            try:
                if driver.find_elements(By.CSS_SELECTOR, ".cf-turnstile"):
                    print("[INFO] 尝试处理 Turnstile...")
                    try:
                        # SeleniumBase 的 UC 辅助点击
                        driver.uc_gui_click_cf(".cf-turnstile")
                    except Exception:
                        # 退回普通点击
                        turnstile = driver.find_element(By.CSS_SELECTOR, ".cf-turnstile")
                        turnstile.click()

                    take_screenshot(driver, "04-turnstile-clicked")

                    if not wait_for_turnstile_token(driver, timeout=90):
                        take_screenshot(driver, "ERROR-turnstile-timeout")
                        raise Exception("Turnstile 验证超时")

                    take_screenshot(driver, "05-token-ready")
                else:
                    print("[WARN] 未找到 Turnstile 元素，继续提交...")
            except Exception as e:
                take_screenshot(driver, "ERROR-turnstile-process")
                raise Exception(f"Turnstile 处理失败: {e}")

            print("[INFO] 提交登录表单")
            submit_btn = find_first(
                driver,
                [
                    (By.CSS_SELECTOR, "button[type='submit']"),
                    (By.XPATH, "//button[contains(., 'Login')]"),
                    (By.XPATH, "//button[contains(., 'Sign in')]"),
                ],
            )

            if not submit_btn:
                take_screenshot(driver, "ERROR-submit-button-not-found")
                raise Exception("未找到登录提交按钮")

            submit_btn.click()
            take_screenshot(driver, "06-login-submitted")

            print("[INFO] ⏳ 等待登录跳转...")
            if not wait_for_url_contains(driver, "/dashboard", timeout=45):
                error_text = check_login_error(driver)
                if error_text:
                    print(f"[ERROR] 登录失败: {error_text}")
                    take_screenshot(driver, "ERROR-login-failed-message")
                    raise Exception(f"登录失败: {error_text}")
                else:
                    time.sleep(5)
                    if "/dashboard" not in driver.current_url:
                        take_screenshot(driver, "ERROR-login-stuck")
                        raise Exception("登录后卡住，未跳转")

            print("[INFO] ✅ 登录成功")
            take_screenshot(driver, "07-login-success")
        else:
            print("[INFO] ✅ 已登录，跳过登录流程")
            take_screenshot(driver, "02-already-logged-in")

        # -------------------------------------------------
        # 3) 提取服务器 ID
        # -------------------------------------------------
        print("[INFO] 提取服务器 ID...")
        take_screenshot(driver, "08-dashboard")
        time.sleep(3)

        try:
            element = driver.find_element(
                By.XPATH, "//span[contains(text(),'Free Server #')]"
            )
            text = element.text.strip()
            print(f"[INFO] 找到服务器文本: {text}")

            match = re.search(r"Free Server #(\d+)", text)
            if match:
                sid = match.group(1)
                print(f"[INFO] ✅ 提取到服务器 ID: {sid}")
        except Exception as e:
            print(f"[ERROR] 页面元素定位失败: {e}")

        if not sid:
            take_screenshot(driver, "ERROR-no-server-id")
            raise Exception("无法提取服务器 ID")

        manage_url = f"{BASE_URL}/service/{sid}/manage"
        print(f"[INFO] 访问管理页面: {BASE_URL}/service/{sid}/manage")
        open_url_safely(driver, manage_url)
        time.sleep(3)
        take_screenshot(driver, "09-manage-page")

        # -------------------------------------------------
        # 4) 获取续订前到期时间
        # -------------------------------------------------
        due_date_before_raw, due_date_before_std = get_current_due_date(driver)
        print(f"[INFO] 续订前到期时间: {due_date_before_raw}")

        # -------------------------------------------------
        # 5) 续期操作
        # -------------------------------------------------
        try:
            print("[INFO] 查找并点击 Renew 按钮...")

            renew_btn = find_first(
                driver,
                [
                    (By.CSS_SELECTOR, "button[onclick*='showRenewAlert']"),
                    (By.XPATH, "//button[.//i[contains(@class, 'bx-recycle')]]"),
                    (By.XPATH, "//button[contains(text(),'Renew')]"),
                ],
            )

            if not renew_btn:
                take_screenshot(driver, "ERROR-renew-button-not-found")
                raise Exception("页面上未找到 Renew 按钮")

            onclick_val = renew_btn.get_attribute("onclick") or ""
            print(f"[INFO] Renew 按钮 onclick: {onclick_val}")

            param_match = re.search(
                r"showRenewAlert\((\d+),\s*(\d+),\s*(true|false)\)", onclick_val
            )
            if param_match:
                days_left = int(param_match.group(1))
                threshold = int(param_match.group(2))
                is_free = param_match.group(3) == "true"
                print(
                    f"[INFO] 到期剩余: {days_left} 天, "
                    f"续期阈值: ≤{threshold} 天, 免费服务: {is_free}"
                )

            renew_btn.click()
            renew_executed = True
            print("[INFO] ✅ Renew 按钮已点击")
            time.sleep(3)
            take_screenshot(driver, "10-renew-clicked")

            # -------------------------------------------------
            # 检测限制弹窗
            # -------------------------------------------------
            time.sleep(1)
            restriction_h3 = ""
            try:
                restriction_h3 = driver.execute_script(
                    "var el = document.querySelector('.fixed.inset-0 h3');"
                    "return el ? el.textContent.trim() : '';"
                )
            except Exception:
                pass

            if "Renewal Restricted" in restriction_h3:
                restricted = True
                alert_text = ""
                try:
                    alert_text = driver.execute_script(
                        "var el = document.querySelector('.fixed.inset-0 p');"
                        "return el ? el.textContent.trim() : '';"
                    )
                except Exception:
                    pass

                print(f"[INFO] ⚠️ 触发限制弹窗: {alert_text}")
                take_screenshot(driver, "11-renewal-restricted-popup")

                try:
                    ok_btn = find_first(
                        driver,
                        [
                            (By.XPATH, "//button[contains(text(),'OK')]"),
                            (By.XPATH, "//button[contains(text(),'Ok')]"),
                        ],
                    )
                    if ok_btn:
                        ok_btn.click()
                        time.sleep(1)
                        print("[INFO] 已关闭限制弹窗")
                except Exception:
                    pass
            else:
                # -------------------------------------------------
                # 正常续期流程
                # -------------------------------------------------
                print("[INFO] 等待续期模态框...")

                modal_selector = f"div#renewService-{sid}"
                modal = wait_for_element_visible(
                    driver, By.CSS_SELECTOR, modal_selector, timeout=15
                )
                if not modal:
                    take_screenshot(driver, "ERROR-renew-modal-not-found")
                    raise Exception("未找到续期模态框")

                take_screenshot(driver, "11-renew-modal-opened")

                print("[INFO] 点击 Create Invoice...")
                submit_btn = find_first(
                    driver,
                    [
                        (
                            By.CSS_SELECTOR,
                            f"{modal_selector} button[type='submit']",
                        ),
                        (
                            By.XPATH,
                            f"//div[@id='renewService-{sid}']//button[@type='submit']",
                        ),
                    ],
                )
                if not submit_btn:
                    take_screenshot(driver, "ERROR-create-invoice-button-not-found")
                    raise Exception("未找到 Create Invoice 按钮")

                submit_btn.click()
                time.sleep(3)
                take_screenshot(driver, "12-invoice-created")

                print("[INFO] 等待支付页面...")
                time.sleep(5)
                take_screenshot(driver, "13-invoice-page")

                # 滚动到底部
                try:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                    take_screenshot(driver, "14-scrolled-to-bottom")
                except Exception:
                    pass

                print("[INFO] 尝试点击 Pay 按钮...")
                pay_clicked = False
                try:
                    pay_clicked = driver.execute_script(
                        """
                        var buttons = document.querySelectorAll('button[type="submit"]');
                        for (var i = 0; i < buttons.length; i++) {
                            var btn = buttons[i];
                            if (btn && btn.innerText && btn.innerText.includes('Pay')) {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                        """
                    )
                except Exception:
                    pay_clicked = False

                if pay_clicked:
                    print("[INFO] ⏳ 等待支付完成...")
                    time.sleep(5)
                    take_screenshot(driver, "15-pay-clicked")
                else:
                    print("[WARN] 未找到 Pay 按钮，可能免费服务自动完成")
                    take_screenshot(driver, "15-no-pay-button")

        except Exception as e:
            print(f"[ERROR] ❌ 续期过程出错: {e}")
            take_screenshot(driver, "ERROR-renew-process")
            raise

        # -------------------------------------------------
        # 6) 获取续订后到期时间
        # -------------------------------------------------
        open_url_safely(driver, manage_url)
        time.sleep(3)

        due_date_after_raw, due_date_after_std = get_current_due_date(driver)
        print(f"[INFO] 续订后到期时间: {due_date_after_raw}")

        final_screenshot = take_screenshot(driver, "16-final-due-date")

        if due_date_after_std:
            print(f"[INFO] 到期时间(标准): {due_date_after_std}")
        else:
            print(f"[INFO] 到期时间(标准): {due_date_after_raw}")

        # -------------------------------------------------
        # 7) 判断结果状态
        # -------------------------------------------------
        if restricted and not renew_executed:
            result_status = "ℹ️ 暂无可续期"
        elif restricted and renew_executed:
            result_status = "ℹ️ 暂无可续期"
        elif due_date_before_std and due_date_after_std:
            if due_date_after_std > due_date_before_std:
                result_status = "✅ 续订成功"
            else:
                result_status = "❌ 续订失败"
        elif renew_executed and not restricted:
            result_status = "⚠️ 续期已执行，请确认"
        else:
            result_status = "❌ 续订失败"

        # -------------------------------------------------
        # 8) 发送 TG 通知
        # -------------------------------------------------
        bj_time = get_bj_time()

        if due_date_before_raw != "N/A" and due_date_after_raw != "N/A":
            if due_date_before_raw == due_date_after_raw:
                change_info = due_date_after_raw
            else:
                change_info = f"{due_date_before_raw} → {due_date_after_raw}"
        else:
            change_info = due_date_after_raw

        extra_info = ""
        if restricted and days_left is not None and threshold is not None:
            extra_info = f"\n剩余: {days_left} 天 (需 ≤{threshold} 天可续)"

        tg_caption = (
            f"{result_status}\n\n"
            f"账号: `{HIDEN_EMAIL}`\n"
            f"服务器: `Free Server #{sid}`\n"
            f"到期: {change_info}{extra_info}\n"
            f"时间: {bj_time}\n\n"
            f"HidenCloud Auto Renew"
        )

        send_tg_notification(tg_caption, photo_path=final_screenshot)
        print(f"[INFO] 任务完成 — {result_status}")

    except Exception as e:
        print(f"[ERROR] ❌ 脚本执行失败: {e}")
        try:
            take_screenshot(driver, "CRITICAL-ERROR")
        except Exception:
            pass
        send_tg_notification(f"❌ HidenCloud 续期失败\n错误: {str(e)[:100]}")
        raise

    finally:
        safe_quit(driver)


if __name__ == "__main__":
    main()
