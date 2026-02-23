import {Button, Col, Form, InputGroup, Row} from "react-bootstrap";

export default function RegisterIdInput({value, onChange, onClick, smLabel = 4, required = false, isAvailable}) {
    return (
        <Form.Group as={Row} className="mb-3" controlId="formUserId">
            <Form.Label column sm={smLabel}>
                아이디 {required && <span style={{color: "red"}}>*</span>}
            </Form.Label>
            <Col sm={12 - smLabel}>
                <InputGroup>
                    <Form.Control
                        name="userId"
                        value={value}
                        onChange={onChange}
                        placeholder="아이디 입력"
                        pattern="^[a-zA-Z0-9]{4,12}$"
                        required={required}
                    />
                    <Button variant="secondary" onClick={onClick}>중복확인</Button>
                </InputGroup>
                {isAvailable !== null && (
                    <Form.Text className={!isAvailable ? "text-success" : "text-danger"}>
                        {!isAvailable ? "사용 가능한 아이디입니다." : "이미 사용 중인 아이디입니다."}
                    </Form.Text>
                )}
            </Col>
        </Form.Group>
    );
}
