import { db } from "./db";

/** Revoke one session. */
export function revokeSession(id: string): void {
  db.sessions.delete(id);
}

export const disableUser = async (user: User) => {
  user.active = false;
  user.sessions.forEach((s) => revokeSession(s));
};

export default class SessionManager<T> extends Base implements Mgr {
  private timeout = 30;
  handler = () => this.expire();
  constructor(private store: Store) { super(); }
  @log
  async expireOld(now: number): Promise<void> {
    const isOld = (s) => s.age(now) > this.timeout;
    this.all().filter(isOld).forEach(revokeSession);
  }
  get count(): number { return this.all().length; }
}

interface Mgr { expireOld(now: number): Promise<void>; }
enum Kind { A, B }
type Alias = string;
namespace Auth { export function inner() { return 1; } }
function* gen() { yield 1; }
module.exports.legacy = function () { return 2; };
describe("users", () => { it("loses sessions", () => { disableUser(u); }); });
