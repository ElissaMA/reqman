"""川航 AMRO 登录脚本 — 人工完成手机验证+账号登录后，手动确认再提取凭证上传到 ReqMan 定检准备系统"""
import asyncio, json, os, sys, tkinter as tk
from tkinter import messagebox
SERVER_URL = "http://127.0.0.1:5001"
UPLOAD_URL = "http://127.0.0.1:5001/inventory/login/upload"
LOGIN_VERSION = "3"
MSG_P1 = "⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。"
MSG_P2 = "已打开登录页面，请先在浏览器中接收并输入手机验证码，再输入账号密码完成川航 AMRO 登录；登录成功后保持页面，点击页面右下角「✅ 完成登录」按钮，或回到此窗口按回车键。"
MSG_P3 = "✅ 登录成功，本页面即将就绪。"

# 注入到 AMRO 页面的悬浮「完成登录」按钮（每次页面加载都注入，按 id 去重）
_INIT_JS = (
    "() => {"
    " if (document.getElementById('__reqman_done_btn')) return;"
    " var b = document.createElement('button');"
    " b.id = '__reqman_done_btn';"
    " b.textContent = '✅ 完成登录';"
    " b.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;padding:10px 16px;background:#198754;color:#fff;border:none;border-radius:8px;font-size:15px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3)';"
    " b.onclick = function(){ if (window.__reqman_login_done) window.__reqman_login_done(); };"
    " (document.body || document.documentElement).appendChild(b);"
    " }"
)


def confirm():
    root = tk.Tk(); root.withdraw()
    ok = messagebox.askokcancel("提示", MSG_P1)
    root.destroy()
    return ok


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
        except Exception:
            pass
    for path in _edge_candidates():
        if os.path.exists(path):
            try:
                return await p.chromium.launch(headless=False, executable_path=path)
            except Exception:
                pass
    print("未检测到 Chrome/Edge，请安装浏览器后重试")
    return None


async def _wait_confirm(done_event):
    """等待手动确认：浏览器内「完成登录」按钮点击，或控制台回车，任一先到。"""
    loop = asyncio.get_event_loop()
    enter_task = loop.run_in_executor(
        None, input,
        "\n>>> 完成手机验证与账号登录后，按回车键获取凭证（或点击页面右下角「✅ 完成登录」）：",
    )
    done_task = asyncio.ensure_future(done_event.wait())
    try:
        await asyncio.wait({enter_task, done_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if not enter_task.done():
            enter_task.cancel()


async def main():
    from playwright.async_api import async_playwright
    import httpx
    if not confirm():
        return
    done = asyncio.Event()
    async with async_playwright() as p:
        browser = await _launch_browser(p)
        if browser is None:
            return
        ctx = await browser.new_context()
        page = await ctx.new_page()

        # 让页面内「完成登录」按钮能回调到本脚本
        async def _on_done():
            done.set()
        await page.expose_function("__reqman_login_done", _on_done)
        # 每次页面加载都注入悬浮按钮
        await page.add_init_script(_INIT_JS)

        print(MSG_P2)
        await page.goto("https://me.sichuanair.com/views/home.shtml", wait_until="domcontentloaded")

        # 等你人工完成手机验证+账号登录后，再确认抓取 cookie
        await _wait_confirm(done)

        cookies = await ctx.cookies()
        names = {c["name"] for c in cookies}
        if "JSESSIONID" not in names:
            print("⚠️ 未检测到 AMRO 登录会话（JSESSIONID），请确认已完成手机验证与账号登录后重新运行登录脚本。")
            await browser.close()
            return
        try:
            async with httpx.AsyncClient(verify=True, timeout=15, trust_env=False) as client:
                resp = await client.post(UPLOAD_URL, data={"cookies": json.dumps(cookies, ensure_ascii=False)})
                resp.raise_for_status()
        except Exception:
            print(f"无法连接ReqMan定检准备系统（{UPLOAD_URL}），请检查网络后重新运行登录脚本")
            await browser.close()
            return
        print(MSG_P3)
        print("✅ 登录成功，请回到网页开始查询")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
