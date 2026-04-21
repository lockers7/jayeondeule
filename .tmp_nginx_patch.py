import sys, re

src_path = '/tmp/nginx_src.conf'
out_path = '/workspace/jayeondeule/.tmp_nginx_out.conf'

with open(src_path) as f:
    txt = f.read()

if '/camera/main/' in txt:
    print('이미 추가됨')
    sys.exit(0)

block = '''
	# farm=main, IP 카메라 (192.168.0.40 → SSH tunnel 127.0.0.1:5040 → 카메라:80)
	# Basic auth (admin:Wkdusemfdp1@) 를 nginx 에서 자동 주입 — 클라이언트 비밀번호 노출 0.
	location /camera/main/ {
		proxy_pass http://127.0.0.1:5040/;
		proxy_set_header Authorization "Basic YWRtaW46V2tkdXNlbWZkcDFA";
		proxy_buffering off; proxy_cache off;
		proxy_read_timeout 60s;
		proxy_http_version 1.1;
		proxy_set_header Connection '';
	}
'''

# 가장 마지막 } 직전에 삽입 (server 블록 닫기 전)
idx = txt.rfind('}')
new = txt[:idx] + block + txt[idx:]

with open(out_path, 'w') as f:
    f.write(new)
print('done')
