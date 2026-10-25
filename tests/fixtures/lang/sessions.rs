use crate::db;

/// Revoke one session.
pub fn revoke_session(id: &str) {
    db::sessions().delete(id);
}

pub struct Manager { timeout: u32 }

impl Manager {
    pub fn new() -> Self { Manager { timeout: 30 } }
    fn expire_old(&self, now: u32) {
        let is_old = |s: &Session| s.age(now) > self.timeout;
        self.all().iter().filter(is_old).for_each(|s| revoke_session(&s.id));
    }
}

impl Store for Manager { fn delete(&self, id: &str) {} }

trait Store { fn delete(&self, id: &str); }

enum Kind { A, B }

mod tests {
    #[test]
    fn disabled_user_loses_sessions() { disable_user(u); }
}

macro_rules! log { ($x:expr) => { println!("{}", $x) }; }
const MAX: u32 = 3;
