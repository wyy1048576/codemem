package auth;

import java.util.List;

/** Session storage. */
public class SessionManager extends Base {
    private int timeout = 30;

    public SessionManager(Store s) { this.store = s; }

    /** Revoke one session. */
    @Override
    public void revokeSession(String id) {
        db.sessions().delete(id);
        new Audit(id).record();
    }

    static class Inner { void helper() {} }

    interface Listener { void onRevoke(String id); }
}

enum Kind { A, B; Kind next() { return B; } }

record Point(int x, int y) { int sum() { return x + y; } }
