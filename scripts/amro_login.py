"""川航 AMRO 登录脚本：浏览器登录后自动探活、获取账号与凭证并上传。"""
import argparse
import asyncio
import json
import os
import time
import tkinter as tk
from tkinter import messagebox

import httpx

SERVER_URL = "http://127.0.0.1:5001"
UPLOAD_URL = "http://127.0.0.1:5001/inventory/login/upload"
LOGIN_VERSION = "5"
# AMRO 网关按 User-Agent 拦截非浏览器指纹（httpx 默认 python-httpx/x 与 requests 均被 403）；
# 与 src/reqman/services/connectors/amro.py 的 AMRO_USER_AGENT 保持一致。
AMRO_USER_AGENT = "ReqMan/3.7.1 (AMRO read-only)"
AMRO_HOME_URL = "https://me.sichuanair.com/views/home.shtml"
AMRO_API_URL = "https://me.sichuanair.com/api/v1/plugins/MM_PARTNUMBERCHAXUN_LIST"
LOGIN_TIMEOUT_SECONDS = 300
LOGIN_POLL_SECONDS = 2
PROBE_PART_NUMBER = "ST1946-107"
BLOCKED_TOLERANCE = 3
MSG_P1 = "⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。"
MSG_P2 = "已打开登录页面，请在浏览器中完成手机验证码和账号登录；登录成功后脚本会自动检查页面、获取账号与凭证并上传，无需点击按钮或回车。"
MSG_P3 = "✅ 登录成功，本页面即将就绪。"
MSG_BLOCKED = ("AMRO 网关拦截请求（HTTP 403）：请确认本机在公司网络或 VPN 内、可正常访问 "
               "https://me.sichuanair.com ，然后重新登录。")
ACCOUNT_SELECTORS = (
    '[data-account]', '[data-username]', '[data-user]',
    '[id*="account" i]', '[id*="username" i]', '[id*="user" i]',
    '[class*="account" i]', '[class*="username" i]', '[class*="user" i]',
)


def upload_url_for(server_arg: str | None) -> str:
    """解析 Cookie 上传地址：有 --server 则以其为源拼 /inventory/login/upload，否则回退内置常量。"""
    if server_arg:
        return str(server_arg).rstrip("/") + "/inventory/login/upload"
    return UPLOAD_URL



def confirm():
    root = tk.Tk()
    root.withdraw()
    try:
        return messagebox.askokcancel("提示", MSG_P1)
    finally:
        root.destroy()


def _edge_candidates():
    """显式 Edge 路径探测（ProgramFiles 与 x86 变体）。"""
    return [
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]


async def _launch_browser(p):
    """浏览器三级回退：Chrome → Edge → 显式 Edge 路径。"""
    for kwargs in ({"channel": "chrome"}, {"channel": "msedge"}):
        try:
            return await p.chromium.launch(headless=False, **kwargs)
        except Exception:  # noqa: BLE001, S110
            pass
    for path in _edge_candidates():
        if os.path.exists(path):
            try:
                return await p.chromium.launch(headless=False, executable_path=path)
            except Exception:  # noqa: BLE001, S110
                pass
    print("未检测到 Chrome/Edge，请安装浏览器后重试")
    return None


async def _read_account(page) -> str:
    """从登录后页面的可见账号区域读取账号，不从 Cookie 猜测。

    AMRO 首页账号固定渲染在 ``#uaccount``；页面 JS 未渲染完成时该节点为空，
    此时视为未就绪（返回空串），不再回退到宽松选择器误取其他文本。
    """
    try:
        value = await page.evaluate(
            """(selectors) => {
                const fromText = (raw) => {
                    const text = String(raw || '').replace(/\\s+/g, ' ').trim();
                    const labeled = text.match(/(?:账号|用户名|工号|用户|account|username|user)\\s*[:：]?\\s*([A-Za-z0-9_-]{2,32})/i);
                    return labeled ? labeled[1] : '';
                };
                const primary = document.querySelector('#uaccount');
                if (primary) {
                    const raw = primary.getAttribute('data-account') || primary.getAttribute('data-username')
                        || primary.innerText || primary.textContent || '';
                    const account = fromText(raw) || String(raw).trim();
                    if (/^[A-Za-z0-9_-]{2,32}$/.test(account)) return account;
                    return '';
                }
                for (const selector of selectors) {
                    const el = document.querySelector(selector);
                    if (!el) continue;
                    const raw = el.getAttribute('data-account') || el.getAttribute('data-username')
                        || el.value || el.innerText || el.textContent || '';
                    const account = fromText(raw) || String(raw).trim();
                    if (/^[A-Za-z0-9_-]{2,32}$/.test(account)) return account;
                }
                return '';
            }""",
            list(ACCOUNT_SELECTORS),
        )
    except Exception:  # noqa: BLE001
        return ""
    value = str(value or "").strip()
    return value if 2 <= len(value) <= 32 and all(c.isalnum() or c in "_-" for c in value) else ""


