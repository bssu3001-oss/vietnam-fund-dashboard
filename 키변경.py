import json

new_key = input("새 API 키를 붙여넣으세요: ").strip()

with open('/Users/minjifully/Desktop/ai-work/베트남펀드_대시보드/설정.json') as f:
    cfg = json.load(f)

cfg['anthropic_api_key'] = new_key

with open('/Users/minjifully/Desktop/ai-work/베트남펀드_대시보드/설정.json', 'w') as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print('저장 완료!')
