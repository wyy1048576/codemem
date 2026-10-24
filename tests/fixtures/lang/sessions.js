const db = require("./db");

/**
 * Revoke one session.
 */
function revokeSession(id) {
  db.sessions.delete(id);
}

class SessionManager extends Base {
  timeout = 30;
  expireOld(now) { return this.all().filter((s) => s.age(now) > this.timeout); }
  static create() { return new SessionManager(); }
}

const disableUser = function (user) { revokeSession(user.sid); };
exports.revokeSession = revokeSession;
