"""Read only selected non-secret local proxy settings."""
import json
from pathlib import Path
import yaml

root = Path('C:/Users/Administrator/AppData/Roaming/com.follow/clash')
cfg = yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8')) or {}
result = {key: cfg.get(key) for key in ['mode', 'mixed-port', 'port', 'socks-port', 'allow-lan', 'interface-name', 'external-controller', 'external-controller-pipe']}
result['tun'] = {key: (cfg.get('tun') or {}).get(key) for key in ['enable', 'stack', 'auto-route', 'strict-route', 'mtu']}
result['dns'] = {key: (cfg.get('dns') or {}).get(key) for key in ['enable', 'enhanced-mode', 'listen']}
result['gateway_rules'] = [rule for rule in cfg.get('rules', []) if isinstance(rule, str) and any(host in rule for host in ['shuaiapi.com', 'micuapi.ai'])]
result['fallback_rule_types'] = [rule.split(',')[0] for rule in cfg.get('rules', []) if isinstance(rule, str) and rule.startswith('MATCH,')]
print(json.dumps(result, ensure_ascii=False))
