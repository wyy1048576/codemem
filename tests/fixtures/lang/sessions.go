package auth

import "fmt"

// RevokeSession deletes one session.
// It is idempotent.
func RevokeSession(id string) error {
	return db.Sessions.Delete(id)
}

type Manager struct {
	timeout int
}

type Store interface {
	Delete(id string) error
}

func (m *Manager) ExpireOld(now int) {
	isOld := func(s Session) bool { return s.Age(now) > m.timeout }
	for _, s := range m.All() {
		if isOld(s) {
			RevokeSession(s.ID)
		}
	}
}

var defaultTimeout = 30

func TestDisable(t *testing.T) { DisableUser(u) }
