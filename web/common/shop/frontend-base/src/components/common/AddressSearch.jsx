import { Button, Form, InputGroup } from 'react-bootstrap';

export default function AddressSearch({ zipcode, address, addressDetail, onChange }) {
  const openPostcode = () => {
    new window.daum.Postcode({
      oncomplete(data) {
        const fullAddr = data.roadAddress || data.jibunAddress;
        onChange({
          zipcode: data.zonecode,
          address: fullAddr,
        });
      },
    }).open();
  };

  return (
    <>
      <Form.Group className="mb-2">
        <Form.Label>우편번호</Form.Label>
        <InputGroup>
          <Form.Control type="text" value={zipcode || ''} readOnly placeholder="우편번호" />
          <Button variant="outline-secondary" onClick={openPostcode} style={{ whiteSpace: 'nowrap' }}>
            주소 찾기
          </Button>
        </InputGroup>
      </Form.Group>
      <Form.Group className="mb-2">
        <Form.Control type="text" value={address || ''} readOnly placeholder="주소" />
      </Form.Group>
      <Form.Group className="mb-3">
        <Form.Control type="text" value={addressDetail || ''} placeholder="상세주소 입력"
          onChange={(e) => onChange({ addressDetail: e.target.value })} />
      </Form.Group>
    </>
  );
}
