import re

path = '/workspace/jayeondeule/shop/frontend/src/pages/HouseIntroPage.jsx'
with open(path) as f:
    txt = f.read()

# "재배사별 실시간 스트리밍" section 추출
streaming_pattern = re.compile(
    r'\n      \{/\* 재배사별 실시간 스트리밍 \*/\}\n      <section [^\n]*\n.*?      </section>\n',
    re.DOTALL,
)
m = streaming_pattern.search(txt)
if not m:
    raise SystemExit('streaming section not found')
streaming_block = m.group(0)
print('추출:', len(streaming_block), 'chars')

# 원위치에서 제거
txt2 = streaming_pattern.sub('', txt, count=1)

# "스마트팜 시스템 갤러리" 직전에 삽입
target = '\n      {/* 스마트팜 시스템 갤러리 */}\n      <section'
if target not in txt2:
    raise SystemExit('target marker not found')
txt3 = txt2.replace(target, streaming_block + target, 1)

with open(path, 'w') as f:
    f.write(txt3)
print('완료')
