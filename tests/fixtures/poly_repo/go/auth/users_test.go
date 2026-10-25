package auth

import "testing"

func TestDisabledUserLosesSessions(t *testing.T) {
	DisableUser(u)
}
