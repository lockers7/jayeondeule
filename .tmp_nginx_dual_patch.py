import os, sys

CAMERA_BLOCK = '''
\t# farm=main, IP 카메라 — ZY-CAMHIPTZ-A-2M (192.168.0.40)
\t# 스냅샷·PTZ : 127.0.0.1:5040 (ipcam_tunnel.service SSH -L)
\t# 스트리밍   : 127.0.0.1:5046 (ipcam_mjpeg.service ffmpeg→Flask)
\t# Basic auth (admin:Wkdusemfdp1@) 는 nginx 가 자동 주입 — 클라이언트 비밀번호 노출 0.
\tlocation /camera/main/stream {
\t\tproxy_pass http://127.0.0.1:5046/stream;
\t\tproxy_buffering off; proxy_cache off;
\t\tproxy_read_timeout 600s;
\t\tproxy_http_version 1.1;
\t\tproxy_set_header Connection '';
\t\tchunked_transfer_encoding off;
\t}
\tlocation /camera/main/ {
\t\tproxy_pass http://127.0.0.1:5040/;
\t\tproxy_set_header Authorization "Basic YWRtaW46V2tkdXNlbWZkcDFA";
\t\tproxy_buffering off; proxy_cache off;
\t\tproxy_read_timeout 60s;
\t\tproxy_http_version 1.1;
\t\tproxy_set_header Connection '';
\t}
'''

def patch(in_path, out_path):
    with open(in_path) as f:
        txt = f.read()
    if 'location /camera/main/stream' in txt:
        # 기존 /camera/main/ (단일 location) 만 있으면 stream 추가가 필요
        if '/camera/main/stream' in txt:
            print(f'{in_path}: stream 이미 등록')
            with open(out_path, 'w') as g: g.write(txt)
            return
    if '/camera/main/' in txt:
        # 기존 단일 location 을 새 두 개 블록으로 교체
        # 가장 간단: 기존 단일 location /camera/main/ ~ } 를 찾아 교체
        import re
        pattern = re.compile(r'\n\s*#[^\n]*\n\s*#[^\n]*\n\s*location /camera/main/ \{[^}]*\}\n', re.DOTALL)
        new = pattern.sub(CAMERA_BLOCK, txt)
        if new == txt:
            # 단순 location 만 있을 수 있음
            pattern2 = re.compile(r'\n\s*location /camera/main/ \{[^}]*\}\n', re.DOTALL)
            new = pattern2.sub(CAMERA_BLOCK, txt)
        if new == txt:
            print(in_path + ': 기존 location 패턴 매치 실패 — 마지막 닫는 괄호 직전에 stream 만 추가')
            idx = new.rfind('}')
            stream_only = '''
\tlocation /camera/main/stream {
\t\tproxy_pass http://127.0.0.1:5046/stream;
\t\tproxy_buffering off; proxy_cache off;
\t\tproxy_read_timeout 600s;
\t\tproxy_http_version 1.1;
\t\tproxy_set_header Connection '';
\t\tchunked_transfer_encoding off;
\t}
'''
            new = new[:idx] + stream_only + new[idx:]
        with open(out_path, 'w') as g: g.write(new)
        print(f'{in_path}: 교체 완료')
    else:
        # 처음 추가 — 마지막 } 직전
        idx = txt.rfind('}')
        new = txt[:idx] + CAMERA_BLOCK + txt[idx:]
        with open(out_path, 'w') as g: g.write(new)
        print(f'{in_path}: 신규 추가 완료')

src = sys.argv[1]
out = sys.argv[2]
patch(src, out)
