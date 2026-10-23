"""Build a research checkpoint from the saved, credential-free diagnostics."""
import json
import shutil
import ssl
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts'


def clienthello(curve=None):
    context = ssl.create_default_context()
    if curve:
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.set_ecdh_curve(curve)
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    stream = context.wrap_bio(incoming, outgoing, server_side=False, server_hostname='sub.micuapi.ai')
    try:
        stream.do_handshake()
    except ssl.SSLWantReadError:
        pass
    data = outgoing.read()
    p = 5 + 4 + 2 + 32
    p += 1 + data[p]
    p += 2 + int.from_bytes(data[p:p+2], 'big')
    p += 1 + data[p]
    end = p + 2 + int.from_bytes(data[p:p+2], 'big')
    p += 2
    groups, shares = [], []
    while p < end:
        kind = int.from_bytes(data[p:p+2], 'big')
        size = int.from_bytes(data[p+2:p+4], 'big')
        body = data[p+4:p+4+size]
        if kind == 10:
            groups = [int.from_bytes(body[i:i+2], 'big') for i in range(2, len(body), 2)]
        if kind == 51:
            i = 2
            while i < len(body):
                group = int.from_bytes(body[i:i+2], 'big')
                key_size = int.from_bytes(body[i+2:i+4], 'big')
                shares.append(dict(group=group, bytes=key_size))
                i += 4 + key_size
        p += 4 + size
    return dict(record_bytes=len(data), supported_groups=groups, key_shares=shares)


def tally(rows, field):
    grouped = {}
    for row in rows:
        counts = grouped.setdefault(row[field], Counter())
        counts['attempts'] += 1
        counts['success' if row['ok'] else 'failure'] += 1
    return {k: dict(v) for k, v in grouped.items()}


def main():
    names = ['two-gateway-diagnostic.json', 'two-gateway-tls-version.json',
             'two-gateway-tls13-groups.json', 'gateway-stream-model-comparison.json',
             'gateway-stream-x25519-comparison.json', 'model-client-settings-audit.json']
    evidence = {name: json.loads((ARTIFACTS / name).read_text(encoding='utf-8')) for name in names}
    settings = evidence['model-client-settings-audit.json']
    summary = dict(time=datetime.now().astimezone().isoformat(), client=settings,
                   hello_default=clienthello(), hello_x25519=clienthello('X25519'),
                   handshake=tally(evidence['two-gateway-tls13-groups.json'], 'client'),
                   streaming=tally(evidence['gateway-stream-x25519-comparison.json'], 'mode'))
    (ARTIFACTS / 'interruption-audit-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    note = f'''# 项目长任务中断排查：两家中转的对照验证

时间：{summary['time']}

## 结论与边界

两家中转 api.shuaiapi.com、sub.micuapi.ai 的实际平台日志均出现模型请求连接异常，第二家在 20:05:35 的子任务栈同样明确停在 start_tls。
最近一轮 20:09:39 启动、20:11:45 报 APIConnectionError 结束。不是固定运行时长或思考时长限制。
独立于 Agent、提示词、论文、记忆的无密钥网络测试能复现故障：TCP 建立后，TLS 握手约 15.5 秒被提前断开，SSLEOFError → EndOfStream → ConnectError。

本轮 OpenSSL {settings['ssl']} 默认握手参数存在与当前链路的兼容性问题。两家均走 Cloudflare，但不能据此认定 Cloudflare 服务端故障。
TLS 1.3 + X25519 对照保持证书校验并成功协商 TLS 1.3；无需据目前证据全局禁用 TLS 1.3。
默认 ClientHello 公共参数：{json.dumps(summary['hello_default'])}
X25519 ClientHello 公共参数：{json.dumps(summary['hello_x25519'])}
这里只保存握手长度、组编号及密钥份额长度，不保存密钥或业务请求。
若默认组包含 4588（0x11ec），其标准名称为 X25519MLKEM768；29 为 X25519。
目前没有抓包定位，不能证明究竟是网络中间设备、MTU/分片、客户端安全软件、CDN 入口策略中的哪一个触发提前关闭。

## 重复对照结果

固定入口 IP、同时对照默认参数与 TLS1.3-X25519，两家各三轮：
{json.dumps(summary['handshake'], ensure_ascii=False)}

当前真实 gpt-6-astra、当前中转、流式短回复、禁用 SDK 自动重试，各三次：
{json.dumps(summary['streaming'], ensure_ascii=False)}

这些是短调用验证，不能把 3 次成功宣称为长期科研任务已稳定。
早期 TLS1.2 对照与 Windows curl 对照也保存在附件中。
无密钥 HTTP 401/403 仅用于确认握手及传输完成，不代表模型授权成功；真实模型对照以完整流式内容和 finish_reason=stop 为成功依据。

## 项目代码中放大故障的问题

1. imaging_scientist/llm/models.py 的 get_chat_model 未配置 TLS 兼容策略，沿用当前 Python/OpenSSL 默认上下文。
2. 实际模型 SDK max_retries={settings['sdk_retries']}（原始请求外最多两次重试），timeout={settings['timeout']}。None 表示没有设置请求超时，不是两分钟或十分钟自动终止。
3. imaging_scientist/imaging_scientist.py 的模型中间件链无模型网络异常恢复策略。ToolErrorHandlerMiddleware 处理工具错误；主模型异常仍向上传播并结束运行。
4. imaging_scientist/middleware/tool_selector.py 在工具数量超过26时增加一次模型选择请求，增加长任务的网络调用次数；选择器失败可降级，但主模型失败仍会退出。
5. webui/src/app/hooks/useChat.ts 的 onError 刷新列表并 toast.error，不会自动恢复失败的后台运行；reconnectOnMount 是重连界面流，不是后台任务重试。

因此，短请求偶尔正常，中转有成功记录；任务持续多步后某次新连接失败，SDK 重试耗尽，整轮突然停止。

## 后续修复重点

优先为模型 HTTP 客户端加入经过本次对照验证的握手兼容配置，保留证书和主机名验证；统一同步、异步及辅助调用的策略。
补充请求开始前/未收到模型输出时的有限重试和错误原因日志；已经输出内容或执行工具后，不应盲目重放整轮以免重复操作。
连续失败应显示持久错误和可恢复检查点，而不是仅闪现通知。
设置明确的连接/读取超时，并用长任务验收验证；不应仅延长超时或继续换中转。

本轮为诊断：未修改生产模型配置、TLS 配置、系统代理、运行中任务或记忆内容，未宣称问题已修复。
'''
    (ARTIFACTS / 'interruption-audit.md').write_text(note, encoding='utf-8')
    import sys
    if '--record-workspace' in sys.argv:
        for directory in ['development', 'memory']:
            (Path('E:/data') / directory / '2026-09-19_two_gateway_interruption_audit.md').write_text(note, encoding='utf-8')
        destination = Path('E:/data/development/two_gateway_interruption_audit')
        destination.mkdir(exist_ok=True)
        for name in names + ['interruption-audit-summary.json']:
            shutil.copy2(ARTIFACTS / name, destination / name)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
