"""川航 AMRO 登录脚本 — 自动提取登录凭证并上传到需求单系统"""
import asyncio, json, sys, tkinter as tk
from tkinter import messagebox
SERVER_URL = "http://127.0.0.1:5001"
UPLOAD_URL = "http://127.0.0.1:5001/inventory/login/upload"
LOGIN_VERSION = "1"
MSG_P1 = "⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。"
MSG_P2 = "已打开登录页面，请在浏览器中完成川航 AMRO 登录（账号/密码/验证码），登录后请保持页面不动。"
MSG_P3 = "✅ 登录成功，本页面即将就绪。"

def confirm():
    root = tk.Tk(); root.withdraw()
    ok = messagebox.askokcancel("提示", MSG_P1)
    root.destroy()
    return ok

async def main():
    from playwright.async_api import async_playwright
    import httpx
    if not confirm():
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        print(MSG_P2)
        await page.goto("https://me.sichuanair.com/views/home.shtml", wait_until="domcontentloaded")
        deadline = asyncio.get_event_loop().time() + 300
        while asyncio.get_event_loop().time() < deadline:
            cookies = await ctx.cookies()
            names = {c["name"] for c in cookies}
            if "JSESSIONID" in names:
                try:
                    async with httpx.AsyncClient(verify=True, timeout=15, trust_env=False) as client:
                        resp = await client.post(UPLOAD_URL, data={"cookies": json.dumps(cookies, ensure_ascii=False)})
                        resp.raise_for_status()
                except Exception:
                    print(f"无法连接需求单系统（{UPLOAD_URL}），请检查网络后重新运行登录脚本")
                    await browser.close()
                    return
                print(MSG_P3)
                print("✅ 登录成功，请回到网页开始查询")
                root = tk.Tk(); root.withdraw()
                messagebox.showinfo("登录成功", "✅ 登录成功，本页面即将就绪。\n请回到网页开始查询")
                root.destroy()
                await browser.close()
                return
            await asyncio.sleep(2)
        await browser.close()
        raise TimeoutError("登录超时")

if __name__ == "__main__":
    asyncio.run(main())
