"""端口分配与健康探测。

启动受管工具前先挑一个空闲端口，再轮询 HTTP 健康检查确认工具已经就绪。
只用标准库；网络层的任何失败都折算成“不可用”，不向调用方抛异常。

探测显式禁用系统代理（``HTTP_PROXY`` 等）且不跟随重定向：本机工作台
运行期不访问外网，健康检查更不能被代理返回的 200 误判成存活。
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_TRIES = 20
DEFAULT_TCP_TIMEOUT = 0.4
DEFAULT_HTTP_TIMEOUT = 1.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """拒绝一切重定向：3xx 仍按响应判活，但绝不请求 Location。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


# 显式 ProxyHandler({}) 让回环探测完全不受 HTTP_PROXY/HTTPS_PROXY 影响。
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirect()
)


def pick_free_port(
    preferred: int, *, host: str = "127.0.0.1", tries: int = 20
) -> int | None:
    """从 ``preferred`` 起逐个尝试绑定，返回第一个可用端口。

    绑定成功后立刻关闭 socket，把端口交还调用方；``tries`` 个端口都
    被占用（或超出 65535）时返回 ``None``。只吞 bind 的 :class:`OSError`。
    """
    for offset in range(max(tries, 0)):
        port = preferred + offset
        if port > 65535:
            break
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    return None


def tcp_open(host: str, port: int, timeout: float = 0.4) -> bool:
    """能否与 ``host:port`` 建立 TCP 连接。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_http(url: str, timeout: float = 1.0) -> bool:
    """URL 有 HTTP 响应即为存活：2xx–4xx 返回 ``True``。

    4xx 说明服务在监听、只是路径或权限不对，所以也算活；3xx 同样说明有
    服务在监听，但**不会**跟随 Location 去请求别的主机。5xx、连接失败、
    超时、URL 非法等一律返回 ``False``。探测不走系统代理。
    """
    try:
        with _OPENER.open(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except urllib.error.HTTPError as exc:
        # opener 把 4xx/5xx（以及不跟随的 3xx）变成异常抛出，按状态码重判。
        alive = 200 <= exc.code < 500
        exc.close()
        return alive
    except Exception:  # 连接失败、超时、URL 非法……都视为不存活
        return False
