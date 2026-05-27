import { useState } from 'react';
import { Container, Row, Col } from 'react-bootstrap';
import { Link } from 'react-router-dom';

const pages = [
  { id: 'intro', title: '상황버섯이란?', icon: '🍄' },
  { id: 'benefits', title: '주요 효능', icon: '💪' },
  { id: 'research', title: '과학적 연구', icon: '🔬' },
  { id: 'usage', title: '복용법과 장기 복용', icon: '🍵' },
  { id: 'compare', title: '약용버섯 비교', icon: '📊' },
];

function IntroSection() {
  return (
    <>
      <div className="efficacy-card">
        <h3>상황버섯이란?</h3>
        <div className="d-flex gap-3 mb-3">
          <img src="/images/efficacy/mushroom-1.jpg" alt="상황버섯 근접" className="efficacy-img" style={{ width: '50%', height: '280px', objectFit: 'cover', margin: 0 }} />
          <img src="/images/efficacy/mushroom-2.jpg" alt="상황버섯 원목재배" className="efficacy-img" style={{ width: '50%', height: '280px', objectFit: 'cover', margin: 0 }} />
        </div>
        <p>
          상황버섯은 <strong>뽕나무(桑)에서 자라는 누런색(黃) 버섯</strong>이라는 뜻의 다년생 약용 버섯입니다.
          주로 뽕나무의 오래된 고목 그루터기에서 기생하며, 상수리나무, 참나무 등 다양한 활엽수 고목에서도 발견됩니다.
          딱딱한 검은 표면과 단단한 목질 속살이 특징이며, 동의보감과 본초강목 등 고전 의서에 약효가 기록되어 수천 년간 약용으로 사용되어 왔습니다.
        </p>

        <h4>다양한 이름</h4>
        <table className="efficacy-table">
          <thead>
            <tr><th>언어</th><th>이름</th></tr>
          </thead>
          <tbody>
            <tr><td>한국명</td><td>상황버섯 (목질진흙버섯)</td></tr>
            <tr><td>학명</td><td>Phellinus linteus / Sanghuangporus sanghuang</td></tr>
            <tr><td>일본명</td><td>메시마코부 (meshimakobu)</td></tr>
            <tr><td>중국명</td><td>상황(桑黃), 송근(song gen)</td></tr>
            <tr><td>영문명</td><td>Mesima mushroom, Sang-hwang mushroom</td></tr>
          </tbody>
        </table>
      </div>

      <div className="efficacy-card">
        <h3>역사적 배경</h3>
        <p>
          1968년, 일본국립암연구소의 이케가와 데쓰로 박사가 상황버섯 추출물의
          <strong> 종양 억제율 96.7%</strong>를 발표하면서 세계적 주목을 받았습니다.
          Sarcoma 180 종양 세포를 이식한 실험 쥐 8마리 중 7마리가 완치되었으며,
          이후 전 세계 연구기관에서 활발한 연구가 진행되고 있습니다.
        </p>
        <div className="efficacy-highlight">
          <strong>2003년 식품 재분류</strong> — 탁월한 효능에도 부작용이 거의 없는 것으로 확인되어,
          한국에서 의약품에서 <strong>식품으로 재분류</strong>되어 누구나 섭취 가능하게 되었습니다.
        </div>
      </div>

      <div className="efficacy-card">
        <h3>핵심 생물활성 성분</h3>
        <p>상황버섯에는 면역 조절, 항암, 항산화에 핵심적인 다양한 생물활성 성분이 함유되어 있습니다.</p>
        <table className="efficacy-table">
          <thead>
            <tr><th>성분</th><th>함량 (건조 100g)</th><th>주요 역할</th></tr>
          </thead>
          <tbody>
            <tr><td>다당류 (Polysaccharides)</td><td>10~40g</td><td>면역 조절의 핵심</td></tr>
            <tr><td>베타글루칸 (Beta-glucan)</td><td>8~10g</td><td>면역 세포 활성화</td></tr>
            <tr><td>트리터페노이드</td><td>2~6g</td><td>항염증, 혈당 조절</td></tr>
            <tr><td>폴리페놀</td><td>0.5~1g</td><td>항산화</td></tr>
            <tr><td>히스폴론 (Hispolon)</td><td>미량</td><td>항암, 세포자멸사 유도</td></tr>
            <tr><td>히스피딘 (Hispidin)</td><td>미량</td><td>강력한 항산화</td></tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

function BenefitsSection() {
  return (
    <>
      <div className="efficacy-card">
        <h3>항암 효과</h3>
        <img src="/images/efficacy/anticancer.jpg" alt="항암 효과" className="efficacy-img" />
        <p>
          상황버섯은 <strong>"천연 항암제"</strong>로 불릴 만큼 뛰어난 항암 활성을 보여줍니다.
          위암, 식도암, 직장암, 간암, 유방암, 전립선암, 폐암, 결장암 등 <strong>10종 이상의 암세포</strong>에 대해 활성이 확인되었습니다.
          특히 소화기 계통 암 수술 후 <strong>화학요법과 병용 시 면역기능이 항진</strong>되어 치료 보조 효과가 보고되었습니다.
        </p>

        <h4>항암 작용 메커니즘</h4>
        <ul>
          <li><strong>세포 주기 정지</strong> — S-phase에서 세포 주기를 차단하고 P27kip1 발현을 증가</li>
          <li><strong>세포자멸사 유도</strong> — 미토콘드리아 경로를 통한 프로그래밍된 세포 사멸</li>
          <li><strong>혈관신생 억제</strong> — 종양에 영양을 공급하는 새로운 혈관 형성을 차단</li>
          <li><strong>전이 억제</strong> — uPA 하향 조절을 통해 암세포 침습 행동을 억제</li>
        </ul>

        <div className="efficacy-stat-grid">
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number">96.7%</div>
            <div className="efficacy-stat-label">종양 억제율 (1968년 일본 연구)</div>
          </div>
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number">10+</div>
            <div className="efficacy-stat-label">효과 확인된 암 종류</div>
          </div>
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number">7/8</div>
            <div className="efficacy-stat-label">실험 쥐 완치율</div>
          </div>
        </div>
      </div>

      <div className="efficacy-card">
        <h3>면역력 강화</h3>
        <img src="/images/efficacy/immunity.jpg" alt="면역력 강화" className="efficacy-img" />
        <p>상황버섯의 다당류와 베타글루칸은 인체의 면역 체계를 다방면으로 활성화합니다.</p>
        <ul>
          <li><strong>자연살해세포(NK세포) 활성화</strong> — 수지상세포와 대식세포 활성화를 통해 NK세포 세포독성을 강화</li>
          <li><strong>대식세포 활성화</strong> — NO(산화질소) 생성을 통한 종양 살해 활성 극대화</li>
          <li><strong>T세포 증가</strong> — IL-12, IFN-gamma, TNF-alpha 분비 촉진</li>
          <li><strong>B세포 자극</strong> — B 림프구의 공동자극 분자 발현 증진 및 증식 촉진</li>
          <li><strong>보체계(Complement System) 활성화</strong> — 균사체 유래 다당류가 보체 경로를 활성화하여 선천 면역 반응을 강화</li>
        </ul>
        <div className="efficacy-highlight">
          <strong>면역 균형 조절</strong> — 다당류가 IFN-gamma/IL-4 비율을 조절하고 항염증성 IL-10 사이토카인 생산을
          증가시켜, 단순히 면역을 올리는 것이 아니라 <strong>면역 균형을 최적화</strong>합니다.
        </div>
      </div>

      <div className="efficacy-card">
        <h3>항산화 / 항염증 / 기타 효능</h3>

        <h4>항산화 효과</h4>
        <p>
          약용버섯 비교 연구에서 상황버섯의 항산화 효과는 <strong>90%</strong>로 가장 우수한 것으로 나타났습니다.
          항산화 효소 활성(SOD, 카탈라아제, GPx)을 25~40% 증가시키며, 히스피딘 성분이 강력한 DPPH 라디칼 소거 능력을 발휘합니다.
        </p>

        <h4>항염증 효과</h4>
        <p>
          히스폴론이 NF-kappaB 경로 하향 조절을 통해 iNOS, NO, TNF-alpha 생산을 억제하며,
          만성 염증 관련 질환 예방에 기여합니다.
        </p>

        <h4>기타 효능</h4>
        <table className="efficacy-table">
          <thead>
            <tr><th>효능</th><th>세부 내용</th></tr>
          </thead>
          <tbody>
            <tr><td>간 보호</td><td>9종의 펠리눌린 화합물이 간 성상세포 활성화를 15~68% 억제 (실리마린 36.4% 대비 우수). 알코올 및 니코틴으로 인한 간세포 손상에서도 분획추출물이 세포 생존율을 유의미하게 향상</td></tr>
            <tr><td>혈당 조절</td><td>알록산 유발 당뇨 쥐에서 혈당 35.6% 감소</td></tr>
            <tr><td>인슐린 저항성 개선</td><td>8주간 투여 시 장내 미생물 조성 개선, 장벽 기능 유지</td></tr>
            <tr><td>심혈관 건강</td><td>콜레스테롤 수치 저하, 혈압 강하, 고혈압 및 동맥경화 예방</td></tr>
            <tr><td>항균 활성</td><td>병원성 미생물에 대한 항균 효과 확인, 감염 예방에 기여</td></tr>
            <tr><td>피부 건강</td><td>베타글루칸의 피부재생 보호 효과, 활성산소 제거를 통한 피부 노화 방지</td></tr>
            <tr><td>인지 기능</td><td>베타글루칸이 기억력 회복을 지원하는 것으로 보고</td></tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

function ResearchSection() {
  return (
    <>
      <div className="efficacy-card">
        <h3>주요 전임상 연구</h3>
        <img src="/images/efficacy/research.jpg" alt="과학적 연구" className="efficacy-img" />

        <h4>1968년 - 일본국립암연구소</h4>
        <p>
          이케가와 데쓰로 박사가 Sarcoma 180 종양 이식 쥐에서 <strong>종양 억제율 96.7%</strong>를 기록하였습니다.
          실험 쥐 8마리 중 7마리가 완치되어, 상황버섯을 세계적으로 알린 최초의 주요 연구입니다.
        </p>

        <h4>대장암 연구 (BMC Cancer)</h4>
        <p>
          SW480 인간 대장암 세포에서 단백결합 다당류(PBP)가 Wnt/beta-catenin 경로를 변형하여
          종양 성장, 침습, 혈관신생을 동시에 억제하는 것이 확인되었습니다.
        </p>

        <h4>유방암 연구 (Nature / British Journal of Cancer)</h4>
        <p>
          MDA-MB-231 세포에서 AKT 신호 경로 억제를 통해 암세포 성장, 혈관신생, 침습 행동을 억제합니다.
          2025년 연구에서는 Cdc42/N-WASP 신호 경로 조절을 통한 유방암 세포 증식/이동 억제도 확인되었습니다.
        </p>

        <h4>간 보호 연구 (PMC)</h4>
        <p>
          아세트아미노펜(APAP) 유발 급성 간 손상에서 AMPK/Nrf2 신호 경로를 활성화하여
          혈청 ALT, AST 수치를 유의미하게 감소시켰습니다.
        </p>

        <h4>알코올/니코틴 간세포 보호 연구</h4>
        <p>
          알코올과 니코틴에 노출된 간세포에서 상황버섯 분획추출물이 <strong>세포 생존율을 유의미하게 향상</strong>시켜,
          음주 및 흡연으로 인한 간 손상 보호 가능성이 확인되었습니다.
        </p>

        <h4>췌장암 수술 전후 임상 활용 (SAGE Journals, 2025)</h4>
        <p>
          췌장암 수술 전후 상황버섯 추출물의 면역 증강 효과를 평가한 임상 연구로,
          수술 환자의 <strong>면역기능 회복 촉진</strong> 가능성이 보고되었습니다.
        </p>

        <h4>당뇨 연구 (FASEB Journal)</h4>
        <p>
          8주간 다당류 추출물 투여 시 단쇄지방산(SCFA) 생산 박테리아 풍부도가 증가하고,
          장벽 기능 유지 및 전신 염증 감소를 통해 인슐린 저항성이 역전되었습니다.
        </p>
      </div>

      <div className="efficacy-card">
        <h3>인체 사례 보고</h3>
        <p>
          미국 최고 암 전문 병원인 <strong>Memorial Sloan Kettering Cancer Center</strong>에서 정리한 인체 사례입니다.
        </p>

        <div className="efficacy-highlight">
          <strong>사례 1 — 전립선암 (일본)</strong><br/>
          호르몬 불응성 전립선암 환자(골 전이 동반)에서 상황버섯 추출물 복용 후 양성 반응 확인
        </div>

        <div className="efficacy-highlight">
          <strong>사례 2 — 간세포암 (한국)</strong><br/>
          상황버섯 추출물 복용 + 방사선 치료 병행, 18개월 후 <strong>자발적 종양 퇴행</strong> 및 골 전이 소실
        </div>

        <div className="efficacy-highlight">
          <strong>사례 3 — 간세포암 + 폐 전이</strong><br/>
          균사체 추출물 단독 복용, <strong>6개월 후 완전 퇴행</strong> 확인
        </div>
      </div>

      <div className="efficacy-card">
        <h3>연구 출처</h3>
        <ul>
          <li>A Review: The Bioactivities and Pharmacological Applications of Phellinus linteus (PMC, 2019)</li>
          <li>Medicinal mushroom Phellinus linteus as an alternative cancer therapy (PMC, 2012)</li>
          <li>Phellinus linteus - Memorial Sloan Kettering Cancer Center</li>
          <li>P. linteus suppresses breast cancer via AKT inhibition (Nature)</li>
          <li>Protein-bound polysaccharide inhibits colon cancer (BMC Cancer, 2011)</li>
          <li>P. linteus polysaccharide extract improves insulin resistance (FASEB Journal)</li>
          <li>Perioperative Clinical Usage for Pancreatic Cancer (SAGE Journals, 2025)</li>
        </ul>
        <div className="efficacy-highlight">
          <strong>참고</strong> — Memorial Sloan Kettering Cancer Center의 평가에 따르면,
          인체 대상 근거는 아직 제한적이며 잘 설계된 임상시험이 추가로 필요합니다.
          현재까지의 근거 대부분은 세포/동물 실험 수준입니다.
        </div>
      </div>
    </>
  );
}

function UsageSection() {
  return (
    <>
      <div className="efficacy-card">
        <h3>기본 끓이는 방법 (달임법)</h3>
        <img src="/images/efficacy/tea-brewing.jpg" alt="복용법" className="efficacy-img" />
        <p><strong>재료:</strong> 건조 상황버섯 30~50g, 물 2,000mL</p>

        <h4>과정</h4>
        <ol style={{ paddingLeft: '20px', lineHeight: 2.2 }}>
          <li>상황버섯을 잘게 쪼갠다 (표면적 증가로 유효성분 추출 효율 향상)</li>
          <li>물 2,000mL에 넣고 센 불로 가열</li>
          <li>물이 끓기 시작하면 <strong>약한 불</strong>로 낮추어 1,000mL (1/2~1/3)로 줄 때까지 달임</li>
          <li>달인 물만 유리용기에 옮겨 보관</li>
          <li>같은 버섯으로 위 과정을 <strong>5~10회 반복</strong> 우려내기</li>
          <li>모든 회차의 추출물을 혼합하여 냉장 보관</li>
        </ol>

        <div className="efficacy-highlight">
          <strong>주의:</strong> 금속 용기 사용 금지! 금속 성분에 다당체가 흡착되어 영양소가 손실됩니다.
          반드시 <strong>유리그릇 또는 도자기(옹기)</strong>를 사용하세요.
        </div>
      </div>

      <div className="efficacy-card">
        <h3>복용 방법과 용량</h3>
        <table className="efficacy-table">
          <thead>
            <tr><th>구분</th><th>1회 용량</th><th>횟수</th><th>시기</th></tr>
          </thead>
          <tbody>
            <tr><td>일반 건강 유지</td><td>120cc (커피컵 1잔)</td><td>1일 3~4회</td><td>공복 / 식전</td></tr>
            <tr><td>환자분</td><td>120cc</td><td>1일 5~6회</td><td>공복 / 식전</td></tr>
          </tbody>
        </table>
        <ul>
          <li>가급적 <strong>따뜻하게</strong> 섭취하는 것이 흡수율에 유리합니다.</li>
          <li><strong>공복 섭취</strong>가 흡수력이 가장 좋습니다.</li>
        </ul>

        <h4>다양한 섭취 형태</h4>
        <table className="efficacy-table">
          <thead>
            <tr><th>형태</th><th>특징</th><th>편의성</th></tr>
          </thead>
          <tbody>
            <tr><td>달임차</td><td>전통 방식, 유효성분 추출 극대화</td><td>보통</td></tr>
            <tr><td>분말 (가루)</td><td>물/음료에 타서 섭취, 요리에 첨가 가능</td><td>높음</td></tr>
            <tr><td>추출물 캡슐/정제</td><td>정량 섭취 용이, 휴대 편리</td><td>매우 높음</td></tr>
            <tr><td>액상 추출물</td><td>농축 형태, 즉시 섭취 가능</td><td>높음</td></tr>
          </tbody>
        </table>
      </div>

      <div className="efficacy-card">
        <h3>장기 복용의 이점</h3>
        <div className="efficacy-stat-grid">
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number" style={{ fontSize: '1.5rem' }}>🛡️</div>
            <div className="efficacy-stat-label">면역 체계 지속적 강화<br/>NK세포, 대식세포 활성 유지</div>
          </div>
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number" style={{ fontSize: '1.5rem' }}>🔥</div>
            <div className="efficacy-stat-label">만성 염증 감소<br/>NF-kappaB 경로 지속적 억제</div>
          </div>
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number" style={{ fontSize: '1.5rem' }}>🧬</div>
            <div className="efficacy-stat-label">항산화 방어 강화<br/>SOD, 카탈라아제, GPx 유지</div>
          </div>
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number" style={{ fontSize: '1.5rem' }}>🦠</div>
            <div className="efficacy-stat-label">장내 환경 개선<br/>유익균 풍부도 증가</div>
          </div>
        </div>

        <div className="efficacy-highlight">
          <strong>장기 복용 가이드라인:</strong> 1개월 복용 후 <strong>10일간 휴식</strong> → 다시 복용 (주기적 반복).
          체내 적응(tolerance) 방지 및 간/신장 부담을 최소화합니다.
          장기 복용 전 반드시 의료진 상담을 권장합니다.
        </div>
      </div>

      <div className="efficacy-card">
        <h3>부작용 및 주의사항</h3>
        <h4>복용 금기 또는 주의 대상</h4>
        <ul>
          <li><strong>자가면역질환 환자</strong> — 면역 기능 증강이 오히려 악화 요인이 될 수 있습니다.</li>
          <li><strong>면역억제제 복용 중인 환자</strong> — 약물 효과와 상충할 수 있습니다.</li>
          <li><strong>수술 전후</strong> — 면역/혈액 관련 영향 가능성이 있습니다.</li>
          <li><strong>임산부/수유부</strong> — 안전성이 확립되지 않았습니다.</li>
          <li>처음 복용 시 <strong>소량부터</strong> 시작하여 소화기 반응을 확인하세요.</li>
        </ul>
      </div>
    </>
  );
}

function CompareSection() {
  return (
    <>
      <div className="efficacy-card">
        <h3>약용버섯 4종 비교</h3>
        <img src="/images/efficacy/comparison.jpg" alt="약용버섯 비교" className="efficacy-img" />
        <table className="efficacy-table">
          <thead>
            <tr><th>항목</th><th>상황버섯</th><th>영지버섯</th><th>차가버섯</th><th>동충하초</th></tr>
          </thead>
          <tbody>
            <tr><td>별명</td><td>천연항암제</td><td>불로초</td><td>자작나무의 선물</td><td>겨울벌레여름풀</td></tr>
            <tr><td>핵심성분</td><td>베타글루칸, 히스폴론</td><td>가노데릭산, 다당류</td><td>베툴린산, 멜라닌</td><td>코르디세핀</td></tr>
          </tbody>
        </table>
      </div>

      <div className="efficacy-card">
        <h3>효능별 비교</h3>
        <table className="efficacy-table">
          <thead>
            <tr><th>효능</th><th>상황버섯</th><th>영지버섯</th><th>차가버섯</th><th>동충하초</th></tr>
          </thead>
          <tbody>
            <tr><td>항암</td><td className="star-rating">★★★★★</td><td className="star-rating">★★★★</td><td className="star-rating">★★★★</td><td className="star-rating">★★★</td></tr>
            <tr><td>면역력</td><td className="star-rating">★★★★★</td><td className="star-rating">★★★★</td><td className="star-rating">★★★★</td><td className="star-rating">★★★★</td></tr>
            <tr><td>항산화</td><td className="star-rating">★★★★★</td><td className="star-rating">★★★</td><td className="star-rating">★★★★★</td><td className="star-rating">★★★</td></tr>
            <tr><td>간 보호</td><td className="star-rating">★★★★★</td><td className="star-rating">★★★★</td><td className="star-rating">★★★</td><td className="star-rating">★★★</td></tr>
            <tr><td>혈당 조절</td><td className="star-rating">★★★★</td><td className="star-rating">★★★</td><td className="star-rating">★★★★</td><td className="star-rating">★★★</td></tr>
            <tr><td>심신 안정</td><td className="star-rating">★★</td><td className="star-rating">★★★★★</td><td className="star-rating">★★</td><td className="star-rating">★★★</td></tr>
            <tr><td>호흡기</td><td className="star-rating">★★★</td><td className="star-rating">★★★</td><td className="star-rating">★★</td><td className="star-rating">★★★★★</td></tr>
          </tbody>
        </table>

        <div className="efficacy-stat-grid">
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number">90%</div>
            <div className="efficacy-stat-label">상황버섯 항산화 효과</div>
          </div>
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number">78%</div>
            <div className="efficacy-stat-label">차가버섯 항산화 효과</div>
          </div>
          <div className="efficacy-stat-item">
            <div className="efficacy-stat-number">75~91%</div>
            <div className="efficacy-stat-label">암세포 억제율 (상황/차가)</div>
          </div>
        </div>
      </div>

      <div className="efficacy-card">
        <h3>목적별 추천</h3>
        <table className="efficacy-table">
          <thead>
            <tr><th>목적</th><th>1순위 추천</th><th>2순위 추천</th></tr>
          </thead>
          <tbody>
            <tr><td>암 예방 / 보조</td><td><strong>상황버섯</strong></td><td>차가버섯</td></tr>
            <tr><td>면역력 전반</td><td><strong>상황버섯</strong></td><td>영지버섯</td></tr>
            <tr><td>항산화 / 노화방지</td><td><strong>차가버섯</strong></td><td>상황버섯</td></tr>
            <tr><td>수면 / 스트레스</td><td><strong>영지버섯</strong></td><td>동충하초</td></tr>
            <tr><td>호흡기 건강</td><td><strong>동충하초</strong></td><td>영지버섯</td></tr>
            <tr><td>간 건강</td><td><strong>상황버섯</strong></td><td>영지버섯</td></tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function EfficacyPage() {
  const [activePage, setActivePage] = useState('intro');

  const renderContent = () => {
    switch (activePage) {
      case 'intro': return <IntroSection />;
      case 'benefits': return <BenefitsSection />;
      case 'research': return <ResearchSection />;
      case 'usage': return <UsageSection />;
      case 'compare': return <CompareSection />;
      default: return <IntroSection />;
    }
  };

  return (
    <>
      <div className="page-header">
        <Container>
          <h1 className="page-header-title">효능효과</h1>
          <p className="page-header-desc">
            상황버섯의 과학적으로 검증된 효능과 올바른 복용법을 안내합니다
          </p>
        </Container>
      </div>

      <section className="shop-section">
        <Container>
          <Row>
            <Col lg={3}>
              <nav className="efficacy-nav">
                {pages.map(({ id, title, icon }) => (
                  <button
                    key={id}
                    className={`efficacy-nav-item ${activePage === id ? 'active' : ''}`}
                    onClick={() => { setActivePage(id); window.scrollTo({ top: 200, behavior: 'smooth' }); }}
                  >
                    {icon} {title}
                  </button>
                ))}
              </nav>
            </Col>
            <Col lg={9}>
              {renderContent()}

              <div className="efficacy-cta">
                <h3>고흥뜰에의 프리미엄 상황버섯</h3>
                <p>AI 스마트팜에서 최적의 환경으로 재배한 무농약 상황버섯을 만나보세요</p>
                <Link to="/products" className="btn-shop-primary" style={{ display: 'inline-flex' }}>
                  상품 보러가기 →
                </Link>
              </div>
            </Col>
          </Row>
        </Container>
      </section>
    </>
  );
}
