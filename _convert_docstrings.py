"""
docstring → separator comment block 변환 스크립트 (v2)
여러 줄 함수 정의 및 class docstring도 처리
"""
import re
import os

SEPARATOR = '# ' + '-' * 236


def extract_docstring(lines, start_idx):
    """start_idx부터 docstring을 추출. (내용 리스트, 끝 인덱스) 반환"""
    i = start_idx
    while i < len(lines) and lines[i].strip() == '':
        i += 1

    if i >= len(lines):
        return None, start_idx

    stripped = lines[i].strip()
    if not stripped.startswith('"""'):
        return None, start_idx

    content_lines = []

    if stripped == '"""':
        i += 1
        while i < len(lines) and '"""' not in lines[i].strip():
            content_lines.append(lines[i])
            i += 1
        return content_lines, i
    elif stripped.endswith('"""') and len(stripped) > 3 and stripped.count('"""') == 2:
        text = stripped[3:-3].strip()
        return [text + '\n'] if text else [], i
    else:
        first = stripped[3:].strip()
        if first:
            content_lines.append(first + '\n')
        i += 1
        while i < len(lines) and '"""' not in lines[i].strip():
            content_lines.append(lines[i])
            i += 1
        return content_lines, i


def parse_docstring_content(content_lines):
    """docstring 내용을 description, args, returns로 분리"""
    description = []
    args = []
    returns = []
    section = 'desc'

    for line in content_lines:
        s = line.strip()
        if not s:
            continue

        if s in ('Args:', 'Arguments:'):
            section = 'args'
            continue
        if s.startswith('Args:'):
            section = 'args'
            rest = s[5:].strip()
            if rest:
                args.append(rest)
            continue
        if s in ('Returns:', 'Yields:'):
            section = 'returns'
            continue
        if s.startswith('Returns:') or s.startswith('Yields:'):
            section = 'returns'
            colon_pos = s.index(':')
            rest = s[colon_pos + 1:].strip()
            if rest:
                returns.append(rest)
            continue
        if s in ('Raises:',) or s.startswith('Raises:'):
            section = 'raises'
            continue

        if section == 'desc':
            description.append(s)
        elif section == 'args':
            args.append(s)
        elif section == 'returns':
            returns.append(s)

    return description, args, returns


def find_separator_above(new_lines):
    """new_lines의 끝에서 위로 올라가며 separator block을 찾음"""
    i = len(new_lines) - 1
    while i >= 0 and new_lines[i].strip() == '':
        i -= 1

    if i < 0:
        return None

    if not new_lines[i].strip().startswith('# ' + '-' * 10):
        return None

    close_idx = i
    i -= 1
    while i >= 0:
        if new_lines[i].strip().startswith('# ' + '-' * 10):
            return {'start': i, 'end': close_idx}
        if not new_lines[i].strip().startswith('#'):
            return None
        i -= 1
    return None


def extract_separator_content(new_lines, sep_info):
    """separator block 안의 내용을 추출"""
    content = []
    for i in range(sep_info['start'] + 1, sep_info['end']):
        line = new_lines[i].strip()
        if line.startswith('#'):
            line = line[1:].strip()
        content.append(line)
    return content


def build_comment_block(indent, title_lines, description, args, returns):
    """새로운 comment block 생성"""
    sep = indent + SEPARATOR
    lines = [sep + '\n']

    for t in title_lines:
        if t:
            lines.append(f"{indent}# {t}\n")

    for d in description:
        if d and d not in title_lines:
            lines.append(f"{indent}# {d}\n")

    if args:
        first_arg = args[0]
        lines.append(f"{indent}# Args: {first_arg}\n")
        for arg in args[1:]:
            lines.append(f"{indent}#       {arg}\n")

    if returns:
        ret_text = ' '.join(returns)
        lines.append(f"{indent}# Returns: {ret_text}\n")

    lines.append(sep + '\n')
    return lines


