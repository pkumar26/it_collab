// Validates REQ-014: create-user payload validation.
// Covers AC-1 (400 on missing fields), AC-2 (structured errors), AC-3 (201 valid).

const assert = require('node:assert');
const test = require('node:test');
const { validatePayload, createUserHandler } = require('../generated/create_user.js');

function mockRes() {
  return {
    statusCode: null,
    body: null,
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(payload) {
      this.body = payload;
      return this;
    },
  };
}

// AC-1: missing required fields -> 400
test('AC-1: returns 400 when required fields are missing', () => {
  const res = mockRes();
  createUserHandler(() => ({}))({ body: { name: 'Ada' } }, res);
  assert.strictEqual(res.statusCode, 400);
});

// AC-2: structured error list
test('AC-2: returns a structured errors array', () => {
  const errors = validatePayload({ name: '' });
  assert.ok(Array.isArray(errors));
  assert.ok(errors.length > 0);
  for (const e of errors) {
    assert.ok(typeof e.field === 'string');
    assert.ok(typeof e.message === 'string');
  }
});

// AC-3: valid payload -> 201
test('AC-3: accepts a valid payload with 201', () => {
  const res = mockRes();
  const persist = (u) => ({ id: 1, ...u });
  createUserHandler(persist)(
    { body: { email: 'ada@example.com', name: 'Ada' } },
    res,
  );
  assert.strictEqual(res.statusCode, 201);
  assert.strictEqual(res.body.email, 'ada@example.com');
});