async def _amro_cookies(ctx) -> list[dict]:
    cookies = await ctx.cookies("https://me.sichuanair.com")
    return [c for c in cookies if c.get("name") and isinstance(c.get("value"), str) and c.get("value", "").strip()]


async def _probe_login(client: httpx.AsyncClient, cookies: list[dict]) -> str:
    """使用已知只读库存接口严格探活：valid / pending / blocked / retry。"""
    cookie_map = {c["name"]: c["value"] for c in cookies}
    try:
        resp = await client.post(
            AMRO_API_URL,
            data={
                "I_HHJ": "",
                "I_ZLGO_TYP": "01",
                "I_MFRPN": PROBE_PART_NUMBER,
                "I_MATER_NO_FLEET": "",
            },
            cookies=cookie_map,
            timeout=15,
        )
        if resp.status_code == 403:
            return "blocked"
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return "retry"
    if not isinstance(body, dict):
        return "retry"
    code = body.get("code")
    if code == 200:
        return "valid"
    if code == 100:
        return "pending"
    return "retry"


async def _wait_for_login(ctx, page, client: httpx.AsyncClient) -> tuple[str, list[dict]]:
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    last_account = ""
    stable_reads = 0
    last_notice = 0.0
    blocked_reads = 0
    last_state = "waiting"
    while time.monotonic() < deadline:
        if page.is_closed():
            raise RuntimeError("AMRO 登录页面已关闭")
        account = await _read_account(page)
        cookies = await _amro_cookies(ctx)
        jsession = next((c for c in cookies if c.get("name") == "JSESSIONID"), None)
        if account and jsession:
            stable_reads = stable_reads + 1 if account == last_account else 1
            last_account = account
            if stable_reads >= 2:
                state = await _probe_login(client, cookies)
                last_state = state
                if state == "valid":
                    return account, await _amro_cookies(ctx)
                if state == "blocked":
                    blocked_reads += 1
                    if blocked_reads >= BLOCKED_TOLERANCE:
                        raise RuntimeError(MSG_BLOCKED)
                else:
                    blocked_reads = 0
        else:
            stable_reads = 0
            last_account = ""
            blocked_reads = 0
        now = time.monotonic()
        if now - last_notice >= 15:
            print("等待 AMRO 登录完成，脚本将自动检查账号与会话…")
            last_notice = now
        await asyncio.sleep(LOGIN_POLL_SECONDS)
    raise TimeoutError(
        f"等待 AMRO 登录完成超时（最后探活状态：{last_state}"
        f"，账号：{last_account or '未读取到'}），请确认已完成手机验证码和账号登录"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="AMRO 登录脚本")
    parser.add_argument("--server", default="",
                        help="Cookie 上传目标服务地址；由 ReqManLogin 协议携带来源动态传入，缺省用内置兜底地址")
    args = parser.parse_args()
    from playwright.async_api import async_playwright

    if not confirm():
        print("已取消登录")
        return 1
    browser = None
    try:
        async with async_playwright() as p:
            browser = await _launch_browser(p)
            if browser is None:
                return 1
            try:
                ctx = await browser.new_context()
                page = await ctx.new_page()
                print(MSG_P2)
                await page.goto(AMRO_HOME_URL, wait_until="domcontentloaded")
                async with httpx.AsyncClient(
                    verify=True,
                    trust_env=False,
                    headers={"User-Agent": AMRO_USER_AGENT},
                ) as client:
                    account, cookies = await _wait_for_login(ctx, page, client)
                    upload_url = upload_url_for(args.server)
                    response = await client.post(
                        upload_url,
                        data={
                            "account": account,
                            "cookies": json.dumps(cookies, ensure_ascii=False),
                        },
                        headers={"X-Requested-With": "XMLHttpRequest"},
                        timeout=15,
                    )
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict) or body.get("success") is not True:
                        raise RuntimeError("ReqMan 未确认凭证保存")
                print(MSG_P3)
                print(f"登录账号：{account}已上传，网页状态将自动更新")
                return 0
            finally:
                await browser.close()
    except TimeoutError as exc:
        print(f"登录未完成：{exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"登录未完成：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
