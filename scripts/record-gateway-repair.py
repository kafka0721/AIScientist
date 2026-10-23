"""Save credential-free repair evidence and research-workspace checkpoints."""
import json
import os
import shutil
import ssl
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
os.environ['WITAISCIENTIST_CONFIG_PATH'] = str(ROOT / 'user-config/config.yaml')
THREAD = '01a0b872-afa2-7292-8565-c479a7f59ac7'
RUN = '01a0b9b9-4ccd-7a50-92ad-0a8200722098'


def hello_size(context):
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    stream = context.wrap_bio(incoming, outgoing, server_hostname='example.com')
    try:
        stream.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return len(outgoing.read())


def main():
    if '--response-diagnosis' in sys.argv:
        artifacts = ROOT / 'artifacts'
        note = (artifacts / 'response-transport-diagnosis.md').read_text(encoding='utf-8')
        if '--record-workspace' in sys.argv:
            for directory in ['development', 'memory']:
                (Path('E:/data') / directory / '2026-09-19_large_request_transport_diagnosis.md').write_text(note, encoding='utf-8')
            destination = Path('E:/data/development/large_request_transport_diagnosis')
            destination.mkdir(exist_ok=True)
            summary = json.loads((artifacts / 'response-diagnosis-summary.json').read_text(encoding='utf-8'))
            for name in summary['evidence_files'] + ['response-diagnosis-summary.json']:
                shutil.copy2(artifacts / name, destination / name)
        print('Recorded large-request transport diagnosis and credential-free evidence.')
        return
    if '--recurrence-audit' in sys.argv:
        note = f'''# 21:18 长任务再次连接中断：纠正稳定性结论

记录时间：{datetime.now().astimezone().isoformat()}
任务：{THREAD}
运行：01a0b9c3-da9b-72c0-ac25-c6629b944ff3

本轮21:07:31实际启动，21:18:16报APIConnectionError结束，执行约10分44秒；此前排队约3分56秒。本次结束后active=0、pending=0、running=0，不是残留队列占用。
当前日志中的请求目标为api.shuaiapi.com，模型gpt-6-astra。当前配置仍为gateway_tls_profile=x25519；失败栈实际经过gateway_transport.py的AsyncGatewayClient.send，且本轮有该组件的连接超时重试日志，因此不能说此前修复完全没有加载。

## 可确认的两段错误

1. 21:13:55子任务task失败：httpcore在_receive_response_headers读取HTTP响应头时发生ReadError，转为httpx.ReadError，再由SDK包装为APIConnectionError。此时已经进入HTTP响应读取阶段，不能一概描述成TLS握手失败或未发出请求。
2. 主任务捕获工具错误后继续列出导入文件、读取manifest；21:17:15仍有HTTP200。随后21:17:42、21:17:59出现SDK重试，21:18:16主模型APIConnectionError结束。本段最终日志未保留底层cause，不能把前一段ReadError直接当作最后请求的已证实根因。

检查点现有163条消息，next=model，错误APIConnectionError。论文清单截至P12导入完成；已有文件与domain记忆保留。
此前短连接、短流式及数分钟生产验证只能证明当时成功，不能证明长任务已彻底稳定。当前证据说明仍存在响应读取异常和连接超时，需进一步定位当前网络路径、HTTP连接复用及中转响应行为，不能未经对照就断言中转分组、模型选择或domain写入有错。
本轮仅诊断和记录，未重放科研任务、未切换中转、未删除进度。
'''
        (ROOT / 'artifacts/gateway-recurrence-audit.md').write_text(note, encoding='utf-8')
        if '--record-workspace' in sys.argv:
            for directory in ['development', 'memory']:
                (Path('E:/data') / directory / '2026-09-19_2118_gateway_recurrence.md').write_text(note, encoding='utf-8')
        print('Recorded 21:18 recurrence diagnosis; research task remains at its saved checkpoint.')
        return
    if '--queue-cleanup' in sys.argv:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:6174/threads/{THREAD}/runs?limit=3', timeout=10) as response:
            runs = json.load(response)
        evidence = [{'run_id': run['run_id'], 'status': run['status'], 'created_at': run['created_at']} for run in runs]
        run_lines = [line for line in (ROOT / '.imaging-scientist-runtime/langgraph_dev.log').read_text(encoding='utf-8', errors='replace').splitlines()
                     if 'run_id=01a0b9c3-da9b-72c0-ac25-c6629b944ff3' in line]
        successful_responses = sum('HTTP Request: POST' in line and '200 OK' in line for line in run_lines)
        note = f'''# 重启后失效运行占用清理

时间：{datetime.now().astimezone().isoformat()}
对话：{THREAD}

21:07:31 通过平台 cancel?action=interrupt 接口将旧运行 {RUN} 从 running 转为 interrupted。后台重启后该运行已没有 worker 执行，但其状态阻挡同对话新消息。
仅清理这一条失效运行；保留历史、检查点、论文笔记及 domain 记忆，未删除任务或重建对话。
队列中的最新运行 01a0b9c3-da9b-72c0-ac25-c6629b944ff3 随即在21:07:31启动，active worker=1，pending=0。配置模型gpt-6-astra，当前中转api.shuaiapi.com。21:07:50日志出现一次SDK请求重试，不能只凭running宣称模型已正常回复。
截至本次记录，恢复后已有{successful_responses}次模型HTTP 200响应；仍有请求重试，未据此宣称所有网络问题永久消失。

采样运行状态：
{json.dumps(evidence, ensure_ascii=False, indent=2)}

本次是队列清理，不是对重启后孤立运行状态问题的永久代码修复。
'''
        (ROOT / 'artifacts/queue-cleanup.md').write_text(note, encoding='utf-8')
        if '--record-workspace' in sys.argv:
            for directory in ['development', 'memory']:
                (Path('E:/data') / directory / '2026-09-19_stale_run_queue_cleanup.md').write_text(note, encoding='utf-8')
        print(json.dumps(evidence, ensure_ascii=False))
        return
    import truststore
    truststore.inject_into_ssl()
    from imaging_scientist.llm.gateway_transport import gateway_ssl_context

    old = ssl.create_default_context()
    old.minimum_version = ssl.TLSVersion.TLSv1_2
    old.set_ecdh_curve('X25519')
    fixed = gateway_ssl_context()
    opener = build_opener(ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:6174/threads/{THREAD}/runs/{RUN}', timeout=10) as response:
        run = json.load(response)
    lines = [line for line in (ROOT / '.imaging-scientist-runtime/langgraph_dev.log').read_text(
        encoding='utf-8', errors='replace').splitlines() if f'run_id={RUN}' in line]
    literature = Path('E:/data/development/image_classification_literature')
    p11 = json.loads((literature / 'ingestion/P11_import.json').read_text(encoding='utf-8'))
    report = dict(
        time=datetime.now().astimezone().isoformat(), thread_id=THREAD, run_id=RUN,
        run_status=run['status'], run_started_at=run['created_at'],
        truststore_clienthello_before=hello_size(old), truststore_clienthello_after=hello_size(fixed),
        certificate_required=fixed.verify_mode == ssl.CERT_REQUIRED,
        hostname_verification=fixed.check_hostname,
        production_http_200=sum('HTTP Request: POST' in line and '200 OK' in line for line in lines),
        production_connection_failures=sum('Gateway connection failed' in line for line in lines),
        production_run_failures=sum('Background run failed' in line for line in lines),
        research_progress={'P11_created': p11['counts'].get('created', 0),
                           'P11_verified': all(row['readback_verified'] and row['retrieval_verified'] for row in p11['rows']),
                           'P12_note_exists': (literature / 'papers/P12_VGG.md').exists()},
        tests={'backend_final_suite': 182, 'backend_routing_selector_suite_before_final_tls_patch': 50,
               'frontend': 6, 'typecheck': 'passed', 'production_build': 'passed'},
        normal_tls_stream_test=json.loads((ROOT / 'artifacts/gateway-repair-live.json').read_text()),
        truststore_stream_test=json.loads((ROOT / 'artifacts/gateway-repair-truststore-live.json').read_text()),
    )
    note = f'''# 2026-09-19 长任务连接中断修复

记录时间：{report['time']}

## 原因与修复

此前两个中转均在 TCP 已连接后、模型 HTTP 请求之前出现 TLS 握手提前关闭（SSLEOFError → ConnectError → APIConnectionError）。OpenSSL 3.5 默认混合密钥交换与当前网络路径存在兼容性问题。不能根据此证据认定是哪一台中间设备或中转服务故障。成功请求与失败的新连接可以同时存在，所以中转有调用记录不矛盾。

部署验证另发现 LangGraph 启动会注入 truststore.SSLContext；其继承的 set_ecdh_curve 只修改未用于实际连接的外壳，未传递至内部 _ctx。回归测试修复前真实失败，ClientHello 为 {report['truststore_clienthello_before']} 字节，修复后为 {report['truststore_clienthello_after']} 字节。

- 模型统一工厂为 custom-openai 的同步、异步、主模型、辅助及子模型连接应用 gateway_tls_profile=x25519；证书和主机名校验保留。TLS 1.2/1.3 仍可协商。
- 对 truststore 仅设置本客户端实例的真实上下文，未改第三方包或全局关闭系统证书验证；私有 _ctx 接口有显式兼容检查及回归测试，升级依赖后应重跑测试。
- 连接阶段增加一次有限重试，并保留 SDK 默认最多两次重试，合计最多六次连接尝试；本层不重放已输出流、读取/写入错误或取消。
- 设置连接20秒、读取300秒、写入60秒、连接池30秒超时。读取超时是等待下一个数据块，并非整项科研任务总时限。
- 前端持久显示失败及保存状态，仅当检查点明确是模型连接/超时失败时显示“从中断处重试”；不自动重放失败工具。

## 验证与部署

后端最终相关测试182项通过；此前路由、子模型、工具选择等50项通过。前端6项通过，TypeScript检查和生产构建通过。
普通环境6次、注入truststore的真实服务环境6次全新连接流式请求均完整返回（finish_reason=stop），当前模型gpt-6-astra。
最终修复已重启加载。20:49:58请求 interrupt 保留检查点；20:50后旧 worker 仍短暂活动，部署时停止旧服务，未声称 cancel 接口立即停止全部子任务。保存的149条主线程消息及待完成task工具检查点在重启后核验保留，20:52:03以空输入恢复原任务。
未完成的子任务从其入口重新核查文件/记忆，可能重复阅读；未对失败工具提供无条件UI自动重试。P11 Swin笔记在重启前已保存，原子任务提示词要求预检及使用稳定候选ID。

任务：{THREAD}
恢复运行：{RUN}
本次采样状态：{report['run_status']}；恢复后模型HTTP 200共{report['production_http_200']}次，连接失败日志{report['production_connection_failures']}条，运行失败日志{report['production_run_failures']}条。
恢复后的实际业务进展：P11 Swin正式新建{report['research_progress']['P11_created']}条domain记忆，三类各一条，原始导入返回逐条回读/检索通过={report['research_progress']['P11_verified']}；P12 VGG笔记已生成={report['research_progress']['P12_note_exists']}。这里只核验执行产物，不等于独立复核论文证据。
这是截至上述时间的实测结果，不等于18篇任务已完成或保证未来网络永不中断。业务进度以image_classification_literature中的实际笔记、导入原始返回和manifest为准。

修复涉及 imaging_scientist/llm/gateway_transport.py、models.py、gateway_catalog.py、config/settings.py、user-config/config.yaml、webui/src/lib/runFailure.ts、hooks/useChat.ts、components/ChatInterface.tsx 及对应测试。
本记录属于开发/运维记忆，不导入科研domain证据库，避免混入论文结论。
'''
    artifacts = ROOT / 'artifacts'
    (artifacts / 'gateway-repair-summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (artifacts / 'gateway-connection-repair.md').write_text(note, encoding='utf-8')
    if '--record-workspace' in sys.argv:
        for directory in ['development', 'memory']:
            (Path('E:/data') / directory / '2026-09-19_gateway_connection_repair.md').write_text(note, encoding='utf-8')
        destination = Path('E:/data/development/gateway_connection_repair')
        destination.mkdir(exist_ok=True)
        for filename in ['gateway-repair-summary.json', 'gateway-repair-live.json', 'gateway-repair-truststore-live.json']:
            shutil.copy2(artifacts / filename, destination / filename)
    print(json.dumps({key: value for key, value in report.items() if 'stream_test' not in key}, ensure_ascii=False))


if __name__ == '__main__':
    main()
