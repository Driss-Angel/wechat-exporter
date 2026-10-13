"""把 GitHub 上的恋爱/人物 skill 压成给实时参谋用的「风格指令」（本地 Qwen）。用法: python distill.py <source.md> <out.md> <风格名>"""
import sys, os, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.llm_endpoints import pick_endpoint  # 端点配置见 core/llm_endpoints.py
SRC, OUT, NAME = sys.argv[1:4]
URL, MODEL = pick_endpoint()
SYS = f"""你将收到一份名为「{NAME}」的 AI 技能说明（来自 GitHub）。请把它压缩成一份「回复参谋风格指令」，供另一个模型在替用户起草微信回复时使用。要求：
- 中文 Markdown，600-900 字，只保留对「判断对方状态 + 起草一条回复」直接有用的内容：策略取向、判断信号的方法、措辞规则、常用句式骨架、禁忌。
- 丢掉：问卷、输出格式、演练模式、时间线、来源、身份卡、线下带领清单、多线并行、关于作者本人的生平。
- 如果原文是人物视角，保留他的核心心智模型和决策启发式，但注明「用户要用自己的口吻说，不模仿此人的直播腔和口头禅」。
- 结构固定：
  ## 策略取向（3-5 条）
  ## 怎么读对方（3-5 条）
  ## 措辞规则（5-8 条，含「别这样说→换成」的替换例子）
  ## 句式骨架（5-8 条，方括号留空位）
  ## 这个风格的禁忌（3-5 条）
只输出 Markdown，不要前言。"""
body = dict(model=MODEL, temperature=0.3, max_tokens=3000, messages=[{'role':'system','content':SYS},{'role':'user','content':open(SRC,encoding='utf-8').read()}], chat_template_kwargs={'enable_thinking': False})
r = json.load(urllib.request.urlopen(urllib.request.Request(URL+'/v1/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type':'application/json'}), timeout=600))
c = r['choices'][0]['message']['content'].strip()
open(OUT,'w',encoding='utf-8').write(f"# 风格：{NAME}\n\n" + c + '\n'); print(OUT, len(c), '字')
