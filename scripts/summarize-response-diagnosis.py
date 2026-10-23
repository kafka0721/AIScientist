"""Aggregate this investigation's credential-free transport experiments."""
import collections
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
artifacts = ROOT / 'artifacts'
groups = collections.defaultdict(lambda: {'passed': 0, 'total': 0})
evidence_files = []
for file in sorted(artifacts.glob('response-diagnostic-*.json')):
    report = json.loads(file.read_text(encoding='utf-8'))
    if not any(row.get('kind') == 'model' for row in report['results']):
        continue  # GET/403 is transport evidence, not a model success.
    evidence_files.append(file.name)
    for row in report['results']:
        label = '|'.join(map(str, [row.get('engine', 'httpx'), row['profile'],
                                  row.get('explicit_local_proxy', False), row.get('long', False),
                                  row.get('padding', 0), row.get('pace', False), row.get('pinned_ip')]))
        groups[label]['passed'] += int(row['ok'])
        groups[label]['total'] += 1

summary = {'time': datetime.now().astimezone().isoformat(),
           'columns': ['engine', 'tls_profile', 'explicit_local_proxy', 'long_prompt', 'padding_bytes', 'paced', 'pinned_ip'],
           'results': dict(groups), 'evidence_files': evidence_files}
(artifacts / 'response-diagnosis-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
note = f'''# 大请求上传中断诊断：与模型处理时间解耦

记录时间：{summary['time']}

## 可确认的结论

当前 api.shuaiapi.com / gpt-6-astra 的网络问题已能在脱离 Agent、论文工具和domain记忆的合成请求上复现。故障与较大请求上传相关；同一条件存在成功和失败，不能说是服务固定拒绝某个大小。
较大的请求本机写入缓存后，常在等待HTTP响应头约15.2秒时发生连接重置（Windows错误64），表现为httpcore/httpx.ReadError，SDK再包装为APIConnectionError。本机send_request_body.complete并不证明远端已经收到全部内容。
原生curl对相同215KB请求两次返回exit55（发送失败），两次报告size_upload=65296、HTTP000，说明问题不局限于Python/OpenSSL或LangGraph。

## 实验关键对照

- 约123字节短模型请求，同一连接连续3次完整成功。
- 最初约215KB长输入，在全新TLS1.3/X25519连接上2次均完成握手，随后读取响应头失败，上传后约15秒重置。
- 将提示词保持极短，仅在合法JSON尾部加空白使上传约215KB，TLS1.3下2/2失败；TLS1.2下1/2成功。这排除了“必须是模型处理大量token才会失败”的解释。
- 约32KB短提示词填充上传2/2成功，约64KB同类请求2/2失败。仅两次样本，不能视为精确大小阈值。
- 约215KB真实长输入改用TLS1.2两次均失败。因此只禁用TLS1.3不能解决本轮大请求问题。
- 同样大请求分8KB段并间隔10毫秒发送，1/2成功，另一轮在发送阶段WriteError后ReadError；分段发送不足以保证恢复。
- DNS切换到104.26.6.67时大请求2/2成功；随后固定该IP又2/2成功。固定172.67.74.19则1/2成功。因此存在入口/路径差异或时间波动，不能把某IP认定为永久坏节点，更不应直接长期写死hosts。
- 显式使用本机FlClash HTTP代理127.0.0.1:7890，相同约215KB长输入、每次全新连接，3/3完整成功，约37.8、6.5、3.1秒。37秒/44秒仍能成功说明不是统一15秒模型思考上限。代理对照是可行绕行证据，仍非长期稳定性保证，实验并非严格同时随机分组。

## 当前平台与网络配置

平台仍使用gpt-6-astra、custom-openai、gateway_tls_profile=x25519；此前修复在实际失败栈中生效。
后台进程没有HTTP_PROXY/HTTPS_PROXY/ALL_PROXY等代理环境变量，Windows ProxyEnable=0。
FlClash及其核心正在运行，mixed-port=7890、mode=rule，但配置tun.enable=false，系统代理也关闭。因此“代理软件已打开”不等于平台模型请求已经走该代理。诊断中的默认路径禁用环境代理，显式代理对照仅对诊断客户端生效。
本机WLAN接口MTU=1500，默认出口为192.168.3.10；同时存在Radmin/VirtualBox/Hyper-V适配器，但目前没有证据认定这些适配器导致错误。
尝试pktmon限定中转IP和443端口、仅抓包头，最终捕获0包，已停止并移除本次过滤器。此次抓包没有提供有效数据，不能用它证明丢包位置、TCP RST来源、MTU黑洞或透明代理。
平台最近模型输入约53k–68k tokens、检查点163条消息，文本合计约427k字符；符合长任务请求较大，但本轮未序列化重放科研请求，合成请求不等同于原失败请求逐字复现。

## 下一步修复方向与限制

优先让平台模型客户端显式使用经过大请求验证的本机代理路径（同步/异步、主/辅助/子模型一致，保留TLS证书校验），并在真实检查点续跑后验收。不要仅继续增加超时、扩大重试或把全部故障归结为中转分组。
同时补充读取/写入异常的安全阶段日志：仅记录阶段、大小、时长、异常类型和Windows错误码，避免下次最终异常只剩APIConnectionError而丢失根因。
目前尚未证明究竟是本机过滤、路由器、运营商线路还是CDN链路引发重置；需有效抓包或另一独立网络对照才能定位具体设备。前述TLS握手修复只覆盖一个故障环节，不能据短测成功宣称全部修复。
本轮只诊断；未修改系统网络参数、代理设置、平台生产配置或研究记忆，也未恢复/重放论文任务。原任务保留于失败检查点。科研文件保留到P12。

## 完整实验分组

下表键依次为客户端、TLS配置、显式本机代理、长提示词、空白填充字节、分段发送、固定IP；passed仅计算完整模型流finish_reason=stop。

```json
{json.dumps(dict(groups), ensure_ascii=False, indent=2)}
```

原始报告列表见response-diagnosis-summary.json。最初control实验的TLS1.2误用了X25519-only组、出现握手错误，后续已改为默认TLS1.2曲线；该控制实验不纳入模型结论。
'''
(artifacts / 'response-transport-diagnosis.md').write_text(note, encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False))
