// @traces REQ-014
// Generated artifact: create-user endpoint payload validation.
// Success criteria: AC-1 (400 on missing fields), AC-2 (structured errors),
// AC-3 (201 on valid payload).

'use strict';

const REQUIRED_FIELDS = ['email', 'name'];

/**
 * Validate a create-user payload. Returns a list of structured errors,
 * each with a `field` and a human-readable `message`. Empty list == valid.
 */
function validatePayload(payload) {
  const errors = [];
  if (payload == null || typeof payload !== 'object') {
    errors.push({ field: '<body>', message: 'Request body must be a JSON object' });
    return errors;
  }
  for (const field of REQUIRED_FIELDS) {
    const value = payload[field];
    if (value === undefined || value === null || value === '') {
      errors.push({ field, message: `Field '${field}' is required` });
    }
  }
  if (payload.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(payload.email)) {
    errors.push({ field: 'email', message: 'Field email must be a valid address' });
  }
  return errors;
}

/**
 * Express-style handler. Rejects malformed requests with HTTP 400 and a
 * structured `errors` array BEFORE any persistence occurs; returns 201 on success.
 */
function createUserHandler(persist) {
  return function handle(req, res) {
    const errors = validatePayload(req.body);
    if (errors.length > 0) {
      return res.status(400).json({ errors });
    }
    const user = persist(req.body);
    return res.status(201).json(user);
  };
}

module.exports = { validatePayload, createUserHandler, REQUIRED_FIELDS };