def find_def_or_class_line(new_lines):
    """new_lines의 끝에서 가장 최근 def/class 정의를 찾음 (여러줄 포함)"""
    i = len(new_lines) - 1

    # 끝에서부터 def 또는 class가 포함된 줄 찾기
    # 여러줄 함수 정의: def ... (\n    arg1,\n    arg2,\n) -> Type:\n
    # 마지막 줄은 ) -> Type: 또는 ): 형태

    while i >= 0:
        stripped = new_lines[i].strip()
        if stripped.startswith('def ') or stripped.startswith('async def ') or stripped.startswith('class '):
            return i
        i -= 1
    return -1


def is_def_or_class_end(line):
    """함수/클래스 정의의 마지막 줄인지 확인"""
    stripped = line.rstrip()
    # def func(): 또는 ) -> Type: 또는 ): 또는 class Foo(Bar):
    return stripped.endswith(':')


def process_file(filepath):
    """파일의 모든 함수/클래스 docstring을 comment block으로 변환"""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    new_lines = []
    i = 0
    changes = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 현재 줄이 함수/클래스 정의의 마지막 줄인지 확인
        is_end_of_def = False

        if stripped.endswith(':'):
            # 단일 줄 def/class
            if stripped.startswith('def ') or stripped.startswith('async def ') or stripped.startswith('class '):
                is_end_of_def = True
            # 여러줄 def의 마지막줄 (예: ) -> Dict:  또는  ):)
            elif (stripped.startswith(')') or stripped.endswith('):')) and not stripped.startswith('#'):
                # 위로 올라가서 def가 있는지 확인
                def_idx = find_def_or_class_line(new_lines)
                if def_idx >= 0:
                    is_end_of_def = True

        if is_end_of_def:
            # 다음에 docstring이 있는지 확인
            doc_content, doc_end = extract_docstring(lines, i + 1)

            if doc_content is not None:
                description, args, returns = parse_docstring_content(doc_content)
                indent_size = len(line) - len(line.lstrip())

                # 단일 줄 def인 경우
                if stripped.startswith('def ') or stripped.startswith('async def ') or stripped.startswith('class '):
                    indent = line[:indent_size]
                else:
                    # 여러줄 def의 경우 - def 줄의 indent 사용
                    def_idx = find_def_or_class_line(new_lines)
                    if def_idx >= 0:
                        def_line_content = new_lines[def_idx]
                        indent = def_line_content[:len(def_line_content) - len(def_line_content.lstrip())]
                    else:
                        indent = line[:indent_size]

                sep_info = find_separator_above(new_lines)

                if sep_info:
                    existing_content = extract_separator_content(new_lines, sep_info)
                    has_args = any('Args' in c for c in existing_content)
                    has_returns = any('Returns' in c or 'Return' in c for c in existing_content)

                    if has_args or has_returns:
                        # 이미 상세 주석 있음 → docstring만 제거
                        new_lines.append(line)
                        i = doc_end + 1
                        changes += 1
                        continue

                    title_lines = [c for c in existing_content if c]
                    del new_lines[sep_info['start']:]
                    # 빈줄 정리
                    while new_lines and new_lines[-1].strip() == '':
                        new_lines.pop()
                else:
                    title_lines = description[:1] if description else []
                    description = description[1:] if len(description) > 1 else []

                comment_block = build_comment_block(indent, title_lines, description, args, returns)

                if new_lines and new_lines[-1].strip() != '':
                    new_lines.append('\n')
                new_lines.extend(comment_block)
                new_lines.append(line)

                i = doc_end + 1
                changes += 1
                continue

        new_lines.append(line)
        i += 1

    if changes > 0:
        with open(filepath, 'w') as f:
            f.writelines(new_lines)
        print(f"  {filepath}: {changes}개 docstring 변환 완료")
    else:
        print(f"  {filepath}: 변환 대상 없음")

    return changes


def main():
    target_files = [
        '/workspace/jayeondeule/agri_ai_core/src/ai/mcp_client.py',
        '/workspace/jayeondeule/agri_ai_core/src/ai/llm_client.py',
        '/workspace/jayeondeule/agri_ai_core/src/ai/query_handler_simple.py',
    ]
    total = 0
    for f in target_files:
        total += process_file(f)
    print(f"\n총 {total}개 docstring 변환 완료")


if __name__ == '__main__':
    main()
