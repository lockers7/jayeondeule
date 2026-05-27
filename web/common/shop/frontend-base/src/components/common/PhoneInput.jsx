import { Form } from 'react-bootstrap';

function formatPhone(value) {
  const nums = value.replace(/\D/g, '').slice(0, 11);
  if (nums.length <= 3) return nums;
  if (nums.length <= 7) return nums.slice(0, 3) + '-' + nums.slice(3);
  return nums.slice(0, 3) + '-' + nums.slice(3, 7) + '-' + nums.slice(7);
}

export default function PhoneInput({ value, onChange, ...props }) {
  const handleChange = (e) => {
    onChange(formatPhone(e.target.value));
  };

  return (
    <Form.Control
      type="tel"
      value={value || ''}
      onChange={handleChange}
      placeholder="010-0000-0000"
      maxLength={13}
      {...props}
    />
  );
}
