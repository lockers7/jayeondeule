* __all__ = [] : import * 시 import 되는 함수(내부함수 숨길겨우), __all__ 없이 import * 시 _함수를 제외하고 모두 import 됨

* 서버 시작 → yield 이전 코드 실행 (초기화)
               ↓
           yield (앱이 요청 수신/처리 중...)
               ↓
  서버 종료 → yield 이후 코드 실행 (정리)

*  