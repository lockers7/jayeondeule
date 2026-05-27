# A/B 비교: 후보 결정 vs baseline(golden). 안전핵심 필드(action/devices/circulation) 변화 표시.
import sys, json
BASE="tests/control/prompt_ab/decisions_baseline.json"
def load(p): return json.load(open(p))
def main(cand_label):
    base=load(BASE); cand=load(f"tests/control/prompt_ab/decisions_{cand_label}.json")
    print(f"═══ 비교: baseline vs {cand_label} ═══")
    print(f"  system_prompt: {base['_meta']['system_prompt_len']}자 → {cand['_meta']['system_prompt_len']}자")
    diffs=0
    for k in base:
        if k=="_meta": continue
        b=base[k]["decision"]; c=cand.get(k,{}).get("decision",{})
        same = (b.get("action")==c.get("action") and b.get("circulation")==c.get("circulation") and b.get("devices")==c.get("devices"))
        mark="✅동일" if same else "⚠변화"
        if not same: diffs+=1
        print(f"  [{k}] {mark}")
        if not same:
            print(f"     base: {b.get('action')}·{b.get('circulation')}·{b.get('devices')}")
            print(f"     cand: {c.get('action')}·{c.get('circulation')}·{c.get('devices')}  ({c.get('reason')})")
    print(f"  → 결정 변화 {diffs}/{len([k for k in base if k!='_meta'])} 시나리오")
if __name__=="__main__": main(sys.argv[1] if len(sys.argv)>1 else "candidate")
