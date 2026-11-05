"""AMRO 连通性只读诊断：区分「网络不可达」与「被网关按 UA 拦截」。

只做只读探活，不上传凭证、不写任何数据。
用法：python scripts/amro_diag.py
"""
import socket
import ssl
import sys
import time

import httpx

AMRO_HOST = "me.sichuanair.com"
AMRO_API_URL = f"https://{AMRO_HOST}/api/v1/plugins/MM_PARTNUMBERCHAXUN_LIST"
AMRO_HOME_URL = f"https://{AMRO_HOST}/views/home.shtml"
AMRO_USER_AGENT = "ReqMan/3.7.1 (AMRO read-only)"
PROBE_FORM = {"I_HHJ": "", "I_ZLGO_TYP": "01", "I_MFRPN": "ST1946-107", "I_MATER_NO_FLEET": ""}


def _dns() -> None:
    print("[DNS]")
    try:
        infos = socket.getaddrinfo(AMRO_HOST, 443, proto=socket.IPPROTO_TCP)
        addresses = sorted({info[4][0] for info in infos})
        for addr in addresses:
            print(f"  {AMRO_HOST} -> {addr}")
            if addr.startswith(("198.18.", "198.19.")):
                print("  [!] 解析到 fake-IP 网段（代理软件 TUN 模式），流量将被代理接管")
    except OSError as exc:
        print(f"  [X] 解析失败：{exc}")


def _tls() -> None:
    print("[TLS]")
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((AMRO_HOST, 443), timeout=15) as sock, \
                ctx.wrap_socket(sock, server_hostname=AMRO_HOST) as tls:
            cert = tls.getpeercert()
            subject = dict(item[0] for item in cert.get("subject", ()))
            print(f"  [OK] 握手成功，证书 CN={subject.get('commonName', '?')}")
            print(f"     证书有效期至 {cert.get('notAfter', '?')}")
    except OSError as exc:
        print(f"  [X] 握手失败：{exc}")


def _request(url: str, *, user_agent: str | None) -> str:
    headers = {"User-Agent": user_agent} if user_agent else {}
    start = time.monotonic()
    try:
        with httpx.Client(verify=True, trust_env=False, timeout=20, headers=headers) as client:
            resp = client.get(url) if url == AMRO_HOME_URL else client.post(url, data=PROBE_FORM)
        elapsed = time.monotonic() - start
        return f"HTTP {resp.status_code} ({elapsed:.2f}s) {resp.text[:60].strip()}"
    except (httpx.HTTPError, OSError) as exc:
        return f"ERR {type(exc).__name__}: {str(exc)[:80]}"


def _probe() -> None:
    print("[探活]")
    print(f"  首页 (浏览器UA)      : {_request(AMRO_HOME_URL, user_agent=AMRO_USER_AGENT)}")
    print(f"  接口 (无 UA)         : {_request(AMRO_API_URL, user_agent=None)}")
    print(f"  接口 (ReqMan UA)     : {_request(AMRO_API_URL, user_agent=AMRO_USER_AGENT)}")


def main() -> int:
    print("=" * 60)
    print(f"AMRO 只读诊断 — {AMRO_HOST}")
    print("=" * 60)
    _dns()
    _tls()
    _probe()
    print("-" * 60)
    print("判读：接口用 ReqMan UA 返回 200/100 说明 UA 正常；")
    print("      仍为 403 说明本机网络出口不在 AMRO 可达范围（需公司网络/VPN）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
